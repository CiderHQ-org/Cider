"""Optional bounded GTK fixture in disposable Xvfb; no client or network.

GDK_BACKEND=x11 GSK_RENDERER=cairo xvfb-run -a python3 tests/dpi_settings_ui.py
"""
from pathlib import Path
import sys
import threading
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))
threading.Thread.start = lambda self: None
from quadra import app, core
from gi.repository import Adw, Gio

saved = []
application = Adw.Application(application_id="org.quadrahq.Quadra.DpiTest",
                              flags=Gio.ApplicationFlags.NON_UNIQUE)
application.register(None)

def walk(widget):
    yield widget
    child = widget.get_first_child()
    while child:
        yield from walk(child)
        child = child.get_next_sibling()

with patch.object(core, "load_settings", return_value=dict(core.DEFAULT_SETTINGS)), \
        patch.object(core, "save_settings", side_effect=lambda value: saved.append(dict(value))):
    window = app.LauncherWindow(application)
    rows = [widget for widget in walk(window.settings_page)
            if isinstance(widget, Adw.SpinRow) and widget.get_title() == "Roblox UI scale"]
    assert len(rows) == 1
    row = rows[0]
    assert row.get_value() == 100
    assert "next launch" in row.get_subtitle()
    adjustment = row.get_adjustment()
    assert adjustment.get_lower() == 100 and adjustment.get_upper() == 400
    assert adjustment.get_step_increment() == 25
    row.set_value(175)
    assert window.settings["dpi_scale"] == saved[-1]["dpi_scale"] == 1.75
    row.set_value(400)
    assert window.settings["dpi_scale"] == saved[-1]["dpi_scale"] == 4.0
    row.set_value(100)
    assert window.settings["dpi_scale"] == saved[-1]["dpi_scale"] == 1.0
    window.destroy()

print("PASS Roblox UI scale100..400percent, step25, default100, settings persist, nextlaunch subtitle")
