"""Optional UI regression for the Quadra M2VK settings group.

GDK_BACKEND=x11 GSK_RENDERER=cairo xvfb-run -a python3 tests/m2vk_settings_ui.py
"""
from pathlib import Path
import sys
import threading
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))
# Suppress unrelated startup update/avatar workers in this UI fixture.
threading.Thread.start = lambda self: None
from quadra import app, core, graphics
from gi.repository import Adw, Gio

saved, errors = [], []
application = Adw.Application(application_id="org.quadrahq.Quadra.M2VKSettingsTest",
                              flags=Gio.ApplicationFlags.NON_UNIQUE)
application.register(None)


def walk(widget):
    yield widget
    child = widget.get_first_child()
    while child:
        yield from walk(child)
        child = child.get_next_sibling()


def row(window, title, kind):
    found = [w for w in walk(window.settings_page) if isinstance(w, kind) and w.get_title() == title]
    assert len(found) == 1, (title, len(found))
    return found[0]


with patch.object(core, "load_settings", return_value=dict(core.DEFAULT_SETTINGS)), \
        patch.object(core, "save_settings", side_effect=lambda value: saved.append(dict(value))), \
        patch.object(app, "_error_dialog", side_effect=lambda *args: errors.append(args)):
    window = app.LauncherWindow(application)
    page = window.settings_page
    group = page.m2vk_group
    # Its own tab, holding the renderer choice and the settings.
    tab = page.stack.get_page(page.m2vk_page)
    assert tab.get_name() == "m2vk" and tab.get_title() == "Quadra M2VK"
    assert [p.get_name() for p in page.stack.get_pages()][:2] == ["env", "m2vk"]
    assert group.get_parent() is not None
    tab_renderer = [w for w in walk(page.m2vk_page) if isinstance(w, Adw.ComboRow) and w.get_title() == "Renderer"]
    assert len(tab_renderer) == 1
    assert group not in list(walk(page.env_page)), "the settings are no longer on the Environment tab"
    # Only meaningful for Quadra M2VK.
    assert window.settings["renderer"] == "opengl" and not group.get_sensitive()
    with patch.object(core, "PREBUILT_SHIM", None), \
            patch.object(graphics, "missing_metal_dependencies", return_value=[]):
        renderer = [w for w in walk(page) if isinstance(w, Adw.ComboRow) and w.get_title() == "Renderer"][0]
        renderer.set_selected(2)
        assert window.settings["renderer"] == "metal" and group.get_sensitive()

    accuracy = row(window, "Accuracy", Adw.ComboRow)
    present = row(window, "Frame presentation", Adw.ComboRow)
    priority = row(window, "Keep important graphics memory resident", Adw.SwitchRow)
    memory = row(window, "Graphics memory limit (GiB)", Adw.SpinRow)
    threads = row(window, "Shader compile threads", Adw.SpinRow)
    warm = row(window, "Learned shaders kept ready", Adw.SpinRow)

    # The defaults are shown as stored.
    assert accuracy.get_selected() == 0 and present.get_selected() == 0 and priority.get_active()
    assert memory.get_value() == 0 and threads.get_value() == 0 and warm.get_value() == 256
    assert graphics.metal_tuning_environment(window.settings) == {}

    accuracy.set_selected(2)
    present.set_selected(2)
    priority.set_active(False)
    memory.set_value(4)
    threads.set_value(2)
    warm.set_value(512)
    assert window.settings["metal_accuracy"] == "exact"
    assert window.settings["metal_present_mode"] == "fifo"
    assert window.settings["metal_memory_priority"] is False
    assert (window.settings["metal_vram_limit_gib"], window.settings["metal_compile_threads"],
            window.settings["metal_warm_states"]) == (4, 2, 512)
    assert saved[-1]["metal_warm_states"] == 512
    assert graphics.metal_tuning_environment(window.settings) == {
        "MACOBLOX_METAL_ACCURACY": "exact", "MACOBLOX_METAL_PRESENT_MODE": "fifo",
        "MACOBLOX_METAL_MEMORY_PRIORITY": "0", "MACOBLOX_METAL_COMPILE_THREADS": "2",
        "MACOBLOX_METAL_WARM_STATES": "512"}

    # Reset puts every row and every stored value back.
    reset = [w for w in walk(page) if isinstance(w, (Adw.ActionRow, getattr(Adw, "ButtonRow", Adw.ActionRow)))
             and w.get_title() == "Reset Quadra M2VK settings"][0]
    reset.emit("activated")
    assert accuracy.get_selected() == 0 and present.get_selected() == 0 and priority.get_active()
    assert (memory.get_value(), threads.get_value(), warm.get_value()) == (0, 0, 256)
    assert graphics.metal_tuning_environment(window.settings) == {}
    assert not errors

    # Back to OpenGL greys the group again, but the renderer row on its own tab stays usable.
    tab_renderer[0].set_selected(0)
    assert window.settings["renderer"] == "opengl" and not group.get_sensitive()
    assert tab_renderer[0].get_sensitive()
    tab_renderer[0].set_selected(2)
    assert window.settings["renderer"] == "metal" and group.get_sensitive()
    tab_renderer[0].set_selected(0)
    window.destroy()

print("PASS: Quadra M2VK settings group: availability, saving, environment and reset")
