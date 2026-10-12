"""Optional real terminal fixture; uses only a fake installer and private display.

GSETTINGS_BACKEND=memory GDK_BACKEND=x11 QT_QPA_PLATFORM=xcb \
  dbus-run-session -- xvfb-run -a python3 tests/runtime_install_terminal.py
"""
from contextlib import ExitStack
import os
from pathlib import Path
import shlex
import shutil
import signal
import sys
import tempfile
import time
from unittest.mock import patch

temporary = tempfile.TemporaryDirectory()
base = Path(temporary.name)
os.environ.update(XDG_CONFIG_HOME=str(base / "config"), XDG_CACHE_HOME=str(base / "cache"),
                  XDG_DATA_HOME=str(base / "data"), DPREFIX=str(base / "prefix"))
for key in ("WAYLAND_DISPLAY", "BASH_ENV", "ENV"):
    os.environ.pop(key, None)
(base / "config").mkdir()
(base / "config/xdg-terminals.list").write_text("org.kde.konsole.desktop\n")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))
from macoblox import app, runtime_install, terminal
from runtime_update_fixture import release_fixture
from gi.repository import Gtk

Gtk.init()
window = Gtk.Window()
project = base / "Cider %f ' $() directory"
project.mkdir()
arguments = base / "arguments"
installer = project / "install.sh"
installer.write_text('#!/bin/bash\n[[ -t 0 && -t 1 ]] || exit 41\n'
                     'test -r /dev/tty || exit 42\n'
                     'printf "%s\\n" "$@" > ' + shlex.quote(str(arguments)) + '\nexit 0\n')
try:
    # The desktop default (xdg-terminal-exec), Cider's own terminal list with
    # xdg-terminal-exec hidden, then GIO's list as the last resort.
    real_which = shutil.which
    without_xdg = lambda name: None if name == "xdg-terminal-exec" else real_which(name)
    modes = {"desktop default": [],
             "own terminal list": [patch.object(terminal.shutil, "which", without_xdg),
                                   patch.dict(os.environ, {"TERMINAL": "", "XDG_CURRENT_DESKTOP": "KDE"})],
             "GIO fallback": [patch.object(app.terminal, "command", return_value=None)]}
    for mode, patches in modes.items():
        release = release_fixture() if mode == "GIO fallback" else None
        job = runtime_install.Installation.create(project, "ciderdarling", base / "cache", release=release)
        try:
            with ExitStack() as stack:
                for active in patches:
                    stack.enter_context(active)
                assert app._launch_runtime_terminal(window, job.command)
            deadline = time.monotonic() + 20
            while True:
                status = job.poll()
                if status is not None:
                    assert status == 0, f"Fake terminal installer exited {status}"
                    break
                if time.monotonic() > deadline:
                    raise AssertionError("Terminal did not finish the fake installer")
                time.sleep(.05)
            expected = ["--install-runtime", "--darling", "ciderdarling", "--pinned-runtime"]
            if release:
                expected += ["--runtime-release", str(job.directory / "release.json")]
                assert job.target_revision == release['source_revision']
            assert arguments.read_text().splitlines() == expected
            arguments.unlink()
            print(f"PASS: real terminal ({mode}) supplies a TTY and preserves special-character paths")
        finally:
            started = job.directory / "started"
            if started.exists():
                pid = int(started.read_text())
                try:
                    process_arguments = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
                    if os.fsencode(job.directory) in process_arguments:
                        os.kill(pid, signal.SIGHUP)  # Only the owned fake installer shell.
                except FileNotFoundError:
                    pass
            job.close()
    # No terminal anywhere: GIO's error becomes an explanation.
    empty = base / "empty-path"
    empty.mkdir()
    with patch.object(app.terminal, "command", return_value=None), patch.dict(os.environ, {"PATH": str(empty)}):
        try:
            app._launch_runtime_terminal(window, ["true"])
        except RuntimeError as error:
            assert "No terminal application was found" in str(error), error
        else:
            raise AssertionError("Launching without any terminal did not fail")
    print("PASS: no terminal reports how to fix it")
finally:
    window.destroy()
    temporary.cleanup()
