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


CHILD = textwrap.dedent("""
    import ctypes, threading, time
    libc = ctypes.CDLL(None)
    libc.prctl(0x59616d61, ctypes.c_ulong(-1))  # PR_SET_PTRACER, PR_SET_PTRACER_ANY

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
