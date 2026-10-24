"""Stall watch: what the game's threads do while it hangs.

`quadrahq --watch-stalls` waits for the game and then records, ten times a
second, how much CPU each thread used; for the busy ones it also stops the
thread for a moment and reads where it is (instruction pointer and the frame
chain), and once a second it notes every blocked thread's system call and the
likely return addresses on its stack. Everything goes to a JSON-lines file.
When the game ends (or on Ctrl-C) the file is turned into a report that lines
the threads up against the launch log's markers: joining, leaving, swapchain
timeouts. A hang then reads as "the thread named X used 100% of a core in
function Y for 14 s" or "X waited in futex from the moment of leaving".

Reading another process's stacks needs ptrace permission. Under Yama
(kernel.yama.ptrace_scope=1) the game must allow it: the shim does when the
game was started with MACOBLOX_ALLOW_DEBUGGER=1 (Settings -> Environment ->
allow freeze diagnostics). Without that only the CPU timeline is recorded.
Each stop lasts about a tenth of a millisecond, at most three threads per
tenth of a second.
"""
import bisect
import ctypes
import datetime
import json
import os
import re
import signal
import struct
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

from . import diagnostics

PTRACE_GETREGS = 12
PTRACE_DETACH = 17
PTRACE_SEIZE = 0x4206
PTRACE_INTERRUPT = 0x4207
WALL = 0x40000000  # __WALL: wait for threads, not only child processes
RBP, RIP, RSP = 4, 16, 19  # indexes in struct user_regs_struct (x86_64)
REGISTER_WORDS = 27

INTERVAL = 0.1
CENSUS_INTERVAL = 1.0
MAPS_INTERVAL = 3.0
STOP_TIMEOUT = 0.1
MAX_STOPS = 3
MIN_INTERVAL = 0.05  # a faster loop would stop the game's threads too often
MAX_STOPS_PER_SECOND = 60  # whatever else goes wrong, the game is never stopped more often than this
BUSY_FRACTION = 0.2  # of an interval on the CPU for a thread to be worth stopping
STACK_BYTES = 8192
LULL_FRACTION = 0.3  # of a core, over half-second buckets
LULL_SECONDS = 3.0
FUTEX = 202
CANDIDATES = 12
FRAMES = 24
MAX_FILE_BYTES = 150 * 1024 * 1024

# x86_64 Linux system calls a game's threads wait in.
SYSCALLS = {0: "read", 1: "write", 7: "poll", 17: "pread64", 23: "select", 35: "nanosleep", 43: "accept",
            45: "recvfrom", 46: "sendmsg", 47: "recvmsg", 61: "wait4", 202: "futex", 230: "clock_nanosleep",
            232: "epoll_wait", 270: "pselect6", 271: "ppoll", 281: "epoll_pwait"}

MARKERS = (
    (re.compile(r"launchUGCGameInternal"), "join"),
    (re.compile(r"Game join succeeded"), "join accepted"),
    (re.compile(r"Terrain TextureArray"), "terrain texture array"),
    (re.compile(r"returnToLuaApp: \(stage:UGCGame\)|leaveUGCGameInternal"), "leave"),
    (re.compile(r"replaceDataModel"), "replace data model"),
    (re.compile(r"Replicator destroyed"), "replicator destroyed"),
    (re.compile(r"nextDrawable timed out"), "swapchain timeout"),
    (re.compile(r"\[Quadra Metal\] buffer of"), "large buffer"),
    (re.compile(r"\[Quadra Metal\] render pipelines"), "pipelines"),
    (re.compile(r"\[Quadra Input\]"), "input"),
)
KEY_MARKERS = ("join", "leave")
DEDUPLICATE = 5.0
LOG_TIME = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d+)Z,")


# ------------------------------------------------------------------ reading

class Regions:
    """The game's executable file mappings, by address."""

    def __init__(self, pid):
        self.items = sorted(diagnostics._mappings(pid))
        self.starts = [item[0] for item in self.items]
        self.low = self.starts[0] if self.items else 0
        self.high = max((item[1] for item in self.items), default=0)

    def locate(self, address):
        """(library path, file offset) of a code address, or None."""
        if not self.low <= address < self.high:
            return None
        index = bisect.bisect_right(self.starts, address) - 1
        if index >= 0:
            start, end, offset, path = self.items[index]
            if address < end:
                return path, address - start + offset
        return None


class Memory:
    """/proc/PID/mem of the game, read-only."""

    def __init__(self, pid):
        self.descriptor = os.open(f"/proc/{pid}/mem", os.O_RDONLY)

    def read(self, address, size):
        try:
            return os.pread(self.descriptor, size, address)
        except (OSError, OverflowError, ValueError):
            return b""

    def close(self):
        os.close(self.descriptor)


def frame_chain(memory, regions, pc, rbp, rsp, depth=FRAMES):
    """Code addresses of a thread, innermost first: its instruction pointer,
    the word at the top of its stack when that is code (a function that has
    not built its frame yet, such as a system call stub, was called from
    there) and then the saved frame pointers' return addresses. Mach-O code
    keeps frame pointers."""
    frames = [pc]
    top = memory.read(rsp, 8)
    if len(top) == 8:
        word = struct.unpack("<Q", top)[0]
        if regions.locate(word):
            frames.append(word)
    previous = 0
    for _unused in range(depth):
        if rbp < 0x1000 or rbp & 7 or rbp <= previous:
            break
        data = memory.read(rbp, 16)
        if len(data) < 16:
            break
        saved, ret = struct.unpack("<QQ", data)
        if not regions.locate(ret):
            break
        if ret != frames[-1]:
            frames.append(ret)
        previous, rbp = rbp, saved
    return frames


