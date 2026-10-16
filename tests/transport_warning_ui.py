"""Real GTK warning regression in disposable Xvfb; no game or network.

GDK_BACKEND=x11 GSK_RENDERER=cairo xvfb-run -a python3 tests/transport_warning_ui.py
"""
from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import Mock, patch

temporary = tempfile.TemporaryDirectory()
base = Path(temporary.name)
os.environ.update(XDG_CONFIG_HOME=str(base / "config"), XDG_CACHE_HOME=str(base / "cache"),
                  XDG_DATA_HOME=str(base / "data"))
for name in ("DPREFIX", "FLATPAK_ID", "MACOBLOX_PAGE"):
    os.environ.pop(name, None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))
threading.Thread.start = lambda self: None  # no unrelated startup/avatar workers
from macoblox import app, core
from session_fixture import bare_session
from gi.repository import Adw, Gio, GLib

application = Adw.Application(application_id="org.ciderhq.Cider.TransportTest",
                              flags=Gio.ApplicationFlags.NON_UNIQUE)
application.register(None)
settings = dict(core.DEFAULT_SETTINGS, setup_complete=True, discord_rpc=False,
                hide_launcher_on_launch=True, show_launcher_after_exit=False)

with ExitStack() as context:
    context.enter_context(patch.object(core, "load_settings", return_value=settings))
    context.enter_context(patch.object(core, "save_settings"))
    context.enter_context(patch.object(core, "installed_version", return_value="0.743.0.7431134"))
    context.enter_context(patch.object(core, "roblox_pids", return_value=[]))
    context.enter_context(patch.object(core, "exit_reason", return_value=None))
    context.enter_context(patch.object(app.uri_handoff, "peek_pending", return_value=None))
    window = app.LauncherWindow(application)
    context.callback(window.destroy)
    updates = context.enter_context(patch.object(window.settings_page, "check_launcher_update"))
    logs = context.enter_context(patch.object(window.play_page, "show_logs"))
    quit_app = context.enter_context(patch.object(application, "quit"))
    session = bare_session(settings)
    session.log_path = base / "launch.log"
    window.session = session
    window.last_log = session.log_path
    window.set_visible(False)
    window._show_transport_warning(session)
    assert window._transport_warning_dialog is None and not window.get_visible()
    session.transport_monitor.selected_transport = "RakNet"
    window._show_transport_warning(session)
    assert window._transport_warning_dialog is None

    session.transport_monitor.selected_transport = "RbxTransport"
    window._watch_result(session, None)
    dialog = window._transport_warning_dialog
    assert dialog is not None and window.get_visible()
    assert "Roblox update" in dialog.get_heading()
    assert all(word in dialog.get_body() for word in ("RakNet", "Error 256", "wait", "patch"))
    window._hide_while_playing()
    assert window.get_visible()  # startup hide timer cannot hide the warning
    window._show_transport_warning(session)
    assert window._transport_warning_dialog is dialog  # one warning per launch

    # Optional screenshot of this disposable test window only.
    if len(sys.argv) == 2:
        import subprocess, time
        for _ in range(30):
            while GLib.MainContext.default().iteration(False):
                pass
            time.sleep(0.01)
        subprocess.run(["import", "-window", "root", sys.argv[1]], check=True)
    dialog.emit("response", "updates")
    dialog.close()
    updates.assert_called_once_with()
    assert window.stack.get_visible_child_name() == "settings"
    assert window._transport_warning_dialog is None
    window._show_transport_warning(session)
    assert window._transport_warning_dialog is None  # dismissal suppresses repeats

    newer = bare_session(settings)
    newer.log_path = base / "new.log"
    newer.transport_monitor.selected_transport = "RbxTransport"
    window.session = newer
    window.last_log = newer.log_path
    window._show_transport_warning(session)
    assert window._transport_warning_dialog is None  # stale session ignored
    window._watch_result(newer, 0)
    dialog = window._transport_warning_dialog
    assert dialog is not None and window.session is None and window.get_visible()
    quit_app.assert_not_called()  # exit preferences cannot hide a new warning
    dialog.emit("response", "logs")
    dialog.close()
    logs.assert_called_once_with(newer.log_path)
    assert window._transport_warning_dialog is None

print("PASS: real transport warning without Discord, hidden launcher, hide timer, dismissal, stale session, update/log actions and clean exit")
