import fcntl
import os
from pathlib import Path
import pty
import shlex
import signal
import subprocess
import tempfile
import termios
import time
import unittest
from unittest.mock import patch

from macoblox.runtime_install import Installation


class RuntimeInstallationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.project = self.root / "Cider % $() ' space"
        self.project.mkdir()
        self.installer = self.project / "install.sh"
        self.installer.write_text("exit 0\n")
        self.arguments = self.root / "arguments"

    def create(self):
        return Installation.create(self.project, "ciderdarling", self.root / "cache")

    def test_missing_installer_unknown_variant_and_flatpak_do_not_start(self):
        with self.assertRaises(ValueError):
            Installation.create(self.project, "ciderdarling; echo bad", self.root)
        with patch.dict(os.environ, FLATPAK_ID="org.ciderhq.Cider"):
            with self.assertRaises(RuntimeError):
                self.create()
        self.installer.unlink()
        with self.assertRaises(FileNotFoundError):
            self.create()
        self.assertFalse((self.root / "cache").exists())

    def test_startup_timeout_and_stale_pid_are_reported(self):
        job = self.create()
        self.assertEqual(job.directory.stat().st_mode & 0o777, 0o700)
        self.assertIsNone(job.poll())
        job.created -= 31
        with self.assertRaisesRegex(RuntimeError, "did not start"):
            job.poll()
        (job.directory / "started").write_text(str(os.getpid()))
        with self.assertRaisesRegex(RuntimeError, "closed before"):
            job.poll()
        job.close()

    def test_status_validation_and_only_own_directory_removed(self):
        job = self.create()
        sibling = job.directory.parent / "keep"
        sibling.write_text("other work")
        for value in ("broken", "-1", "256"):
            (job.directory / "result").write_text(value)
            with self.assertRaises(RuntimeError):
                job.poll()
        for value in (0, 1, 130):
            (job.directory / "result").write_text(str(value))
            self.assertEqual(job.poll(), value)
        job.close()
        self.assertEqual(sibling.read_text(), "other work")

    def terminal(self, job):
        master, slave = pty.openpty()
        def controlling_terminal():
            os.setsid()
            fcntl.ioctl(0, termios.TIOCSCTTY, 0)
        process = subprocess.Popen(job.command, stdin=slave, stdout=slave, stderr=slave,
                                   preexec_fn=controlling_terminal)
        os.close(slave)
        def cleanup():
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=5)
            os.close(master)
        self.addCleanup(cleanup)
        return process, master

    def wait_for(self, condition):
        deadline = time.monotonic() + 5
        while not condition():
            if time.monotonic() > deadline:
                self.fail("Test installer did not respond")
            time.sleep(.01)

    def test_interactive_wrapper_preserves_arguments_result_and_terminal(self):
        for status in (0, 7):
            with self.subTest(status=status):
                self.installer.write_text(
                    '#!/bin/bash\n[[ -t 0 && -t 1 ]] || exit 41\n'
                    'IFS= read -r answer </dev/tty\n[[ $answer == y ]] || exit 42\n'
                    'printf "%s\\n" "$@" > ' + shlex.quote(str(self.arguments)) + '\n'
                    f'exit {status}\n')
                job = self.create()
                process, master = self.terminal(job)
                os.write(master, b"y\n")
                self.wait_for(lambda: (job.directory / "result").exists())
                self.assertEqual(job.poll(), status)
                self.assertEqual(self.arguments.read_text().splitlines(),
                                 ["--install-runtime", "--darling", "ciderdarling"])
                self.assertIsNone(process.poll(), "Terminal must remain open for the build output")
                job.close()
                os.write(master, b"\n")
                self.assertEqual(process.wait(timeout=5), status)

    def test_late_terminal_after_timeout_does_not_run_installer(self):
        self.installer.write_text('touch ' + shlex.quote(str(self.arguments)) + '\n')
        job = self.create()
        job.close()
        process, _master = self.terminal(job)
        self.assertEqual(process.wait(timeout=5), 125)
        self.assertFalse(self.arguments.exists())
