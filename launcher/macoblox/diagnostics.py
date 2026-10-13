"""Freeze and crash diagnostics: one archive with what a report needs.

Collected without stopping the game: every Roblox thread's state and kernel
wait channel, sampled twice a few seconds apart (a frozen thread keeps the
same wait), the recent launcher, Roblox and darlingserver logs, the runtime
selection and the Cider/Darling environment variables of the game.

Reading where a thread is in user space (its system call, instruction pointer
and stack) needs ptrace permission. Under Yama (kernel.yama.ptrace_scope=1,
the usual default) only an ancestor may read that, and Roblox is a child of
darlingserver, not of Cider, so the game must allow it: the shim does when
MACOBLOX_ALLOW_DEBUGGER=1 (Settings, or the environment). Then each thread's
instruction pointer and the likely return addresses on its stack are given as
library + offset; `--gdb` adds gdb's backtraces (gdb briefly stops the game).

Credentials stay out: environment variables are filtered to Cider, Darling
and graphics settings, and join tickets and cookies in logs are redacted.
"""
import io
import json
import os
import platform
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import tarfile
import time
from pathlib import Path

from . import __version__

SAMPLE_INTERVAL = 3.0
STACK_SCAN_BYTES = 64 * 1024
STACK_CANDIDATES = 24
LOG_TAIL = 2 * 1024 * 1024
ENV_PREFIXES = ("MACOBLOX_", "CIDER_", "DSERVER_", "MESA_", "GALLIUM_", "ZINK_", "__GLX_", "__GL_",
                "LIBGL_", "VK_", "MANGOHUD", "DPREFIX", "DISPLAY", "WAYLAND_DISPLAY", "XDG_SESSION_TYPE",
                "EGL_PLATFORM", "LIBDISPATCH_")
SECRET_VARIABLES = ("MACOBLOX_PENDING_URI",)
REDACTIONS = (
    (re.compile(r"(ticket=)[^&\"'\s]+", re.I), r"\1<redacted>"),
    (re.compile(r"(\"ticket\"\s*:\s*\")[^\"]*", re.I), r"\1<redacted>"),
    (re.compile(r"(gameinfo:)[^+\s\"']+", re.I), r"\1<redacted>"),
    (re.compile(r"(\.?ROBLOSECURITY\s*[=:]\s*)[^;\s\"']+", re.I), r"\1<redacted>"),
    (re.compile(r"_\|WARNING:-DO-NOT-SHARE-THIS[^\s\"';]*"), "<redacted>"),
)


def redact(text):
    for pattern, replacement in REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


def _read(path, limit=None):
    try:
        with open(path, "rb") as file:
            if limit is not None:
                size = os.fstat(file.fileno()).st_size
                if size > limit:
                    file.seek(size - limit)
            return file.read()
    except OSError as error:
        return f"<unreadable: {error.strerror}>".encode()


def _text(path, limit=None):
    return _read(path, limit).decode(errors="replace")


# ------------------------------------------------------------------ threads

def _mappings(pid):
    """Executable file mappings: (start, end, file offset, path)."""
    regions = []
    try:
        for line in Path(f"/proc/{pid}/maps").read_text().splitlines():
            fields = line.split(None, 5)
            if len(fields) < 6 or "x" not in fields[1]:
                continue
            start, end = (int(value, 16) for value in fields[0].split("-"))
            regions.append((start, end, int(fields[2], 16), fields[5]))
    except OSError:
        pass
    return regions


def _locate(address, regions):
    for start, end, offset, path in regions:
        if start <= address < end:
            return f"{Path(path).name}+0x{address - start + offset:x}", path, address - start + offset
    return None, None, None


def _symbolizer():
    for name in ("llvm-symbolizer", "addr2line"):
        found = shutil.which(name)
        if found:
            return name, found
    return None, None


