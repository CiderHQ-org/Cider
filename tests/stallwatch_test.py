import json
import os
import struct
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from macoblox import stallwatch

CODE = ("/lib/libwork.dylib", 0x1000, 0x2000)  # path, start, end


class FakeMemory:
    def __init__(self, words):
        self.words = words

    def read(self, address, size):
        if address in self.words and size == 8:
            return struct.pack("<Q", self.words[address])
        if address in self.words and size == 16:
            return struct.pack("<QQ", self.words[address], self.words.get(address + 8, 0))
        return b""


def regions():
    path, start, end = CODE
    with patch.object(stallwatch.diagnostics, "_mappings", return_value=[(start, end, 0, path)]):
        return stallwatch.Regions(1)


class RegionTests(unittest.TestCase):
    def test_a_code_address_is_a_library_and_a_file_offset(self):
        found = regions()
        self.assertEqual(found.locate(0x1234), ("/lib/libwork.dylib", 0x234))
        self.assertIsNone(found.locate(0x0fff))
        self.assertIsNone(found.locate(0x2000))

    def test_the_frame_chain_follows_saved_frame_pointers(self):
        memory = FakeMemory({
            0x7000: 0x7100, 0x7008: 0x1111,  # innermost frame: saved frame pointer, return address
            0x7100: 0x7200, 0x7108: 0x1222,
            0x7200: 0, 0x7208: 0x1333,
        })
        chain = stallwatch.frame_chain(memory, regions(), 0x1100, 0x7000, 0x6ff0)
        self.assertEqual(chain, [0x1100, 0x1111, 0x1222, 0x1333])

    def test_a_system_call_stub_is_followed_by_its_caller_from_the_stack_top(self):
        memory = FakeMemory({0x6ff0: 0x1444, 0x7000: 0x7100, 0x7008: 0x1555, 0x7100: 0, 0x7108: 0x1666})
        chain = stallwatch.frame_chain(memory, regions(), 0x1100, 0x7000, 0x6ff0)
        self.assertEqual(chain, [0x1100, 0x1444, 0x1555, 0x1666])

    def test_a_frame_chain_stops_at_a_pointer_that_does_not_climb_or_a_return_outside_code(self):
        loop = FakeMemory({0x7000: 0x7000, 0x7008: 0x1111})
        self.assertEqual(stallwatch.frame_chain(loop, regions(), 0x1100, 0x7000, 0x6ff0), [0x1100, 0x1111])
        data = FakeMemory({0x7000: 0x7100, 0x7008: 0x9999})
        self.assertEqual(stallwatch.frame_chain(data, regions(), 0x1100, 0x7000, 0x6ff0), [0x1100])


class MarkerTests(unittest.TestCase):
    def test_log_lines_become_markers_and_a_burst_is_one_marker(self):
        lines = [
            "2026-10-24T04:40:25.122Z,60.1,9d915d80,6 [FLog::SingleSurfaceApp] launchUGCGameInternal",
            "2026-10-24T04:40:35.352Z,70.3,9d915d80,6 [FLog::SingleSurfaceApp] returnToLuaApp: (stage:UGCGame).",
            "2026-10-24T04:40:35.353Z,70.3,9d915d80,6 [FLog::SingleSurfaceApp] leaveUGCGameInternal",
            "2026-10-24T04:39:25.840Z,0.8,9d915d80,6 [FLog::SingleSurfaceApp] returnToLuaApp: (stage:InitializedLuaApp).",
            "[Quadra Metal] no timestamp",
        ]
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "launch.log"
            log.write_text("\n".join(lines))
            found = stallwatch.log_markers(log, 1792816700, 1792816900)
        self.assertEqual([label for _moment, label, _text in found], ["join", "leave"])
        self.assertAlmostEqual(found[1][0] - found[0][0], 10.23, places=2)

    def test_markers_outside_the_capture_are_left_out(self):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "launch.log"
            log.write_text("2026-10-24T04:40:25.122Z,60.1,1,6 launchUGCGameInternal\n")
            self.assertEqual(stallwatch.log_markers(log, 0, 100), [])