def stack_candidates(memory, regions, stack_pointer, count=CANDIDATES):
    """Words near the top of a blocked thread's stack that point into code."""
    size = STACK_BYTES - stack_pointer % STACK_BYTES  # not across a page group that may be unmapped
    data = memory.read(stack_pointer, size)
    words = struct.unpack(f"<{len(data) // 8}Q", data[:len(data) // 8 * 8])
    found = []
    for word in words:
        if regions.low <= word < regions.high and regions.locate(word):
            found.append(word)
            if len(found) >= count:
                break
    return found


def _timespec_ms(memory, address, size=16, microseconds=False):
    data = memory.read(address, size) if address else b""
    if len(data) < 16:
        return None
    seconds, fraction = struct.unpack("<qq", data[:16])
    return seconds * 1000.0 + fraction / (1e3 if microseconds else 1e6)


def decode_wait(fields, memory):
    """What a blocked thread waits on and for how long, from the fields of
    /proc/PID/task/TID/syscall ("nr arg1..arg6 sp pc"): {"fx": [futex address,
    word], "to": milliseconds until it times out, "abs": the timeout was a
    deadline, "raw": the timeout as the caller wrote it}. Empty when the call
    has neither."""
    if len(fields) < 9:
        return {}
    try:
        number, args = int(fields[0]), [int(value, 16) for value in fields[1:7]]
    except ValueError:
        return {}
    info, timeout, deadline, clock = {}, None, False, 1
    signed = lambda value: value - (1 << 32) if value & 0x80000000 else value  # noqa: E731
    if number == FUTEX:
        word = memory.read(args[0], 4)
        info["fx"] = [args[0], struct.unpack("<I", word)[0] if len(word) == 4 else None]
        command = args[1] & 0x7f
        if command in (0, 9):
            timeout, deadline = _timespec_ms(memory, args[3]), command == 9
            clock = 0 if args[1] & 256 else 1
    elif number == 7:  # poll
        value = signed(args[2] & 0xffffffff)
        timeout = None if value < 0 else float(value)
    elif number in (232, 281):  # epoll_wait, epoll_pwait
        value = signed(args[3] & 0xffffffff)
        timeout = None if value < 0 else float(value)
    elif number in (271, 270):  # ppoll, pselect6
        timeout = _timespec_ms(memory, args[2] if number == 271 else args[4])
    elif number == 23:  # select
        timeout = _timespec_ms(memory, args[4], microseconds=True)
    elif number == 35:  # nanosleep
        timeout = _timespec_ms(memory, args[0])
    elif number == 230:  # clock_nanosleep
        timeout, deadline, clock = _timespec_ms(memory, args[2]), bool(args[1] & 1), args[0] & 0xf
    if timeout is not None:
        info["raw"] = round(timeout, 3)
        if deadline:
            try:
                timeout -= time.clock_gettime(time.CLOCK_REALTIME if clock == 0 else time.CLOCK_MONOTONIC) * 1000.0
            except (OSError, ValueError):
                pass
            info["abs"] = True
        info["to"] = round(timeout, 1)
    return info


class Tracer:
    """Stops one thread for an instant and reads its registers."""

    def __init__(self):
        self.libc = ctypes.CDLL(None, use_errno=True)
        self.libc.ptrace.argtypes = [ctypes.c_long, ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p]
        self.libc.ptrace.restype = ctypes.c_long

    def registers(self, tid):
        """(pc, frame pointer, stack pointer) of a thread, or None."""
        ptrace = self.libc.ptrace
        if ptrace(PTRACE_SEIZE, tid, None, None) != 0:
            return None
        try:
            if ptrace(PTRACE_INTERRUPT, tid, None, None) != 0:
                return None
            deadline = time.monotonic() + STOP_TIMEOUT
            while True:
                try:
                    pid, status = os.waitpid(tid, WALL | os.WNOHANG)
                except ChildProcessError:
                    return None
                if pid:
                    break
                if time.monotonic() > deadline:
                    return None
                time.sleep(0.0002)
            if not os.WIFSTOPPED(status):
                return None
            buffer = (ctypes.c_ulonglong * REGISTER_WORDS)()
            if ptrace(PTRACE_GETREGS, tid, None, ctypes.byref(buffer)) != 0:
                return None
            return buffer[RIP], buffer[RBP], buffer[RSP]
        finally:
            ptrace(PTRACE_DETACH, tid, None, None)


def can_trace(pid):
    """Whether this user may read the game's stacks (see the module note)."""
    try:
        Path(f"/proc/{pid}/syscall").read_text()
        return True
    except OSError:
        return False


def _cpu_nanoseconds(pid, tid):
    try:
        with open(f"/proc/{pid}/task/{tid}/schedstat", "rb") as file:
            return int(file.read().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def _alive(pid):
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return False
    return stat.rsplit(")", 1)[-1].split()[0] not in ("Z", "X")


# ----------------------------------------------------------------- sockets

TCP_STATES = {"01": "ESTABLISHED", "02": "SYN_SENT", "03": "SYN_RECV", "04": "FIN_WAIT1", "05": "FIN_WAIT2",
              "06": "TIME_WAIT", "07": "CLOSE", "08": "CLOSE_WAIT", "09": "LAST_ACK", "0A": "LISTEN",
              "0B": "CLOSING"}


def _address(text):
    """'0100007F:01BB' -> '127.0.0.1:443' (IPv4; IPv6 stays hexadecimal)."""
    host, _separator, port = text.partition(":")
    try:
        if len(host) == 8:
            host = ".".join(str(int(host[index:index + 2], 16)) for index in (6, 4, 2, 0))
        return f"{host}:{int(port, 16)}"
    except ValueError:
        return text


def socket_table(pid):
    """{fd: {"p": protocol, "st": state, "rx": unread bytes, "tx": unsent bytes, "to": remote address}} of
    the process's TCP and UDP sockets. A receive queue with bytes in it while the owner sleeps in kevent
    is how a lost edge-triggered readiness event shows."""
    inodes = {}
    try:
        for entry in os.listdir(f"/proc/{pid}/fd"):
            try:
                target = os.readlink(f"/proc/{pid}/fd/{entry}")
            except OSError:
                continue
            if target.startswith("socket:["):
                inodes[target[8:-1]] = int(entry)
    except OSError:
        return {}
    found = {}
    for protocol in ("tcp", "tcp6", "udp", "udp6"):
        try:
            lines = Path(f"/proc/{pid}/net/{protocol}").read_text().splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            fields = line.split()
            if len(fields) < 10 or fields[9] not in inodes:
                continue
            transmit, _separator, receive = fields[4].partition(":")
            kind = protocol.rstrip("6")
            found[inodes[fields[9]]] = {"p": kind, "st": TCP_STATES.get(fields[3], fields[3]) if kind == "tcp" else "",
                                       "rx": int(receive, 16), "tx": int(transmit, 16), "to": _address(fields[2])}
    return found


def unread_table(pid):
    """{fd: bytes waiting} for the process's pipes and sockets, asked of a duplicate of each descriptor
    (pidfd_getfd shares the open file, so nothing is consumed and the game is not touched). Only descriptors
    with bytes waiting are returned. This is how a lost edge-triggered wake-up of a kqueue loop shows: the
    loop's interrupter pipe holds a byte that nobody read."""
    import fcntl
    import termios
    found = {}
    try:
        pidfd = os.pidfd_open(pid)
    except (OSError, AttributeError):
        return found
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        for entry in os.listdir(f"/proc/{pid}/fd"):
            try:
                target = os.readlink(f"/proc/{pid}/fd/{entry}")
            except OSError:
                continue
            if not target.startswith(("pipe:", "socket:")):
                continue
            duplicate = libc.syscall(438, pidfd, int(entry), 0)  # SYS_pidfd_getfd
            if duplicate < 0:
                continue
            try:
                waiting = struct.unpack("i", fcntl.ioctl(duplicate, termios.FIONREAD, struct.pack("i", 0)))[0]
            except OSError:
                waiting = 0
            finally:
                os.close(duplicate)
            if waiting > 0:
                found[int(entry)] = ("pipe" if target.startswith("pipe:") else "socket", waiting)
    finally:
        os.close(pidfd)
    return found


def _fdinfo(pid, fd):
    try:
        return Path(f"/proc/{pid}/fdinfo/{fd}").read_text()
    except OSError:
        return ""


def wake_table(pid):
    """What a kqueue loop is woken by. Darling emulates kqueue on epoll, timers on timerfds and
    user events on eventfds, all readable without touching the game:
    {"efd": {fd: count of unconsumed signals}, "tfd": {fd: (seconds until it fires, interval)},
     "ep": {fd: sorted fds it watches}}."""
    found = {"efd": {}, "tfd": {}, "ep": {}}
    try:
        entries = os.listdir(f"/proc/{pid}/fd")
    except OSError:
        return found
    for entry in entries:
        try:
            target = os.readlink(f"/proc/{pid}/fd/{entry}")
        except OSError:
            continue
        if not target.startswith("anon_inode:"):
            continue
        fd, info = int(entry), _fdinfo(pid, entry)
        if target.endswith("[eventfd]"):
            match = re.search(r"eventfd-count:\s*(\d+)", info)
            if match:
                found["efd"][fd] = int(match[1])
        elif target.endswith("[timerfd]"):
            value = re.search(r"it_value: \((\d+), (\d+)\)", info)
            interval = re.search(r"it_interval: \((\d+), (\d+)\)", info)
            if value:
                found["tfd"][fd] = (int(value[1]) + int(value[2]) / 1e9,
                                    int(interval[1]) + int(interval[2]) / 1e9 if interval else 0.0)
        elif target.endswith("[eventpoll]"):
            found["ep"][fd] = sorted(int(match) for match in re.findall(r"tfd:\s*(\d+)", info))
    return found


# ----------------------------------------------------------------- capture

class Recorder:
    """Appends JSON lines and stops at a size limit (keeping the CPU lines)."""

    def __init__(self, path):
        self.file = open(path, "w", buffering=1 << 16)
        self.size = 0
        self.truncated = False

    def write(self, record, essential=False):
        if self.size > MAX_FILE_BYTES and not essential:
            self.truncated = True
            return
        line = json.dumps(record, separators=(",", ":")) + "\n"
        self.size += len(line)
        self.file.write(line)

    def flush(self):
        self.file.flush()

    def close(self):
        self.file.close()


def capture(pid, path, *, interval=INTERVAL, trace=True, stop=lambda: False, servers=()):
    """Record the game's threads until it exits or `stop()` is true. Returns
    whether stacks could be read. `servers` are darlingserver processes whose
    CPU use is recorded beside the game's."""
    interval = max(interval, MIN_INTERVAL)
    recorder = Recorder(path)
    try:
        memory = Memory(pid)
    except OSError:
        memory = None  # no ptrace permission (see the module note)
    regions = Regions(pid)
    tracer = Tracer() if trace and memory and can_trace(pid) else None
    stacks = tracer is not None
    recorder.write({"k": "meta", "t": time.time(), "pid": pid, "interval": interval, "stacks": stacks,
                    "servers": list(servers)}, essential=True)
    cpu_before, names, census_before, in_futex = {}, {}, {}, {}
    socket_before = {}
    wake_before = {"efd": {}, "tfd": {}, "ep": {}}
    unread_before = {}
    server_before = {}
    skip_until = {}
    last_census = last_maps = 0.0
    stop_second, stops_this_second = 0, 0
    try:
        while _alive(pid) and not stop():
            started = time.monotonic()
            now = time.time()
            if started - last_maps >= MAPS_INTERVAL:
                regions, last_maps = Regions(pid), started
            deltas = {}
            for tid in diagnostics._threads(pid):
                nanoseconds = _cpu_nanoseconds(pid, tid)
                if nanoseconds is None:
                    continue
                before = cpu_before.get(tid)
                cpu_before[tid] = nanoseconds
                if before is not None and nanoseconds - before >= 1_000_000:
                    deltas[tid] = round((nanoseconds - before) / 1e6, 1)
            if deltas:
                recorder.write({"k": "cpu", "t": round(now, 3), "d": deltas}, essential=True)
            served = {}
            for server in servers:
                for tid in diagnostics._threads(server):
                    nanoseconds = _cpu_nanoseconds(server, tid)
                    before = server_before.get(tid)
                    if nanoseconds is not None:
                        server_before[tid] = nanoseconds
                        if before is not None and nanoseconds - before >= 1_000_000:
                            served[tid] = round((nanoseconds - before) / 1e6, 1)
            if served:
                recorder.write({"k": "srv", "t": round(now, 3), "d": served}, essential=True)
            if tracer:
                busy = sorted((tid for tid, ms in deltas.items()
                               if ms >= interval * 1000 * BUSY_FRACTION and skip_until.get(tid, 0) < started),
                              key=lambda tid: -deltas[tid])[:MAX_STOPS]
                # The game's main thread is also read while it waits, unless
                # that is a futex wait: stopping a futex waiter makes it check
                # the word again, which could end a lost wakeup being watched.
                waiting = [pid] if pid not in busy and not in_futex.get(pid) and skip_until.get(pid, 0) < started else []
                if int(started) != stop_second:
                    stop_second, stops_this_second = int(started), 0
                for tid in busy + waiting:
                    if stops_this_second >= MAX_STOPS_PER_SECOND:
                        break
                    stops_this_second += 1
                    found = tracer.registers(tid)
                    if not found:
                        skip_until[tid] = started + 5.0
                        continue
                    frames = frame_chain(memory, regions, *found)
                    record = {"k": "run", "t": round(time.time(), 3), "tid": tid,
                              "f": [regions.locate(address) or hex(address) for address in frames]}
                    if tid in waiting:
                        record["w"] = 1
                    recorder.write(record)
            if started - last_census >= CENSUS_INTERVAL:
                last_census = started
                for tid in diagnostics._threads(pid):
                    sample = diagnostics._thread_sample(pid, tid)
                    name = sample.get("name", "")
                    if names.get(tid) != name:
                        names[tid] = name
                        recorder.write({"k": "name", "t": round(now, 3), "tid": tid, "name": name}, essential=True)
                    syscall = sample.get("syscall", "")
                    fields = [] if syscall.startswith("<") or syscall == "running" else syscall.split()
                    in_futex[tid] = bool(fields) and fields[0] == str(FUTEX)
                    detail = decode_wait(fields, memory) if memory and fields else {}
                    state = (sample.get("state"), fields[0] if fields else "", fields[-1] if fields else "",
                             tuple(detail.get("fx") or ()), detail.get("raw"))
                    if census_before.get(tid) == state:
                        continue
                    census_before[tid] = state
                    record = {"k": "wait", "t": round(now, 3), "tid": tid, "state": sample.get("state"),
                              "wchan": sample.get("wchan"), "syscall": fields[0] if fields else ""}
                    if memory and fields:
                        record["x"] = detail  # empty: decoded, no timeout and no futex
                    if memory and len(fields) >= 3 and fields[-2].startswith("0x"):
                        pc, stack_pointer = int(fields[-1], 16), int(fields[-2], 16)
                        record["pc"] = regions.locate(pc) or hex(pc)
                        record["s"] = [regions.locate(address) for address in
                                       stack_candidates(memory, regions, stack_pointer)]
                    recorder.write(record)
                sockets = socket_table(pid)
                for fd, info in sockets.items():
                    signature = (info["p"], info["st"], info["rx"] > 0, info["tx"] > 0, info["to"])
                    if socket_before.get(fd) != signature:
                        socket_before[fd] = signature
                        recorder.write({"k": "sock", "t": round(now, 3), "fd": fd, **info})
                for fd in [fd for fd in socket_before if fd not in sockets]:
                    del socket_before[fd]
                    recorder.write({"k": "sock", "t": round(now, 3), "fd": fd, "gone": 1})
                wakes = wake_table(pid)
                for fd, count in wakes["efd"].items():
                    if wake_before["efd"].get(fd) != count:
                        recorder.write({"k": "efd", "t": round(now, 3), "fd": fd, "n": count})
                for fd, (remaining, repeat) in wakes["tfd"].items():
                    previous = wake_before["tfd"].get(fd)  # (recorded at, remaining then)
                    if previous is None or abs((previous[1] - (now - previous[0])) - remaining) > 0.25:
                        wake_before["tfd"][fd] = (now, remaining)
                        recorder.write({"k": "tfd", "t": round(now, 3), "fd": fd, "v": round(remaining, 3),
                                        "i": round(repeat, 3)})
                for fd, watched in wakes["ep"].items():
                    if wake_before["ep"].get(fd) != watched:
                        recorder.write({"k": "ep", "t": round(now, 3), "fd": fd, "w": watched})
                wake_before["efd"], wake_before["ep"] = wakes["efd"], wakes["ep"]
                unread = unread_table(pid)
                for fd, (kind, waiting) in unread.items():
                    if unread_before.get(fd) is None:
                        recorder.write({"k": "rd", "t": round(now, 3), "fd": fd, "p": kind, "n": waiting})
                for fd in unread_before:
                    if fd not in unread:
                        recorder.write({"k": "rd", "t": round(now, 3), "fd": fd, "n": 0})
                unread_before = {fd: True for fd in unread}
                recorder.flush()
            time.sleep(max(0.0, interval - (time.monotonic() - started)))
    finally:
        recorder.write({"k": "end", "t": time.time(), "truncated": recorder.truncated}, essential=True)
        recorder.close()
        if memory:
            memory.close()
    return stacks


# ------------------------------------------------------------------ report

def load(path):
    """The records of a capture file, bad lines skipped."""
    records = []
    with open(path) as file:
        for line in file:
            try:
                records.append(json.loads(line))
            except ValueError:
                pass
    return records


def log_markers(path, start, end):
    """[(epoch seconds, label, line)] of the launch log's markers in [start, end]."""
    found, latest = [], {}
    try:
        lines = Path(path).read_text(errors="replace").splitlines()
    except OSError:
        return found
    for line in lines:
        timestamp = LOG_TIME.match(line)
        if not timestamp:
            continue
        for pattern, label in MARKERS:
            if pattern.search(line):
                moment = datetime.datetime.fromisoformat(timestamp.group(1)).replace(
                    tzinfo=datetime.timezone.utc).timestamp()
                # A burst of one kind (or one event logged twice) is one marker.
                if start - 1 <= moment <= end + 1 and moment - latest.get(label, -DEDUPLICATE) >= DEDUPLICATE:
                    found.append((moment, label, line.split(" ", 1)[-1][:120]))
                    latest[label] = moment
                break
    return found


def _name_of(symbols, location):
    """'library!function' for a (path, offset) location."""
    if not isinstance(location, (list, tuple)):
        return str(location)
    path, offset = location
    name = symbols.get((path, offset))
    library = Path(path).name
    return f"{library}!{name}" if name else f"{library}+0x{offset:x}"


def _locations(records):
    wanted = set()
    for record in records:
        for key in ("f", "s"):
            for location in record.get(key) or ():
                if isinstance(location, (list, tuple)):
                    wanted.add(tuple(location))
        if isinstance(record.get("pc"), (list, tuple)):
            wanted.add(tuple(record["pc"]))
    return wanted


def render(records, markers, symbols, *, before=2, after=40, everything=False, top_threads=3):
    """The report text."""
    meta = next((record for record in records if record["k"] == "meta"), {})
    cpu = [record for record in records if record["k"] == "cpu"]
    start = meta.get("t") or (cpu[0]["t"] if cpu else 0)
    end = max((record["t"] for record in records), default=start)
    names = {}
    for record in records:
        if record["k"] == "name":
            names[record["tid"]] = record["name"]

    def label(tid):
        return f"{names.get(tid) or '?'}[{tid}]"

    lines = [f"Game process {meta.get('pid', '?')}, {end - start:.0f} s recorded, "
             f"{'stacks' if meta.get('stacks') else 'no stacks (the game did not allow ptrace)'}"]
    if records and records[-1].get("truncated"):
        lines.append("The capture file reached its size limit: later stacks are missing.")
    if markers:
        lines.append("\nMarkers (seconds from the start of the capture):")
        for moment, tag, text in markers:
            lines.append(f"  {moment - start:8.1f}  {tag:22} {text}")
    windows = [(moment - before, moment + after, tag) for moment, tag, _text in markers if tag in KEY_MARKERS]
    if everything or not windows:
        windows = [(start, end, "whole capture")]

    for first, last, tag in windows:
        lines.append(f"\n== {tag} at {first + before - start:.1f} s: CPU per second "
                     f"(threads above 10% of a core; the process total) ==" if tag != "whole capture"
                     else "\n== CPU per second ==")
        seconds = defaultdict(lambda: defaultdict(float))
        for record in cpu:
            if first <= record["t"] <= last:
                for tid, milliseconds in record["d"].items():
                    seconds[int(record["t"] - first)][int(tid)] += milliseconds
        leaves = defaultdict(Counter)
        for record in records:
            if record["k"] == "run" and not record.get("w") and first <= record["t"] <= last and record["f"]:
                leaves[(int(record["t"] - first), record["tid"])][_name_of(symbols, record["f"][0])] += 1
        for second in range(int(last - first) + 1):
            row = seconds.get(second, {})
            total = sum(row.values()) / 10.0
            parts = []
            for tid, milliseconds in sorted(row.items(), key=lambda item: -item[1])[:top_threads]:
                if milliseconds < 100:
                    continue
                part = f"{label(tid)} {milliseconds / 10:.0f}%"
                common = leaves.get((second, tid))
                if common:
                    part += f" in {common.most_common(1)[0][0]}"
                parts.append(part)
            lines.append(f"  {second + first - start:7.1f}  process {total:5.0f}%  {'; '.join(parts)}")

        busy = defaultdict(Counter)
        for record in records:
            if record["k"] == "run" and not record.get("w") and first <= record["t"] <= last and record["f"]:
                busy[record["tid"]][tuple(_name_of(symbols, location) for location in record["f"][:6])] += 1
        if busy:
            lines.append(f"\n== {tag}: where the busy threads were (stack samples) ==")
            ranked = sorted(busy.items(), key=lambda item: -sum(item[1].values()))
            for tid, counter in ranked[:6]:
                lines.append(f"  {label(tid)}: {sum(counter.values())} samples")
                for stack, count in counter.most_common(4):
                    lines.append(f"    {count:4}x  " + "  <-  ".join(stack))
        lines.extend(_new_waits(records, first, last, start, tag, label, symbols))
    for first, last in find_lulls(records, start, end):
        lines.extend(_lull(records, first, last, start, markers, label, symbols, bool(meta.get("servers"))))
    return "\n".join(lines) + "\n"


def _new_waits(records, first, last, start, tag, label, symbols, minimum=2.0):
    """Threads that began waiting in the window and used almost no CPU while
    they kept waiting."""
    end = max((record["t"] for record in records), default=last)
    by_thread = defaultdict(list)
    cpu = defaultdict(list)
    for record in records:
        if record["k"] == "wait":
            by_thread[record["tid"]].append(record)
        elif record["k"] == "cpu":
            for tid, milliseconds in record["d"].items():
                cpu[int(tid)].append((record["t"], milliseconds))
    found = []
    for tid, waits in by_thread.items():
        for index, record in enumerate(waits):
            if index == 0 or record["state"] not in ("S", "D") or not first <= record["t"] <= last:
                continue  # the first census only says where it already was
            until = waits[index + 1]["t"] if index + 1 < len(waits) else end
            used = sum(ms for moment, ms in cpu[tid] if record["t"] <= moment <= until)
            if until - record["t"] >= minimum and used < 20 * (until - record["t"]):
                found.append((record, until, used))
    if not found:
        return []
    lines = [f"\n== {tag}: threads that started waiting here and kept waiting for {minimum:.0f} s or more =="]
    for record, until, used in sorted(found, key=lambda item: item[0]["t"])[:20]:
        number = record.get("syscall", "")
        call = SYSCALLS.get(int(number), number) if number.lstrip("-").isdigit() else number
        lines.append(f"  {label(record['tid'])} from {record['t'] - start:.1f} s for {until - record['t']:.1f} s "
                     f"({used:.0f} ms of CPU): {call}, wchan {record.get('wchan') or '-'}, at "
                     f"{_name_of(symbols, record.get('pc', '?'))}")
        stack = [_name_of(symbols, location) for location in record.get("s") or () if location]
        if stack:
            lines.append("      stack: " + "  <-  ".join(stack[:6]))
    return lines


def find_lulls(records, start, end):
    """[(first, last)] epoch seconds of stretches of LULL_SECONDS or more in
    which the game used under LULL_FRACTION of one core."""
    buckets = int((end - start) * 2) + 1
    used = [0.0] * buckets
    for record in records:
        if record["k"] == "cpu":
            index = int((record["t"] - start) * 2)
            if 0 <= index < buckets:
                used[index] += sum(record["d"].values())
    lulls, first = [], None
    for index, milliseconds in enumerate(used + [1e9]):
        if milliseconds < LULL_FRACTION * 500:
            first = index if first is None else first
        elif first is not None:
            if (index - first) / 2 >= LULL_SECONDS:
                lulls.append((start + first / 2, start + index / 2))
            first = None
    return lulls


def _wait_text(record, start, symbols):
    """One line's worth of what a blocked thread waits on."""
    detail = record.get("x") or {}
    number = record.get("syscall", "")
    call = SYSCALLS.get(int(number), number) if number.lstrip("-").isdigit() else number
    parts = [call]
    if "fx" in detail:
        word = detail["fx"][1]
        parts.append(f"futex 0x{detail['fx'][0]:x} = {word if word is None else hex(word)}")
    if "to" in detail:
        wake = record["t"] - start + detail["to"] / 1000.0
        parts.append(f"times out in {detail['to'] / 1000.0:.1f} s (about {wake:.1f} s)")
    elif "x" in record and number in ("7", "232", "281", "271", "270", "23", "35", "230"):
        parts.append("no timeout")
    if number == "202" and "x" in record and "to" not in detail:
        parts.append("no timeout")
    return ", ".join(parts)


def _lull(records, first, last, start, markers, label, symbols, servers):
    """What the game was doing while it did almost nothing."""
    earlier = [marker for marker in markers if marker[0] <= first + 1.0]
    after = (f", {first - earlier[-1][0]:.1f} s after {earlier[-1][1]} at {earlier[-1][0] - start:.1f} s"
             if earlier and first - earlier[-1][0] < 30 else "")
    lines = [f"\n== lull from {first - start:.1f} s to {last - start:.1f} s: {last - first:.1f} s with under "
             f"{LULL_FRACTION * 100:.0f}% of a core{after} =="]
    used = Counter()
    for record in records:
        if record["k"] == "cpu" and first <= record["t"] <= last:
            for tid, milliseconds in record["d"].items():
                used[int(tid)] += milliseconds
    lines.append("  CPU in the lull: " + ("; ".join(f"{label(tid)} {ms:.0f} ms" for tid, ms in used.most_common(4))
                                         or "none"))
    if servers:
        served = sum(sum(record["d"].values()) for record in records
                     if record["k"] == "srv" and first <= record["t"] <= last)
        lines.append(f"  darlingserver CPU in the lull: {served:.0f} ms "
                     f"({served / (last - first) / 10:.1f}% of a core)")
    woke = {}
    for record in records:
        if record["k"] == "cpu" and last - 1.0 <= record["t"] <= last + 0.5:
            for tid, milliseconds in record["d"].items():
                if milliseconds >= 10 and int(tid) not in woke:
                    woke[int(tid)] = (record["t"] - start, milliseconds)
    if woke:
        lines.append("  first busy again: " + "; ".join(
            f"{label(tid)} at {when:.2f} s ({ms:.0f} ms)"
            for tid, (when, ms) in sorted(woke.items(), key=lambda item: item[1][0])[:3]))
    waiting = Counter()
    for record in records:
        if record["k"] == "run" and record.get("w") and first <= record["t"] <= last and record["f"]:
            waiting[tuple(_name_of(symbols, location) for location in record["f"][:10])] += 1
    if waiting:
        lines.append("  the main thread, sampled while it waited:")
        for stack, count in waiting.most_common(3):
            lines.append(f"    {count:4}x  " + "  <-  ".join(stack))
    middle = (first + last) / 2
    latest = {}
    for record in records:
        if record["k"] == "wait" and record["t"] <= middle:
            latest[record["tid"]] = record
    groups = defaultdict(list)
    for tid, record in latest.items():
        if record["state"] in ("S", "D"):
            detail = record.get("x") or {}
            groups[(_wait_text(record, start, symbols), _name_of(symbols, record.get("pc", "?")),
                    detail.get("raw"))].append(record)
    if groups:
        lines.append("  blocked threads in the middle of the lull, by what they wait on:")
        for (text, where, _raw), members in sorted(groups.items(), key=lambda item: -len(item[1]))[:12]:
            who = ", ".join(label(record["tid"]) for record in members[:4]) + (", ..." if len(members) > 4 else "")
            lines.append(f"    {len(members):3}x  {text}; at {where}; {who}")
            stack = [_name_of(symbols, location) for location in members[0].get("s") or () if location]
            if stack:
                lines.append("           stack: " + "  <-  ".join(stack[:6]))
    lines.extend(_wake_lines(records, first, last, start, middle))
    unread = {}
    for record in records:
        if record["k"] == "sock" and record["t"] <= middle:
            unread[record["fd"]] = record
    unread = {fd: record for fd, record in unread.items() if not record.get("gone") and record.get("rx", 0) > 0}
    if any(record["k"] == "sock" for record in records):
        lines.append("  sockets holding unread bytes in the middle of the lull: " + (
            "; ".join(f"fd {fd} {record['p']} {record['st'] or ''} to {record['to']}, {record['rx']} bytes since "
                      f"{record['t'] - start:.1f} s" for fd, record in sorted(unread.items())) or "none"))
    return lines


def _wake_lines(records, first, last, start, middle):
    """The kqueue loops' wake sources in the middle of a lull: signals nobody consumed, and the timers
    armed then with the time each fires; a timer firing within a second of the lull's end is marked."""
    if not any(record["k"] in ("efd", "tfd", "ep") for record in records):
        return []
    held = {}
    for record in records:
        if record["k"] == "rd" and record["t"] <= middle:
            held[record["fd"]] = record
    held = {fd: record for fd, record in held.items() if record["n"] > 0}
    pending, timers, sets = {}, {}, {}
    for record in records:
        if record["t"] > middle:
            continue
        if record["k"] == "efd":
            pending[record["fd"]] = record
        elif record["k"] == "tfd":
            timers[record["fd"]] = record
        elif record["k"] == "ep":
            sets[record["fd"]] = record["w"]
    lines = ["  pipes and sockets holding unread bytes in the middle of the lull: " + (
        "; ".join(f"fd {fd} {record['p']} {record['n']} bytes since {record['t'] - start:.1f} s"
                  for fd, record in sorted(held.items())) or "none")]
    waiting = {fd: record for fd, record in pending.items() if record["n"] > 0}
    lines.append("  eventfd signals nobody consumed in the middle of the lull: " + (
        "; ".join(f"fd {fd} count {record['n']} since {record['t'] - start:.1f} s (watched by epoll "
                  f"{[ep for ep, watched in sets.items() if fd in watched] or '?'})"
                  for fd, record in sorted(waiting.items())) or "none"))
    armed = []
    for fd, record in timers.items():
        if record["v"] > 0:
            armed.append((record["t"] - start + record["v"], fd, record))
    if armed:
        lines.append("  timers armed in the middle of the lull (fires at): " + "; ".join(
            f"fd {fd} {fires:.1f} s" + (f" (every {record['i']:.1f} s)" if record["i"] else "")
            + (" <- ends the lull" if abs(fires - (last - start)) <= 1.0 else "")
            + f" (epoll {[ep for ep, watched in sets.items() if fd in watched] or '?'})"
            for fires, fd, record in sorted(armed)))
    return lines


def report(path, log=None, *, before=2, after=40, everything=False, symbolize=True):
    """The report for a capture file; the launch log, when it can be found,
    supplies the markers."""
    records = load(path)
    if not records:
        return "The capture file is empty.\n"
    times = [record["t"] for record in records if "t" in record]
    start, end = min(times), max(times)
    if log is None:
        from . import core
        log = diagnostics._latest(core.LOGS, "launch-*.log")
    markers = log_markers(log, start, end) if log else []
    symbols = {}
    if symbolize:
        from . import core
        symbols = diagnostics._symbolize(_locations(records), diagnostics._symbolizer(),
                                         (core.DARLING_PREFIX, core.DARLING_SYSROOT))
    return render(records, markers, symbols, before=before, after=after, everything=everything)


# --------------------------------------------------------------------- CLI

def _wait_for_game(stop):
    from . import core
    while not stop():
        pids = core.roblox_pids(("RobloxPlayer",))
        if pids:
            return max(pids)
        time.sleep(1.0)
    return None


def cli(argv):
    import argparse
    parser = argparse.ArgumentParser(prog="quadrahq --watch-stalls", description=__doc__.split("\n")[0])
    parser.add_argument("--output", type=Path, help="directory for the capture and report (default: Quadra's logs)")
    parser.add_argument("--interval", type=float, default=INTERVAL, help="seconds between CPU samples")
    parser.add_argument("--no-stacks", action="store_true", help="record the CPU timeline only")
    parser.add_argument("--report", type=Path, metavar="CAPTURE", help="print the report of a capture file and exit")
    parser.add_argument("--log", type=Path, help="launch log for the markers (default: the newest)")
    parser.add_argument("--before", type=float, default=2.0, help="seconds shown before a marker")
    parser.add_argument("--after", type=float, default=40.0, help="seconds shown after a marker")
    parser.add_argument("--all", action="store_true", help="report the whole capture, not the join and leave windows")
    parser.add_argument("--no-symbols", action="store_true", help="skip symbol lookup")
    arguments = parser.parse_args(argv)
    options = dict(before=arguments.before, after=arguments.after, everything=arguments.all,
                   symbolize=not arguments.no_symbols)
    if arguments.report:
        print(report(arguments.report, arguments.log, **options), end="")
        return 0

    from . import core
    stopping = []

    def request_stop(*_unused):
        stopping.append(True)
    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)
    directory = arguments.output or core.LOGS
    directory.mkdir(parents=True, exist_ok=True)
    print("Waiting for the game (Ctrl-C to stop)...", file=sys.stderr, flush=True)
    pid = _wait_for_game(lambda: bool(stopping))
    if pid is None:
        return 0
    path = directory / f"stall-watch-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    print(f"Watching process {pid}; capture {path}", file=sys.stderr, flush=True)
    stacks = capture(pid, path, interval=arguments.interval, trace=not arguments.no_stacks,
                     stop=lambda: bool(stopping), servers=core._darlingservers())
    if not stacks and not arguments.no_stacks:
        print("Stacks were not readable: start the game with MACOBLOX_ALLOW_DEBUGGER=1 "
              "(Settings -> Environment -> allow freeze diagnostics).", file=sys.stderr)
    text = report(path, arguments.log, **options)
    path.with_suffix(".txt").write_text(text)
    print(text, end="")
    print(f"Report: {path.with_suffix('.txt')}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(cli(sys.argv[1:]))
