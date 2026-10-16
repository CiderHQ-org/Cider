from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from macoblox import core
from macoblox.transport_monitor import TransportMonitor
from session_fixture import bare_session


def selection(name):
    return (b"2026-10-16T03:21:52.204Z,4.204038,9d7ed000,6,Info "
            b"[DFLog::NetworkClient] Transport selection: useRbxTransportEnabled=true, "
            b"selectedTransport=" + name + b", rccPort=1\n")


class TransportMonitorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "launch.log"
        self.monitor = TransportMonitor()

    def append(self, data):
        with self.path.open("ab") as log:
            log.write(data)
        self.monitor.poll(self.path)

    def test_raknet_is_safe_despite_unsupported_header_and_other_transport_activity(self):
        self.append(b"RakNet compatibility: unsupported client; transport binary left unchanged\n"
                    b"[DFLog::RbxTransportRnaExp] Initialized RtcIoRna\n"
                    + selection(b"RakNet"))
        self.assertEqual(self.monitor.selected_transport, "RakNet")
        self.assertIsNone(self.monitor.warning_transport)

    def test_actual_selection_warns_and_latest_selection_wins(self):
        self.append(selection(b"RbxTransport"))
        self.assertEqual(self.monitor.warning_transport, "RbxTransport")
        self.append(selection(b"RakNet"))
        self.assertIsNone(self.monitor.warning_transport)
        self.append(selection(b"FutureTransport"))
        self.assertEqual(self.monitor.warning_transport, "FutureTransport")

    def test_partial_lines_and_crlf(self):
        line = selection(b"RbxTransport").removesuffix(b"\n")
        self.append(line[:100])
        self.assertIsNone(self.monitor.warning_transport)
        self.append(line[100:] + b"\r\n")
        self.assertEqual(self.monitor.warning_transport, "RbxTransport")

    def test_non_client_channel_or_invalid_transport_is_not_evidence(self):
        for line in (selection(b"RbxTransport").replace(b"NetworkClient", b"Output"),
                     b"[FLog::Output] " + selection(b"RbxTransport"),
                     b"selectedTransport=RbxTransport\n", selection(b"RakNet/unknown"),
                     selection(b"x" * 33)):
            self.append(line)
        self.assertIsNone(self.monitor.selected_transport)

    def test_replacement_and_truncation_discard_old_state_and_partial_lines(self):
        self.append(selection(b"RbxTransport") + b"unfinished")
        replacement = self.path.with_suffix(".new")
        replacement.write_bytes(selection(b"RakNet"))
        replacement.replace(self.path)
        self.monitor.poll(self.path)
        self.assertIsNone(self.monitor.warning_transport)
        self.path.write_bytes(b"")
        self.monitor.poll(self.path)
        self.assertIsNone(self.monitor.selected_transport)
        self.append(selection(b"RbxTransport"))
        self.assertEqual(self.monitor.warning_transport, "RbxTransport")

    def test_oversized_lines_are_skipped_and_work_per_poll_is_bounded(self):
        self.monitor.READ_SIZE = 128
        self.monitor.READS_PER_POLL = 2
        self.monitor.LINE_LIMIT = 200
        data = b"x" * 4000 + selection(b"RbxTransport")
        self.append(data)
        self.assertEqual(self.monitor._position, 256)
        self.assertIsNone(self.monitor.warning_transport)
        for _ in range(20):
            self.monitor.poll(self.path)
        self.assertIsNone(self.monitor.warning_transport)  # same oversized line
        self.append(selection(b"RbxTransport"))
        self.assertEqual(self.monitor.warning_transport, "RbxTransport")
        position = self.monitor._position
        self.monitor.poll(self.path)
        self.assertEqual(self.monitor._position, position)

    def test_missing_or_unreadable_log_is_not_evidence(self):
        self.monitor.poll(None)
        self.monitor.poll(self.path)
        with patch("builtins.open", side_effect=PermissionError):
            self.monitor.poll(self.path)
        self.assertIsNone(self.monitor.warning_transport)

    def test_session_checks_transport_even_without_discord_and_before_early_exit(self):
        session = bare_session(dict(core.DEFAULT_SETTINGS, discord_rpc=False))
        self.path.write_bytes(selection(b"RbxTransport"))
        session.log_path = self.path
        session.process = Mock()
        session.process.poll.return_value = 0
        with patch.object(core, "roblox_pids", return_value=[]), patch.object(session, "finish"):
            self.assertEqual(session.poll(), 0)
        self.assertEqual(session.transport_monitor.warning_transport, "RbxTransport")


if __name__ == "__main__":
    unittest.main()
