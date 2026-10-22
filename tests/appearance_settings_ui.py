"""Bounded native GTK appearance regression and optional PNG previews.

GDK_BACKEND=x11 GSK_RENDERER=cairo GSETTINGS_BACKEND=memory xvfb-run -a \
  python3 tests/appearance_settings_ui.py [preview-directory]
Uses disposable settings and fake launch/update services; never starts Roblox.
"""
from contextlib import ExitStack
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from unittest.mock import patch

temporary = tempfile.TemporaryDirectory(prefix="quadra-appearance-")
base = Path(temporary.name)
os.environ.update(XDG_CONFIG_HOME=str(base / "config"), XDG_DATA_HOME=str(base / "data"),
                  XDG_CACHE_HOME=str(base / "cache"), GSETTINGS_BACKEND="memory")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))
threading.Thread.start = lambda self: None
from macoblox import app, core, theme
from gi.repository import Adw, Gdk, Gio, GLib, Gtk

Gtk.init()
application = Adw.Application(application_id="org.quadrahq.Quadra.AppearanceTest",
                              flags=Gio.ApplicationFlags.NON_UNIQUE)
application.register(None)
icons = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
icons.add_search_path(str(core.ICONS))
icons.add_search_path(str(core.PROJECT / "launcher/icons"))
saved = []
preview = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else None
if preview:
    preview.mkdir(parents=True, exist_ok=True)


def settle(seconds=0.1):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        while GLib.MainContext.default().iteration(False):
            pass
        time.sleep(.01)


def capture(window, name):
    if preview:
        settle(.4)
        width, height = window.get_width(), window.get_height()
        subprocess.run(["magick", "import", "-window", "root", "-crop", f"{width}x{height}+0+0",
                        "+repage", str(preview / (name + ".png"))], check=True, timeout=10)


with ExitStack() as context:
    context.enter_context(patch.object(core, "load_settings", return_value=dict(
        core.DEFAULT_SETTINGS, setup_complete=True, show_playtime=True, playtime_seconds=7440,
        auto_check_ciderdarling_updates=False, auto_check_roblox_updates=False)))
    context.enter_context(patch.object(core, "save_settings", side_effect=lambda value: saved.append(dict(value))))
    context.enter_context(patch.object(core, "installed_version", return_value="0.744.0.7441080"))
    darling = context.enter_context(patch.object(core, "darlingserver_running", return_value=False))
    context.enter_context(patch.object(core, "signed_in", return_value=True))
    context.enter_context(patch.object(app.LauncherWindow, "_periodic_ciderdarling_updates", return_value=False))
    context.enter_context(patch.object(app.GameLogsView, "update"))
    window = app.LauncherWindow(application)
    window.present()
    settle(.4)
    # All three choices act on the same live widgets, including pending logs.
    page, flags, play = window.play_page, window.flags_page, window.play_page.play
    assert page.dashboard_state.get_label() == "Darling stopped"
    darling.return_value = True
    deadline = time.monotonic() + 4
    while page.dashboard_state.get_label() != "Darling running" and time.monotonic() < deadline:
        settle(.05)
    assert page.dashboard_state.get_label() == "Darling running"
    darling.return_value = False
    page.refresh()
    logs = page.logs_view
    logs.buffer.set_text("[ERROR] test failure\n[INFO] same log after theme switch\n")
    row = window.settings_page.appearance_row
    assert row.get_model().get_n_items() == 3
    assert window.settings["launcher_appearance"] == "grid"
    assert window.backdrops.get_visible_child_name() == "grid"
    assert page.appearance_stack.get_visible_child_name() == "custom"
    assert page.action_bar.get_parent() is page.dashboard_actions
    capture(window, "grid-play")
    window.stack.set_visible_child_name("settings")
    capture(window, "grid-settings")
    window.stack.set_visible_child_name("play")
    session = object()
    window.session = session
    for code in ("monochrome", "gnome", "grid", "monochrome", "gnome", "grid"):
        row.set_selected(window.settings_page.appearance_codes.index(code))
        settle()
        assert window.settings["launcher_appearance"] == saved[-1]["launcher_appearance"] == code
        assert window.play_page is page and window.flags_page is flags and page.play is play
        assert window.session is session and page.logs_view is logs
        assert "same log" in logs.buffer.get_text(logs.buffer.get_start_iter(), logs.buffer.get_end_iter(), True)
        assert page.stack.get_pages().get_item(0).get_name() == "play"
        assert page.stack.get_pages().get_item(1).get_name() == "logs"
        assert window.backdrops.get_visible_child_name() == code
        assert page.appearance_stack.get_visible_child_name() == ("gnome" if code == "gnome" else "custom")
        assert (theme._provider is None) == (code == "gnome")
        assert window.appearance_layer.monochrome == (code == "monochrome")
        capture(window, code + "-play")
    window.session = None
    window.set_launcher_appearance("grid")
    window.set_setting("renderer", "vulkan")
    assert page.dashboard_facts["renderer"].get_label() == "Vulkan / Zink"
    window.set_setting("renderer", "opengl")
    window.set_default_size(620, 640)
    settle(.4)
    capture(window, "grid-narrow")
    assert window.split.get_collapsed() and not window.split.get_show_sidebar()
    window.set_language("ru")
    settle(.2)
    assert window.settings_page.appearance_row.get_title() == "Оформление лаунчера"
    assert window.settings["launcher_appearance"] == "grid"
    window.set_language("en")
    settle(.2)
    window.destroy()
    assert page._darling_status_timer == 0
    theme.install("gnome")

print("PASS: three live appearances persist, native CSS restores, controls/logs/unsaved pages/session survive, play/log tabs keep their order")
