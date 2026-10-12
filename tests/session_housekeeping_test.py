"""Launcher housekeeping around a game session; nothing is started."""
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from macoblox import core
from session_fixture import bare_session


def dead_pid():
    process = subprocess.Popen(["true"])
    process.wait()
    return process.pid


class SessionHousekeepingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)

    def patch(self, name, value):
        context = patch.object(core, name, value)
        context.start()
        self.addCleanup(context.stop)

    def test_sweep_removes_only_dead_launchers_fifos(self):
        dead, alive = dead_pid(), os.getppid()
        removed = [self.base / f"audio-{dead}.fifo", self.base / f"audio-in-{dead}.fifo"]
        kept = [self.base / f"audio-{os.getpid()}.fifo", self.base / f"audio-{alive}.fifo",
                self.base / "audio-launcher.fifo"]
        for path in removed + kept:
            os.mkfifo(path, 0o600)
        regular = self.base / f"audio-in-{dead_pid()}.fifo"
        regular.write_text("not a FIFO")
        request = self.base / f"audio-in-{dead}.fifo.request"
        request.write_text("44100 1")
        self.assertEqual(core.sweep_audio_fifos(self.base), 2)
        for path in removed:
            self.assertFalse(path.exists(), path)
        for path in kept + [regular, request]:
            self.assertTrue(path.exists(), path)
        self.assertEqual(core.sweep_audio_fifos(self.base / "missing"), 0)

    def test_logs_are_capped_by_count_and_total_size(self):
        self.patch("LOGS", self.base)
        names = [f"launch-20261012-1200{second:02d}.log" for second in range(6)]
        for index, name in enumerate(names):
            path = self.base / name
            path.write_bytes(b"x" * 100)
            os.utime(path, (1000 + index, 1000 + index))
        other = self.base / "run_debug-20261012.log"
        other.write_bytes(b"x" * 1000)
        current = self.base / names[0]  # oldest, but the running session's
        core.cleanup_logs(4, current=current, max_bytes=250)
        remaining = sorted(path.name for path in self.base.iterdir())
        # Newest two fit in 250 bytes; the current log and other tools' logs stay.
        self.assertEqual(remaining, sorted([names[5], names[4], names[0], other.name]))
        for index in range(3):
            trace = self.base / f"ciderdarling-trace-20261012-1300{index:02d}.jsonl"
            trace.write_bytes(b"t")
            os.utime(trace, (2000 + index, 2000 + index))
        core.cleanup_logs(1, max_bytes=10**9)
        self.assertEqual(sorted(path.name for path in self.base.glob("ciderdarling-trace-*")),
                         ["ciderdarling-trace-20261012-130002.jsonl"])

    def test_dserver_log_rotates_only_while_darling_is_stopped(self):
        self.patch("DARLING_PREFIX", self.base)
        log = self.base / "private/var/log/dserver.log"
        log.parent.mkdir(parents=True)
        old = log.with_name("dserver.log.old")
        old.write_text("older")
        log.write_bytes(b"x" * 64)
        with patch.object(core, "darlingserver_running", return_value=False):
            self.assertFalse(core.rotate_dserver_log(limit=64))
            log.write_bytes(b"x" * 65)
            with patch.object(core, "darlingserver_running", return_value=True):
                self.assertFalse(core.rotate_dserver_log(limit=64))
            self.assertTrue(core.rotate_dserver_log(limit=64))
        self.assertFalse(log.exists())
        self.assertEqual(old.read_bytes(), b"x" * 65)

    def test_warmup_output_never_goes_to_the_launch_log(self):
        self.patch("LOGS", self.base)
        seen = {}

        def run(command, **arguments):
            seen["stdout"] = os.readlink(f"/proc/self/fd/{arguments['stdout'].fileno()}")
            arguments["stdout"].write(b"darlingserver says hello\n")
            return Mock(returncode=0)

        with patch.object(core.subprocess, "run", side_effect=run):
            self.assertEqual(core._darling_warmup({}), 0)
        expected = self.base / f"darlingserver-{core.DARLING_RUNTIME['runtime']}.out"
        self.assertEqual(seen["stdout"], str(expected))
        self.assertEqual(core._warmup_output(), "darlingserver says hello\n")

    def ciderdarling(self, runtime="ciderdarling", **settings):
        session = bare_session(dict(core.DEFAULT_SETTINGS, **settings))
        with patch.object(core, "DARLING_RUNTIME", dict(core.DARLING_RUNTIME, runtime=runtime)):
            return session, session.ciderdarling_variables()

    def test_ciderdarling_settings_reach_only_ciderdarling(self):
        with patch.dict(os.environ, {}, clear=True):
            _session, variables = self.ciderdarling(cider_thread_kicks=True)
            self.assertEqual(variables, ["MACOBLOX_KICK=1"])
            _session, variables = self.ciderdarling("regular", cider_thread_kicks=True, cider_trace=True)
            self.assertEqual(variables, [])
        with patch.dict(os.environ, {"MACOBLOX_KICK": "1"}, clear=True):
            self.assertEqual(self.ciderdarling("regular")[1], ["MACOBLOX_KICK=1"])
            self.assertEqual(self.ciderdarling(cider_thread_kicks=True)[1].count("MACOBLOX_KICK=1"), 1)

    def test_allow_debugger_setting_reaches_the_game(self):
        for settings, environment, expected in (({}, {}, False), ({"allow_debugger": True}, {}, True),
                                                ({}, {"MACOBLOX_ALLOW_DEBUGGER": "1"}, True)):
            session = bare_session(dict(core.DEFAULT_SETTINGS, **settings))
            with self.subTest(settings=settings, environment=environment), \
                    patch.dict(os.environ, environment, clear=True), \
                    patch.object(core, "host_vram_bytes", return_value=0), \
                    patch.object(core, "icon_argb_file", side_effect=OSError):
                variables = session.shim_variables()
            self.assertEqual("MACOBLOX_ALLOW_DEBUGGER=1" in variables, expected)

    def test_trace_file_is_private_and_reaches_the_guest(self):
        log = self.base / "launch-20261012-120000.log"
        session, _variables = self.ciderdarling(cider_trace=True)
        with patch.object(core, "DARLING_RUNTIME", dict(core.DARLING_RUNTIME, runtime="ciderdarling")):
            old = os.umask(0o022)  # a usual umask must not widen the file
            try:
                trace = session._create_trace_file(log)
            finally:
                os.umask(old)
            self.assertEqual(trace, self.base / "ciderdarling-trace-20261012-120000.jsonl")
            info = trace.lstat()
            self.assertTrue(stat.S_ISREG(info.st_mode))
            self.assertEqual(stat.S_IMODE(info.st_mode), 0o600)
            session.trace_path = trace
            self.assertIn(f"CIDER_TRACE_FILE=/Volumes/SystemRoot{trace}", session.ciderdarling_variables())
            # An existing file (or symlink) is never reused.
            self.assertIsNone(session._create_trace_file(log))
            self.assertIn("trace unavailable", session.notes[-1])
        session, _variables = self.ciderdarling("regular", cider_trace=True)
        self.assertIsNone(session._create_trace_file(self.base / "launch-20261012-120001.log"))

    def test_server_from_another_installation_is_found(self):
        root = Path(self.temporary.name)
        (root / "new/bin").mkdir(parents=True)
        (root / "new/bin/darling").write_text("")
        (root / "new/bin/darlingserver").write_text("")
        links = {"/proc/11/exe": str(root / "new/bin/darlingserver"),
                 "/proc/12/exe": str(root / "old/bin/darlingserver") + " (deleted)"}
        with patch.object(core, "DARLING_EXECUTABLE", str(root / "new/bin/darling")), \
                patch.object(core, "_darlingservers", return_value=[11, 12, 13]), \
                patch.object(core.os, "readlink", side_effect=lambda path: links.get(path) or
                             (_ for _ in ()).throw(PermissionError(path))):
            self.assertEqual(core._foreign_darlingservers(), [12])  # 13 unreadable: left alone
        with patch.object(core, "DARLING_EXECUTABLE", str(root / "wrapper/darling")), \
                patch.object(core, "_darlingservers", return_value=[12]):
            self.assertEqual(core._foreign_darlingservers(), [])  # nothing to compare with

    def test_quit_sentinel_gives_roblox_time_to_save(self):
        self.patch("QUIT_GRACE_SECONDS", 0.5)
        session = bare_session()
        players = iter([[7], [7], []])
        with patch.object(core, "roblox_pids", side_effect=lambda names=None: (
                        next(players, []) if names == ("RobloxPlayer",) else ([7] if names is None else []))), \
                patch.object(core, "_terminate_roblox") as terminate:
            session.finish("quit_sentinel")
        # Roblox exited by itself; only a crash handler would have remained.
        terminate.assert_called_once_with([7], wait=1)
        session = bare_session()
        started = time.monotonic()
        with patch.object(core, "roblox_pids", return_value=[7]), \
                patch.object(core, "_terminate_roblox") as terminate:
            session.finish("quit_sentinel")
        self.assertGreaterEqual(time.monotonic() - started, 0.5)
        terminate.assert_called_once_with([7], wait=1)

    def test_server_ip_comes_from_the_newest_logs_tail(self):
        home = self.base / "home"
        logs = home / "Library/Logs/Roblox"
        logs.mkdir(parents=True)
        self.patch("DARLING_HOME", home)
        self.patch("LOGS", self.base / "launcher-logs")
        old = logs / "0.1_Player_old.log"
        old.write_text("Connection accepted from 1.1.1.1\n")
        os.utime(old, (1000, 1000))
        log = logs / "0.1_Player_new.log"
        log.write_text("Connection accepted from 8.8.8.8\n" + "x" * core.SERVER_LOG_TAIL)
        (logs / "0.1_RobloxCrashHandler_Player_x.log").write_text("Connection accepted from 9.9.9.9\n")
        self.assertEqual(core._latest_roblox_log(), log)
        self.assertIsNone(core.extract_server_ip())  # beyond the tail that is read
        with log.open("a") as stream:
            stream.write("\nConnection accepted from 8.8.4.4\n")
        self.assertEqual(core.extract_server_ip(), "8.8.4.4")

    def test_server_lookup_caches_failures_and_skips_private_addresses(self):
        self.patch("_server_location_cache", {})
        with patch.object(core.urllib.request, "urlopen", side_effect=OSError("offline")) as urlopen, \
                self.assertLogs("macoblox", level="WARNING"):
            self.assertIsNone(core.query_server_location("8.8.8.8"))
            self.assertIsNone(core.query_server_location("8.8.8.8"))
            self.assertEqual(urlopen.call_count, 1)
            with patch.object(core, "SERVER_LOCATION_RETRY", 0):
                core.query_server_location("8.8.8.8")
            self.assertEqual(urlopen.call_count, 2)
            for address in ("192.168.1.2", "127.0.0.1", "300.1.1.1", "not an address"):
                self.assertIsNone(core.query_server_location(address))
            self.assertEqual(urlopen.call_count, 2)

    def test_ciderdarling_shortcut_follows_installation(self):
        applications = self.base / "applications"
        entry = applications / core.CIDERDARLING_SHORTCUT
        with patch.object(core.subprocess, "run") as run, patch.dict(os.environ, {}, clear=True):
            self.assertTrue(core.sync_ciderdarling_shortcut(True, applications))
            text = entry.read_text()
            self.assertIn(core.SHORTCUT_MARKER, text.splitlines())
            self.assertIn(" --ciderdarling-settings\n", text)
            self.assertFalse(core.sync_ciderdarling_shortcut(True, applications))
            self.assertEqual(entry.read_text(), text)
            self.assertTrue(core.sync_ciderdarling_shortcut(False, applications))
            self.assertFalse(entry.exists())
            run.assert_called_with(["update-desktop-database", str(applications)], stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
            # The user's own entry of that name is never replaced or removed.
            entry.write_text("[Desktop Entry]\nName=Mine\n")
            self.assertFalse(core.sync_ciderdarling_shortcut(True, applications))
            self.assertFalse(core.sync_ciderdarling_shortcut(False, applications))
            self.assertEqual(entry.read_text(), "[Desktop Entry]\nName=Mine\n")
            entry.unlink()
            with patch.object(core, "PREBUILT_SHIM", "/usr/lib/ciderhq/shim"):
                core.sync_ciderdarling_shortcut(True, applications)
            self.assertIn("Exec=ciderhq --ciderdarling-settings\n", entry.read_text())
        packaged = (core.PROJECT / "packaging" / core.CIDERDARLING_SHORTCUT).read_text()
        self.assertEqual(packaged, entry.read_text())
        with patch.dict(os.environ, {"FLATPAK_ID": "org.ciderhq.Cider"}):
            self.assertFalse(core.sync_ciderdarling_shortcut(False, applications))
        self.assertTrue(entry.exists())


if __name__ == "__main__":
    unittest.main()