def synthetic_capture():
    """A leave at t=100 after which thread 11 spins in one function for 12 s while thread 22 waits."""
    start = 90.0
    records = [{"k": "meta", "t": start, "pid": 7, "interval": 0.1, "stacks": True},
               {"k": "name", "t": start, "tid": 11, "name": "RenderJob"},
               {"k": "name", "t": start, "tid": 22, "name": "Network"},
               {"k": "wait", "t": start, "tid": 22, "state": "S", "wchan": "futex_wait_queue", "syscall": "202",
                "pc": ["/lib/libwork.dylib", 0x1100]}]
    for step in range(0, 400):
        moment = start + step * 0.1
        busy = {11: 95.0} if 100 <= moment < 112 else {11: 4.0}
        records.append({"k": "cpu", "t": moment, "d": busy})
        if 100 <= moment < 112 and step % 5 == 0:
            records.append({"k": "run", "t": moment, "tid": 11,
                            "f": [["/lib/libwork.dylib", 0x1200], ["/lib/libwork.dylib", 0x1300]]})
    records.append({"k": "wait", "t": 100.5, "tid": 22, "state": "S", "wchan": "unix_stream_read_generic",
                    "syscall": "47", "pc": ["/lib/libwork.dylib", 0x1100],
                    "s": [["/lib/libwork.dylib", 0x1400]]})
    records.append({"k": "end", "t": 130.0, "truncated": False})
    return records


class ReportTests(unittest.TestCase):
    def render(self):
        symbols = {("/lib/libwork.dylib", 0x1200): "tzset", ("/lib/libwork.dylib", 0x1300): "formatDate",
                   ("/lib/libwork.dylib", 0x1400): "waitForReply", ("/lib/libwork.dylib", 0x1100): "syscall_stub"}
        markers = [(100.0, "leave", "returnToLuaApp")]
        return stallwatch.render(synthetic_capture(), markers, symbols, before=2, after=20)

    def test_the_busy_second_names_the_thread_and_the_function(self):
        text = self.render()
        self.assertIn("RenderJob[11] 95% in libwork.dylib!tzset", text)
        self.assertIn("leave at 10.0 s", text)

    def test_stack_samples_are_ranked_for_the_busy_thread(self):
        text = self.render()
        self.assertIn("RenderJob[11]: 24 samples", text)
        self.assertIn("libwork.dylib!tzset  <-  libwork.dylib!formatDate", text)

    def test_a_thread_that_began_waiting_in_the_window_is_listed_with_where(self):
        text = self.render()
        self.assertIn("Network[22] from 10.5 s", text)
        self.assertIn("recvmsg", text)
        self.assertIn("unix_stream_read_generic", text)
        self.assertIn("waitForReply", text)

    def test_a_thread_waiting_since_before_the_window_is_not_blamed(self):
        records = [record for record in synthetic_capture()
                   if not (record["k"] == "wait" and record["t"] > 100)]
        text = stallwatch.render(records, [(100.0, "leave", "x")], {}, before=2, after=20)
        self.assertNotIn("started waiting", text)

    def test_a_thread_that_keeps_running_while_it_waits_in_one_place_is_not_blocked(self):
        records = synthetic_capture()
        for record in records:
            if record["k"] == "cpu" and 101 <= record["t"] <= 125:
                record["d"][22] = 60.0
        text = stallwatch.render(records, [(100.0, "leave", "x")], {}, before=2, after=20)
        self.assertNotIn("Network[22] from", text)


