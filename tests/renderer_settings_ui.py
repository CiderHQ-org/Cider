"""Optional UI regression; never installs packages or contacts an auth agent.

GDK_BACKEND=x11 GSK_RENDERER=cairo xvfb-run -a python3 tests/renderer_settings_ui.py
"""
from pathlib import Path
import sys
import threading
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))
# Suppress unrelated startup update/avatar workers in this UI fixture.
threading.Thread.start = lambda self: None
from macoblox import app, core, graphics
from gi.repository import Adw, Gio

saved, pending, errors = [], [], []
application = Adw.Application(application_id="wtf.aubree.MacOBlox.RendererTest",
                              flags=Gio.ApplicationFlags.NON_UNIQUE)
application.register(None)


def walk(widget):
    yield widget
    child = widget.get_first_child()
    while child:
        yield from walk(child)
        child = child.get_next_sibling()


with patch.object(core, "load_settings", return_value=dict(core.DEFAULT_SETTINGS)), \
        patch.object(core, "save_settings", side_effect=lambda value: saved.append(dict(value))), \
        patch.object(app.SettingsPage, "_in_thread", side_effect=lambda work, done: pending.append((work, done))), \
        patch.object(app, "_error_dialog", side_effect=lambda *args: errors.append(args)), \
        patch.object(graphics, "missing_vulkan_dependencies", return_value=["Zink"]):
    window = app.LauncherWindow(application)
    # Environment -> Game, and its copies on the Quadra M2VK and CiderDarling tabs.
    rows = [widget for widget in walk(window.settings_page)
            if isinstance(widget, Adw.ComboRow) and widget.get_title() == "Renderer"]
    assert len(rows) == 3
    row, middle, copy = rows
    assert row.get_model().get_string(2) == copy.get_model().get_string(2) == "Quadra M2VK (experimental)"
    row.set_selected(1)
    assert not row.get_sensitive() and not copy.get_sensitive() and window.settings["renderer"] == "opengl"
    work, done = pending.pop()
    assert work == graphics.ensure_vulkan_dependencies
    done(None, RuntimeError("Authentication cancelled"))
    assert row.get_sensitive() and row.get_selected() == 0 and errors
    assert copy.get_sensitive() and copy.get_selected() == 0
    assert window.settings["renderer"] == "opengl"
    assert not any(value["renderer"] == "vulkan" for value in saved)
    copy.set_selected(1)
    assert not row.get_sensitive() and not copy.get_sensitive()
    _work, done = pending.pop()
    done(True, None)
    assert row.get_sensitive() and row.get_selected() == 1 and copy.get_selected() == 1
    assert window.settings["renderer"] == saved[-1]["renderer"] == "vulkan"
    row.set_selected(0)
    assert copy.get_selected() == 0
    assert window.settings["renderer"] == saved[-1]["renderer"] == "opengl"
    with patch.object(core, "PREBUILT_SHIM", None), \
            patch.object(graphics, "missing_metal_dependencies", return_value=[]):
        queued_before = len(pending)
        row.set_selected(2)
        assert copy.get_selected() == 2 and window.settings["renderer"] == "metal"
        assert len(pending) == queued_before
        copy.set_selected(0)
    with patch.object(core, "PREBUILT_SHIM", "/prebuilt"), \
            patch.object(core, "metal_built", return_value=False):
        row.set_selected(2)
        assert row.get_selected() == copy.get_selected() == 0
        assert window.settings["renderer"] == "opengl"
        assert "not part of this package" in str(errors[-1])
    assert middle.get_selected() == row.get_selected() == copy.get_selected() == 0
    window.destroy()

print("PASS: renderer installation, cancellation, Metal selection, unavailable packages and switching back")