def _macho_layout(path):
    """(slice offset, [(vmaddr, vmsize, fileoff, filesize)]) of the x86_64
    image in a (fat) Mach-O file, or None."""
    try:
        with open(path, "rb") as file:
            head = file.read(4096)
            base = 0
            if head[:4] == b"\xca\xfe\xba\xbe":
                for index in range(struct.unpack_from(">I", head, 4)[0]):
                    cputype, _sub, offset, _size, _align = struct.unpack_from(">5I", head, 8 + index * 20)
                    if cputype == 0x01000007:
                        base = offset
                        break
                else:
                    return None
                file.seek(base)
                head = file.read(4096)
            if head[:4] != b"\xcf\xfa\xed\xfe":
                return None
            commands_size = struct.unpack_from("<I", head, 20)[0]
            if 32 + commands_size > len(head):
                file.seek(base)
                head = file.read(32 + commands_size)
    except (OSError, struct.error):
        return None
    segments, position = [], 32
    for _command in range(struct.unpack_from("<I", head, 16)[0]):
        command, size = struct.unpack_from("<II", head, position)
        if command == 0x19:  # LC_SEGMENT_64
            segments.append(struct.unpack_from("<4Q", head, position + 24))
        position += size
    return base, segments


def _macho_names(path, offsets, nm):
    """Nearest preceding symbol for file offsets in a Mach-O library."""
    layout = _macho_layout(path)
    if not layout:
        return {}
    base, segments = layout
    try:
        output = subprocess.run([nm, "--defined-only", "-n", "--arch=x86_64", path],
                                capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    symbols = []
    for line in output.splitlines():
        fields = line.split(None, 2)
        if len(fields) >= 3 and fields[1] in "TtSs":
            try:
                symbols.append((int(fields[0], 16), fields[2]))
            except ValueError:
                pass
    import bisect
    keys = [address for address, _name in symbols]
    names = {}
    for offset in offsets:
        relative = offset - base
        for vmaddr, vmsize, fileoff, filesize in segments:
            if fileoff <= relative < fileoff + filesize:
                address = vmaddr + relative - fileoff
                index = bisect.bisect_right(keys, address) - 1
                if index >= 0:
                    names[offset] = f"{symbols[index][1]}+0x{address - keys[index]:x}"
                break
    return names


def _host_path(path, roots):
    """The host file behind a path in the game's maps. Darling's libraries
    appear by their path inside its container, whose root is the prefix over
    the runtime's root; the host's own files are under /Volumes/SystemRoot."""
    candidates = [path.removeprefix("/Volumes/SystemRoot")] if path.startswith("/Volumes/SystemRoot/") else []
    relative = Path(path.lstrip("/"))
    # Overlay-backed mappings can name the host prefix even for a file
    # supplied by the runtime's lower layer, absent from that prefix on the
    # host. Translate it back to its guest path before searching both layers.
    for root in roots:
        try:
            relative = Path(path).relative_to(root)
            break
        except ValueError:
            pass
    candidates += [str(Path(root) / relative) for root in roots] + [path]
    return next((candidate for candidate in candidates if os.path.isfile(candidate)), None)


def _symbolize(wanted, tool, roots=()):
    """{(path, offset): name}, one lookup per library (best effort; Darling's
    Mach-O libraries usually keep their symbols)."""
    names = {}
    by_path = {}
    for path, offset in wanted:
        if path.startswith("/"):
            by_path.setdefault(path, []).append(offset)
    nm = shutil.which("llvm-nm")
    for mapped, offsets in by_path.items():
        path = _host_path(mapped, roots)
        if not path:
            continue
        offsets = sorted(set(offsets))
        if _macho_layout(path):
            if nm:
                names.update({(mapped, offset): name for offset, name in _macho_names(path, offsets, nm).items()})
            continue
        if not tool[1]:
            continue
        if tool[0] == "llvm-symbolizer":
            arguments = [tool[1], "--functions=short", "--no-inlines", f"--obj={path}", *map(hex, offsets)]
        else:
            arguments = [tool[1], "-f", "-e", path, *map(hex, offsets)]
        try:
            output = subprocess.run(arguments, capture_output=True, text=True, timeout=20).stdout
        except (OSError, subprocess.SubprocessError):
            continue
        if tool[0] == "llvm-symbolizer":
            functions = [block.split("\n")[0] for block in output.strip("\n").split("\n\n")]
        else:
            functions = output.split("\n")[0::2]
        for offset, function in zip(offsets, functions):
            if function and function != "??":
                names[(mapped, offset)] = function.strip()
    return names


def _thread_sample(pid, tid):
    base = f"/proc/{pid}/task/{tid}"
    sample = {"tid": tid, "name": _text(f"{base}/comm").strip(), "wchan": _text(f"{base}/wchan").strip()}
    stat = _text(f"{base}/stat")
    after = stat.rsplit(")", 1)[-1].split()
    if len(after) > 12:
        sample["state"] = after[0]
        sample["cpu_ticks"] = int(after[11]) + int(after[12])
    try:
        sample["syscall"] = Path(f"{base}/syscall").read_text().strip()
    except OSError as error:
        sample["syscall"] = f"<{error.strerror}>"
    return sample


def _stack_candidates(pid, syscall, regions):
    """Words on the stack that point into executable mappings: likely return
    addresses, innermost first. Read only, the thread keeps running."""
    fields = syscall.split()
    if len(fields) < 3 or not fields[-2].startswith("0x"):
        return []
    stack_pointer = int(fields[-2], 16)
    data = b""
    try:
        with open(f"/proc/{pid}/mem", "rb", buffering=0) as memory:
            # Page by page: a read running past the top of the stack fails whole.
            page = stack_pointer
            while len(data) < STACK_SCAN_BYTES:
                memory.seek(page)
                chunk = memory.read(4096 - page % 4096)
                if not chunk:
                    break
                data += chunk
                page += len(chunk)
    except (OSError, ValueError, OverflowError):
        pass
    found = []
    for index in range(0, len(data) - 7, 8):
        value = struct.unpack_from("<Q", data, index)[0]
        if any(start <= value < end for start, end, _offset, _path in regions):
            found.append(value)
            if len(found) >= STACK_CANDIDATES:
                break
    return found


def _describe_threads(pid, first, second, regions, symbolize, roots=()):
    threads = []
    for tid in sorted(set(first) | set(second)):
        a, b = first.get(tid), second.get(tid)
        current = b or a
        syscall = current.get("syscall", "")
        fields = syscall.split()
        pc = int(fields[-1], 16) if len(fields) >= 3 and fields[-1].startswith("0x") else None
        stack = _stack_candidates(pid, syscall, regions) if pc is not None else []
        threads.append((tid, a, b, current, syscall, pc, stack))
    wanted = set()
    for *_unused, pc, stack in threads:
        for address in ([pc] if pc is not None else []) + stack:
            _label, path, offset = _locate(address, regions)
            if path:
                wanted.add((path, offset))
    names = _symbolize(wanted, _symbolizer(), roots) if symbolize else {}

    def where(address):
        label, path, offset = _locate(address, regions)
        if not label:
            return f"0x{address:x}"
        symbol = names.get((path, offset))
        return f"{label} ({symbol})" if symbol else label

    lines = []
    for tid, a, b, current, syscall, pc, stack in threads:
        busy = a and b and "cpu_ticks" in a and "cpu_ticks" in b and b["cpu_ticks"] > a["cpu_ticks"]
        unchanged = a and b and a.get("syscall") == b.get("syscall") and a.get("wchan") == b.get("wchan")
        verdict = "running" if busy else "unchanged wait" if unchanged else "changed"
        lines.append(f"thread {tid} [{current.get('name', '?')}] state={current.get('state', '?')} "
                     f"wchan={current.get('wchan') or '-'} ({verdict})")
        lines.append(f"  syscall: {syscall}")
        if pc is not None:
            lines.append(f"  pc: {where(pc)}")
            for address in stack:
                lines.append(f"    stack: {where(address)}")
    return "\n".join(lines) + "\n"


def _threads(pid):
    try:
        return [int(entry) for entry in os.listdir(f"/proc/{pid}/task")]
    except OSError:
        return []


def _sample_process(pid):
    return {tid: _thread_sample(pid, tid) for tid in _threads(pid)}


def _game_environment(pid):
    try:
        entries = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
    except OSError as error:
        return f"<unreadable: {error.strerror}>\n"
    kept = []
    for entry in entries:
        name, separator, value = entry.decode(errors="replace").partition("=")
        if not separator or not name.startswith(ENV_PREFIXES):
            continue
        kept.append(f"{name}=<redacted>" if name in SECRET_VARIABLES else f"{name}={value}")
    return "\n".join(sorted(kept)) + "\n"


def _annotate_addresses(text, regions, roots, symbolize):
    """gdb cannot read Darling's Mach-O images: name its addresses."""
    addresses = {int(token, 16) for token in re.findall(r"\b0x[0-9a-f]{6,16}\b", text)}
    located = {address: _locate(address, regions) for address in addresses}
    located = {address: value for address, value in located.items() if value[0]}
    names = (_symbolize({(path, offset) for _label, path, offset in located.values()}, _symbolizer(), roots)
             if symbolize else {})

    def label(match):
        value = located.get(int(match.group(0), 16))
        if not value:
            return match.group(0)
        name = names.get((value[1], value[2]))
        return f"{match.group(0)} <{value[0]}{' ' + name if name else ''}>"
    return re.sub(r"\b0x[0-9a-f]{6,16}\b", label, text)


def _gdb_backtraces(pid):
    gdb = shutil.which("gdb")
    if not gdb:
        return "gdb is not installed\n"
    try:
        # gdb cannot unwind Darling's Mach-O code by itself: the registers and
        # the top of each stack let the return addresses be read anyway.
        result = subprocess.run([gdb, "-p", str(pid), "-batch", "-nx", "-ex", "set pagination off",
                                 "-ex", "thread apply all bt 30",
                                 "-ex", "thread apply all info registers rip rsp rbp",
                                 "-ex", "thread apply all x/64gx $sp"],
                                capture_output=True, text=True, timeout=90)
        return result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return "gdb did not finish within 90 s\n"
    except OSError as error:
        return f"gdb failed: {error}\n"


def _ptrace_note(pid):
    scope = _text("/proc/sys/kernel/yama/ptrace_scope").strip()
    try:
        Path(f"/proc/{pid}/syscall").read_text()
        permitted = True
    except OSError:
        permitted = False
    note = f"kernel.yama.ptrace_scope={scope}; user-space locations {'available' if permitted else 'unavailable'}"
    if not permitted:
        note += ("\nStart the game with MACOBLOX_ALLOW_DEBUGGER=1 (Settings → allow freeze diagnostics) "
                 "to include instruction pointers and stacks.")
    return note + "\n"


# --------------------------------------------------------------------- main

def _latest(directory, pattern, exclude=None):
    try:
        files = [path for path in Path(directory).glob(pattern)
                 if path.is_file() and not (exclude and exclude in path.name)]
    except OSError:
        return None
    return max(files, key=lambda path: path.stat().st_mtime, default=None)


def collect(output_dir=None, *, gdb=False, symbolize=True, interval=SAMPLE_INTERVAL):
    """Write the archive and return its path; RuntimeError when that fails."""
    from . import core
    stamp = time.strftime("%Y%m%d-%H%M%S")
    output_dir = Path(output_dir) if output_dir else core.CACHE_DIR / "diagnostics"
    files = {}
    summary = [f"Cider {__version__}", f"Collected {time.strftime('%Y-%m-%d %H:%M:%S %z')}",
               f"Kernel {platform.release()} ({platform.machine()}); CPUs {os.cpu_count()}",
               f"Darling {core.DARLING_EXECUTABLE}; sysroot {core.DARLING_SYSROOT}; prefix {core.DARLING_PREFIX}"]
    metadata = core.DARLING_RUNTIME.get("metadata") or {}
    if metadata:
        summary.append(f"CiderDarling revision {metadata.get('source_revision', '?')}")
        files["runtime-metadata.json"] = json.dumps(metadata, indent=2) + "\n"
    # Inventory is quick and does not execute graphics or read auth data.
    # Full GPU scenarios remain an explicit hardware-report action.
    from . import hardware_report
    try:
        with tempfile.TemporaryDirectory(prefix='cider-diagnostics-hardware-') as directory:
            report = hardware_report.collect(directory)
            files['hardware.json'] = report.read_bytes()
    except (OSError, ValueError):
        pass

    pids = core.roblox_pids()
    summary.append(f"Roblox processes: {', '.join(map(str, pids)) or 'none running'}")
    first = {pid: _sample_process(pid) for pid in pids}
    if pids:
        time.sleep(interval)
    roots = (core.DARLING_PREFIX, core.DARLING_SYSROOT)
    for pid in pids:
        second = _sample_process(pid)
        regions = _mappings(pid)
        # Everything read from the process first: symbol lookups take a while
        # and a frozen game is often closed meanwhile.
        files[f"process-{pid}/maps.txt"] = _text(f"/proc/{pid}/maps")
        files[f"process-{pid}/environment.txt"] = _game_environment(pid)
        files[f"process-{pid}/status.txt"] = _text(f"/proc/{pid}/status")
        backtraces = _gdb_backtraces(pid) if gdb else None
        files[f"process-{pid}/threads.txt"] = (_ptrace_note(pid) + "\n" +
                                               _describe_threads(pid, first[pid], second, regions, symbolize, roots))
        if backtraces is not None:
            files[f"process-{pid}/gdb.txt"] = _annotate_addresses(backtraces, regions, roots, symbolize)

    sources = {
        "runtime.json": core.CONFIG_DIR / "runtime.json",
        "settings.json": core.SETTINGS_FILE,
        "last-error.txt": core.CACHE_DIR / "last-error.txt",
    }
    launch = _latest(core.LOGS, "launch-*.log")
    if launch:
        sources[f"logs/{launch.name}"] = launch
    roblox_logs = core.DARLING_HOME / "Library" / "Logs" / "Roblox"
    player = _latest(roblox_logs, "*_Player_*_last.log", exclude="CrashHandler")
    if player:
        sources[f"logs/{player.name}"] = player
    crash = _latest(roblox_logs, "*CrashHandler*_last.log")
    if crash:
        sources[f"logs/{crash.name}"] = crash
    sources["logs/dserver.log"] = core.DARLING_PREFIX / "private" / "var" / "log" / "dserver.log"
    # Written by the launcher next to its logs: CiderDarling's runtime trace
    # (Settings -> CiderDarling) and darlingserver's own output.
    trace = _latest(core.LOGS, "ciderdarling-trace-*.jsonl")
    if trace:
        sources[f"logs/{trace.name}"] = trace
    for server in sorted(Path(core.LOGS).glob("darlingserver-*.out")):
        sources[f"logs/{server.name}"] = server
    for name, path in sources.items():
        if Path(path).is_file():
            files[name] = redact(_text(path, LOG_TAIL))
    files["summary.txt"] = "\n".join(summary) + "\n"

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        archive = output_dir / f"cider-diagnostics-{stamp}.tar.gz"
        descriptor = os.open(archive, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as raw, tarfile.open(fileobj=raw, mode="w:gz") as bundle:
            for name, content in files.items():
                data = content.encode() if isinstance(content, str) else content
                info = tarfile.TarInfo(f"cider-diagnostics-{stamp}/{name}")
                info.size, info.mtime, info.mode = len(data), int(time.time()), 0o600
                bundle.addfile(info, io.BytesIO(data))
    except OSError as error:
        raise RuntimeError(f"Could not write the diagnostics archive: {error}") from error
    return archive


def collect_cli(argv):
    import argparse
    parser = argparse.ArgumentParser(prog="ciderhq --collect-diagnostics", description=__doc__.split("\n")[0])
    parser.add_argument("--output", type=Path, help="directory for the archive (default: Cider's cache)")
    parser.add_argument("--gdb", action="store_true", help="also attach gdb for backtraces (briefly stops the game)")
    parser.add_argument("--no-symbols", action="store_true", help="skip symbol lookup")
    parser.add_argument("--interval", type=float, default=SAMPLE_INTERVAL, help="seconds between the two samples")
    arguments = parser.parse_args(argv)
    try:
        archive = collect(arguments.output, gdb=arguments.gdb, symbolize=not arguments.no_symbols,
                          interval=arguments.interval)
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1
    print(archive)
    return 0


if __name__ == "__main__":
    raise SystemExit(collect_cli(sys.argv[1:]))