class WaitDecodeTests(unittest.TestCase):
    def fields(self, number, args, sp=0x7000, pc=0x1100):
        values = [number, *args, *([0] * (6 - len(args)))]
        return [str(values[0]), *[hex(value) for value in values[1:]], hex(sp), hex(pc)]

    def test_a_futex_wait_names_its_word_and_a_relative_timeout(self):
        memory = FakeMemory({0x9000: 7})
        memory.read = lambda address, size: (struct.pack("<I", 7) if address == 0x9000 and size == 4 else
                                              struct.pack("<qq", 16, 500_000_000) if address == 0xa000 else b"")
        # futex(0x9000, FUTEX_WAIT_PRIVATE = 128, 7, &timeout)
        detail = stallwatch.decode_wait(self.fields(202, [0x9000, 128, 7, 0xa000]), memory)
        self.assertEqual(detail["fx"], [0x9000, 7])
        self.assertEqual(detail["to"], 16500.0)
        self.assertNotIn("abs", detail)

    def test_an_untimed_futex_wait_has_no_timeout(self):
        memory = FakeMemory({})
        memory.read = lambda address, size: struct.pack("<I", 1) if size == 4 else b""
        detail = stallwatch.decode_wait(self.fields(202, [0x9000, 128, 1, 0]), memory)
        self.assertEqual(detail, {"fx": [0x9000, 1]})

    def test_a_bitset_wait_is_a_deadline_on_the_monotonic_clock(self):
        now_ms = time.clock_gettime(time.CLOCK_MONOTONIC) * 1000.0
        deadline = now_ms + 2500.0
        memory = FakeMemory({})
        memory.read = lambda address, size: (struct.pack("<I", 0) if size == 4 else
                                              struct.pack("<qq", int(deadline // 1000), int(deadline % 1000 * 1e6)))
        detail = stallwatch.decode_wait(self.fields(202, [0x9000, 137, 0, 0xa000]), memory)  # WAIT_BITSET_PRIVATE
        self.assertTrue(detail["abs"])
        self.assertAlmostEqual(detail["to"], 2500.0, delta=200.0)

    def test_poll_and_epoll_timeouts_are_milliseconds_and_minus_one_is_none(self):
        memory = FakeMemory({})
        self.assertEqual(stallwatch.decode_wait(self.fields(7, [0, 1, 250]), memory)["to"], 250.0)
        self.assertEqual(stallwatch.decode_wait(self.fields(232, [3, 0, 8, 1500]), memory)["to"], 1500.0)
        self.assertEqual(stallwatch.decode_wait(self.fields(7, [0, 1, 0xffffffff]), memory), {})
        self.assertEqual(stallwatch.decode_wait(self.fields(47, [3, 0, 0]), memory), {})

    def test_a_thread_that_is_running_has_no_wait_to_decode(self):
        self.assertEqual(stallwatch.decode_wait([], FakeMemory({})), {})
        self.assertEqual(stallwatch.decode_wait(["-1", "0x7000", "0x1100"], FakeMemory({})), {})


def lull_capture(servers=True):
    """CPU at 100% until t=100, almost none until t=116, busy again; a futex waiter with a 16 s timeout."""
    start = 90.0
    records = [{"k": "meta", "t": start, "pid": 7, "interval": 0.1, "stacks": True, "servers": [99] if servers else []},
               {"k": "name", "t": start, "tid": 11, "name": "Main"},
               {"k": "name", "t": start, "tid": 22, "name": "Worker"}]
    for step in range(0, 400):
        moment = start + step * 0.1
        if moment < 100 or moment >= 116:
            records.append({"k": "cpu", "t": moment, "d": {11: 90.0, 22: 40.0}})
        elif step % 10 == 0:
            records.append({"k": "cpu", "t": moment, "d": {11: 3.0}})
        if servers and 100 <= moment < 116 and step % 10 == 0:
            records.append({"k": "srv", "t": moment, "d": {501: 2.0}})
        if 101 <= moment < 115 and step % 5 == 0:
            records.append({"k": "run", "t": moment, "tid": 11, "w": 1,
                            "f": [["/lib/libwork.dylib", 0x1100], ["/lib/libwork.dylib", 0x1200]]})
    records.append({"k": "wait", "t": 100.6, "tid": 22, "state": "S", "wchan": "futex_wait_queue", "syscall": "202",
                    "x": {"fx": [0x9000, 7], "to": 15400.0, "raw": 15400.0}, "pc": ["/lib/libwork.dylib", 0x1300],
                    "s": [["/lib/libwork.dylib", 0x1400]]})
    records.append({"k": "end", "t": 130.0, "truncated": False})
    return records


class LullTests(unittest.TestCase):
    def test_a_stretch_of_almost_no_cpu_is_found(self):
        records = lull_capture()
        lulls = stallwatch.find_lulls(records, 90.0, 130.0)
        self.assertEqual(len(lulls), 1)
        self.assertAlmostEqual(lulls[0][0], 100.0, delta=0.6)
        self.assertAlmostEqual(lulls[0][1], 116.0, delta=0.6)

    def test_short_quiet_spells_are_not_lulls(self):
        records = [record for record in lull_capture()
                   if not (record["k"] == "cpu" and 100 <= record["t"] < 116 and record["t"] > 102)]
        records += [{"k": "cpu", "t": 102.5 + step * 0.1, "d": {11: 90.0}} for step in range(0, 135)]
        self.assertEqual(stallwatch.find_lulls(records, 90.0, 130.0), [])

    def test_the_lull_report_says_who_woke_what_waited_and_when_it_times_out(self):
        symbols = {("/lib/libwork.dylib", 0x1100): "mach_msg_recv", ("/lib/libwork.dylib", 0x1200): "runloop_wait",
                   ("/lib/libwork.dylib", 0x1300): "futex_stub", ("/lib/libwork.dylib", 0x1400): "pool_idle"}
        text = stallwatch.render(lull_capture(), [(100.0, "leave", "x")], symbols, before=2, after=5)
        self.assertIn("lull from 10.0 s to 26.0 s", text)
        self.assertIn("after leave at 10.0 s", text)
        self.assertIn("first busy again: Main[11] at 26.00 s", text)
        self.assertIn("the main thread, sampled while it waited", text)
        self.assertIn("libwork.dylib!mach_msg_recv  <-  libwork.dylib!runloop_wait", text)
        self.assertIn("futex 0x9000 = 0x7, times out in 15.4 s (about 26.0 s)", text)
        self.assertIn("darlingserver CPU in the lull: 32 ms", text)

    def test_a_capture_without_server_records_does_not_claim_a_server_figure(self):
        text = stallwatch.render(lull_capture(servers=False), [], {}, everything=True)
        self.assertIn("== lull", text)
        self.assertNotIn("darlingserver CPU", text)

    def test_waiting_samples_stay_out_of_the_busy_thread_listing(self):
        symbols = {("/lib/libwork.dylib", 0x1100): "mach_msg_recv"}
        text = stallwatch.render(lull_capture(), [(100.0, "leave", "x")], symbols, before=2, after=20)
        self.assertIn("mach_msg_recv", text)
        self.assertNotIn("where the busy threads were", text)  # the only samples are the main thread's waits
        self.assertGreater(text.index("mach_msg_recv"), text.index("== lull"))


class SocketTests(unittest.TestCase):
    def test_a_connection_with_unread_bytes_shows_its_receive_queue(self):
        import socket
        server = socket.socket()
        self.addCleanup(server.close)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        client = socket.create_connection(server.getsockname())
        self.addCleanup(client.close)
        accepted, _address = server.accept()
        self.addCleanup(accepted.close)
        client.sendall(b"x" * 1234)
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            table = stallwatch.socket_table(os.getpid())
            if table.get(accepted.fileno(), {}).get("rx"):
                break
            time.sleep(0.02)
        info = table[accepted.fileno()]
        self.assertEqual((info["p"], info["st"], info["rx"]), ("tcp", "ESTABLISHED", 1234))
        self.assertTrue(info["to"].startswith("127.0.0.1:"))
        self.assertEqual(table[client.fileno()]["rx"], 0)

    def test_the_report_names_a_socket_with_unread_bytes_during_a_lull(self):
        records = lull_capture()
        records.insert(-1, {"k": "sock", "t": 99.0, "fd": 12, "p": "tcp", "st": "ESTABLISHED", "rx": 0, "tx": 0,
                            "to": "203.0.113.5:443"})
        records.insert(-1, {"k": "sock", "t": 100.2, "fd": 12, "p": "tcp", "st": "ESTABLISHED", "rx": 4096, "tx": 0,
                            "to": "203.0.113.5:443"})
        records.insert(-1, {"k": "sock", "t": 100.2, "fd": 13, "p": "udp", "st": "", "rx": 0, "tx": 0,
                            "to": "0.0.0.0:0"})
        text = stallwatch.render(records, [], {}, everything=True)
        self.assertIn("sockets holding unread bytes in the middle of the lull: fd 12 tcp ESTABLISHED to "
                      "203.0.113.5:443, 4096 bytes since 10.2 s", text)

    def test_a_capture_without_socket_records_does_not_claim_none(self):
        text = stallwatch.render(lull_capture(), [], {}, everything=True)
        self.assertNotIn("sockets holding unread bytes", text)


class WakeTests(unittest.TestCase):
    def test_eventfd_timerfd_and_epoll_sets_are_read_from_proc(self):
        import ctypes
        import select
        libc = ctypes.CDLL(None, use_errno=True)
        timer = libc.timerfd_create(1, 0)  # CLOCK_MONOTONIC
        self.assertGreaterEqual(timer, 0)
        self.addCleanup(os.close, timer)
        spec = (ctypes.c_long * 4)(0, 0, 12, 0)  # it_interval 0, it_value 12 s
        self.assertEqual(libc.timerfd_settime(timer, 0, spec, None), 0)
        event = os.eventfd(0)
        self.addCleanup(os.close, event)
        os.eventfd_write(event, 3)
        poller = select.epoll()
        self.addCleanup(poller.close)
        poller.register(timer, select.EPOLLIN)
        poller.register(event, select.EPOLLIN)
        table = stallwatch.wake_table(os.getpid())
        self.assertEqual(table["efd"][event], 3)
        remaining, interval = table["tfd"][timer]
        self.assertTrue(10.0 < remaining <= 12.0 and interval == 0.0)
        self.assertEqual(table["ep"][poller.fileno()], sorted([timer, event]))

    def test_the_lull_report_names_a_timer_that_fires_when_the_freeze_ends(self):
        records = lull_capture()
        records[-1:-1] = [
            {"k": "ep", "t": 90.5, "fd": 3, "w": [9, 11]},
            {"k": "tfd", "t": 100.4, "fd": 11, "v": 15.5, "i": 0.0},
            {"k": "tfd", "t": 100.4, "fd": 18, "v": 900.0, "i": 0.0},
            {"k": "efd", "t": 101.0, "fd": 9, "n": 2},
        ]
        text = stallwatch.render(records, [], {}, everything=True)
        self.assertIn("eventfd signals nobody consumed in the middle of the lull: fd 9 count 2 since 11.0 s "
                      "(watched by epoll [3])", text)
        self.assertIn("fd 11 25.9 s <- ends the lull (epoll [3])", text)
        self.assertIn("fd 18 910.4 s (epoll ?)", text)

    def test_a_capture_without_wake_records_says_nothing_about_them(self):
        text = stallwatch.render(lull_capture(), [], {}, everything=True)
        self.assertNotIn("eventfd signals", text)
        self.assertNotIn("timers armed", text)


class UnreadTests(unittest.TestCase):
    def test_bytes_waiting_in_a_pipe_and_a_socketpair_are_counted_without_consuming_them(self):
        import socket
        reader, writer = os.pipe()
        self.addCleanup(os.close, reader)
        self.addCleanup(os.close, writer)
        left, right = socket.socketpair()
        self.addCleanup(left.close)
        self.addCleanup(right.close)
        os.write(writer, b"abc")
        right.send(b"hello")
        found = stallwatch.unread_table(os.getpid())
        self.assertEqual(found[reader], ("pipe", 3))
        self.assertEqual(found[left.fileno()], ("socket", 5))
        self.assertNotIn(right.fileno(), found)  # nothing waits on that end
        self.assertEqual(os.read(reader, 8), b"abc")  # still there to be read: nothing was consumed
        self.assertEqual(left.recv(8), b"hello")

    def test_the_lull_report_lists_a_pipe_nobody_read(self):
        records = lull_capture()
        records[-1:-1] = [{"k": "ep", "t": 90.5, "fd": 3, "w": [9]},
                          {"k": "rd", "t": 101.0, "fd": 55, "p": "pipe", "n": 1}]
        text = stallwatch.render(records, [], {}, everything=True)
        self.assertIn("pipes and sockets holding unread bytes in the middle of the lull: fd 55 pipe 1 bytes since 11.0 s",
                      text)


CHILD = textwrap.dedent("""
    import ctypes, threading, time
    libc = ctypes.CDLL(None)
    libc.prctl(0x59616d61, ctypes.c_ulong(-1))  # PR_SET_PTRACER, PR_SET_PTRACER_ANY
    # A timerfd like the game's: a one-shot timer, so its interval is zero.
    timer = libc.timerfd_create(1, 0)
    libc.timerfd_settime(timer, 0, (ctypes.c_long * 4)(0, 0, 600, 0), None)

    def spin_here():
        while True:
            sum(range(2000))

    threading.Thread(target=spin_here, daemon=True, name="spinner").start()
    threading.Thread(target=lambda: time.sleep(600), daemon=True, name="sleeper").start()
    print("ready", flush=True)
    time.sleep(600)
""")


class CaptureTests(unittest.TestCase):
    def start_child(self):
        child = subprocess.Popen([sys.executable, "-I", "-c", CHILD], stdout=subprocess.PIPE, text=True)
        self.addCleanup(child.stdout.close)
        self.addCleanup(child.wait)
        self.addCleanup(child.kill)
        self.assertEqual(child.stdout.readline().strip(), "ready")
        return child

    def test_a_live_process_yields_a_cpu_timeline_stacks_and_waits(self):
        child = self.start_child()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.jsonl"
            deadline = time.monotonic() + 3.0
            stacks = stallwatch.capture(child.pid, path, interval=0.05, stop=lambda: time.monotonic() > deadline)
            records = stallwatch.load(path)
            kinds = {record["k"] for record in records}
            self.assertLessEqual({"meta", "cpu", "name", "wait", "end"}, kinds)
            busiest = max((record for record in records if record["k"] == "cpu"),
                          key=lambda record: max(record["d"].values()))
            self.assertGreater(max(busiest["d"].values()), 20.0)
            if not stacks:
                self.skipTest("ptrace is not permitted here")
            runs = [record for record in records if record["k"] == "run"]
            self.assertTrue(runs, "no stack was sampled for the spinning thread")
            self.assertTrue(all(len(record["f"]) >= 1 for record in runs))
            text = stallwatch.report(path, Path(directory) / "none.log", symbolize=False, everything=True)
            self.assertIn("samples", text)
            self.assertIn("process", text)
        self.assertIsNone(child.poll(), "the watched process must keep running")

    def test_a_timerfd_in_the_watched_process_does_not_change_the_sampling_rate(self):
        # The timerfd's own interval once overwrote the loop's: it became zero and the loop spun.
        child = self.start_child()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.jsonl"
            deadline = time.monotonic() + 2.0
            stallwatch.capture(child.pid, path, interval=0.1, stop=lambda: time.monotonic() > deadline)
            records = stallwatch.load(path)
            self.assertTrue(any(record["k"] == "tfd" for record in records), "the timerfd was not seen")
            runs = sum(1 for record in records if record["k"] == "run")
            cpu_records = sum(1 for record in records if record["k"] == "cpu")
            self.assertLess(runs, 120)  # at most four stacks per tenth of a second
            self.assertLess(cpu_records, 40)

    def test_no_interval_can_make_the_watcher_stop_the_game_more_than_sixty_times_a_second(self):
        child = self.start_child()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.jsonl"
            deadline = time.monotonic() + 2.0
            stallwatch.capture(child.pid, path, interval=0.0, stop=lambda: time.monotonic() > deadline)
            runs = sum(1 for record in stallwatch.load(path) if record["k"] == "run")
            self.assertLess(runs, 2 * stallwatch.MAX_STOPS_PER_SECOND + 30)

    def test_without_ptrace_permission_the_cpu_timeline_is_still_recorded(self):
        child = self.start_child()
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(stallwatch, "can_trace", return_value=False):
            path = Path(directory) / "capture.jsonl"
            deadline = time.monotonic() + 1.0
            self.assertFalse(stallwatch.capture(child.pid, path, interval=0.05,
                                                stop=lambda: time.monotonic() > deadline))
            records = stallwatch.load(path)
            self.assertFalse(any(record["k"] == "run" for record in records))
            self.assertTrue(any(record["k"] == "cpu" for record in records))
            self.assertFalse(next(record for record in records if record["k"] == "meta")["stacks"])


if __name__ == "__main__":
    unittest.main()
