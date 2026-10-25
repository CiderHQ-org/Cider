"""Optional UI regression for the Studio section; never starts Wine or contacts the network.

GDK_BACKEND=x11 GSK_RENDERER=cairo xvfb-run -a python3 tests/studio_settings_ui.py
"""
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))
# Suppress unrelated startup update/avatar workers in this UI fixture.
threading.Thread.start = lambda self: None
from quadra import app, core, studio
from gi.repository import Adw, Gio

saved, errors, toasts = [], [], []
application = Adw.Application(application_id="org.quadrahq.Quadra.StudioSettingsTest",
                              flags=Gio.ApplicationFlags.NON_UNIQUE)
application.register(None)


def walk(widget):
    yield widget
    child = widget.get_first_child()
    while child:
        yield from walk(child)
        child = child.get_next_sibling()


def rows(root, kind, title=None):
    return [widget for widget in walk(root) if isinstance(widget, kind)
            and (title is None or widget.get_title() == title)]


def tabs(page):
    pages = page.stack.get_pages()
    return [pages.get_item(index).get_name() for index in range(pages.get_n_items())]


def make_window():
    return app.LauncherWindow(application)


with patch.object(core, "load_settings", return_value=dict(core.DEFAULT_SETTINGS)), \
        patch.object(core, "save_settings", side_effect=lambda value: saved.append(dict(value))), \
        patch.object(app, "_error_dialog", side_effect=lambda *args: errors.append(args)), \
        patch.object(app, "_toast", side_effect=lambda overlay, text: toasts.append(text)), \
        patch.object(app, "_open_uri", side_effect=lambda window, uri: toasts.append(uri)), \
        patch.object(studio, "_state", return_value={"wine": "stable+1", "webview": "144.0.3719.92"}), \
        patch.object(studio, "installed_version", return_value="version-0123456789abcdef"), \
        patch.object(studio, "vulkan_layer_built", return_value=False):
    window = make_window()

    # The section sits next to Settings, with tabs of its own.
    names = [window.stack.get_pages().get_item(i).get_name() for i in range(window.stack.get_pages().get_n_items())]
    assert names == ["play", "settings", "studio", "mods", "info"], names
    page = window.studio_page
    assert tabs(page) == ["general", "graphics", "updates", "flags"], tabs(page)
    assert window.stack.get_page(page).get_title() == "Studio"

    # State shown.
    assert page.version_row.get_subtitle() == "version-0123456789abcdef"
    assert page.wine_status_row.get_subtitle() == "stable+1"
    assert page.webview_status_row.get_subtitle() == "144.0.3719.92"

    # Switches save their own setting.
    for title, key in (("Microsoft WebView2", "studio_webview"), ("Discord presence", "studio_discord"),
                       ("Follow the system theme", "studio_theme"), ("Back up sign-in and settings", "studio_backup"),
                       ("GameMode", "studio_gamemode")):
        row, = rows(page, Adw.SwitchRow, title)
        assert row.get_active() is core.DEFAULT_SETTINGS[key], title
        row.set_active(False)
        assert window.settings[key] is False and saved[-1][key] is False, title

    # Renderer: every choice saves; Vulkan warns while its layer is missing.
    assert page.renderer_codes == ["dxvk", "dxvk-sarek", "d3d11", "d3d11fl10", "vulkan"]
    assert page.renderer_row.get_selected() == 0 and not page.renderer_note.get_visible()
    for index, code in enumerate(page.renderer_codes):
        page.renderer_row.set_selected(index)
        assert window.settings["studio_renderer"] == code
        assert page.renderer_note.get_visible() == (code == "vulkan"), code
    with patch.object(studio, "vulkan_layer_built", return_value=True):
        page.renderer_row.set_selected(0)
        page.renderer_row.set_selected(4)
        assert not page.renderer_note.get_visible()

    # Graphics cards: hidden with one card, offered with several, the choice saves.
    assert not page.gpu_row.get_visible()
    cards = [{"id": "pci:0000:01:00.0", "label": "NVIDIA (0000:01:00.0)"},
             {"id": "pci:0000:00:02.0", "label": "Intel (0000:00:02.0)"}]
    page._gpu_choices_loaded(cards, None)
    assert page.gpu_row.get_visible() and page.gpu_row.get_sensitive()
    page.gpu_row.set_selected(2)
    assert window.settings["studio_gpu"] == "pci:0000:00:02.0"
    page.gpu_row.set_selected(0)
    assert window.settings["studio_gpu"] == ""
    page._gpu_choices_loaded([], OSError("no drm"))
    assert page.gpu_row.get_visible() and "Could not detect" in page.gpu_row.get_subtitle()

    # Kombucha releases: listed when the page is shown, pinned by choosing one.
    page._releases_loaded_done(["stable+20261018103513", "stable+20261009201837", "unstable"], None)
    assert page.wine_tags == ["", "stable+20261018103513", "stable+20261009201837", "unstable"]
    assert page.release_row.get_selected() == 0
    page.release_row.set_selected(2)
    assert window.settings["studio_wine"] == "stable+20261009201837"
    page.release_row.set_selected(0)
    assert window.settings["studio_wine"] == ""
    assert "may break Studio" in page.release_row.get_model().get_string(3)
    page._releases_loaded_done(None, OSError("rate limited"))
    assert "rate limited" in page.release_row.get_subtitle() and page.wine_tags == [""]

    # Version, channel and a Wine folder of your own: validated before they are saved.
    version, = rows(page, Adw.EntryRow, "Stay on version")
    channel, = rows(page, Adw.EntryRow, "Channel")
    wine_folder, = rows(page, Adw.EntryRow, "Wine folder of your own")
    version.set_text("version-nonsense")
    version.emit("apply")
    assert window.settings["studio_version"] == "" and version.has_css_class("error")
    version.set_text("version-0123456789abcdef")
    version.emit("apply")
    assert window.settings["studio_version"] == "version-0123456789abcdef" and not version.has_css_class("error")
    version.set_text("")
    version.emit("apply")
    assert window.settings["studio_version"] == ""
    channel.set_text("not a channel!")
    channel.emit("apply")
    assert window.settings["studio_channel"] == "" and channel.has_css_class("error")
    channel.set_text("zintegration")
    channel.emit("apply")
    assert window.settings["studio_channel"] == "zintegration"
    with tempfile.TemporaryDirectory() as directory:
        wine_folder.set_text(directory)
        wine_folder.emit("apply")
        assert window.settings["studio_wine_root"] == "" and "bin/wine" in toasts[-1]
        (Path(directory) / "bin").mkdir()
        (Path(directory) / "bin" / "wine").write_text("")
        wine_folder.set_text(directory)
        wine_folder.emit("apply")
        assert window.settings["studio_wine_root"] == directory
        page.refresh()
        assert page.wine_status_row.get_subtitle().startswith("Your own:")
        wine_folder.set_text("")
        wine_folder.emit("apply")
    assert window.settings["studio_wine_root"] == ""

    # Studio's fast flags: added in rows, typed values, saved after a moment, removed again.
    flags = page.flags_page
    assert flags.flags == {}
    for name, value in (("FIntFramerateCap", "144"), ("FFlagSomething", "true"), ("", "")):
        flags._add_row("", "")  # a new row is empty; the person types into it
        flags.rows[-1]["name"].set_text(name)
        flags.rows[-1]["value"].set_text(value)
    flags.flush()
    assert window.settings["studio_fflags"] == {"FIntFramerateCap": 144, "FFlagSomething": True}, window.settings["studio_fflags"]
    flags.rows[1]["value"].set_text("false")
    flags.flush()
    assert window.settings["studio_fflags"]["FFlagSomething"] is False
    flags.group.remove(flags.rows[0]["row"])
    flags.rows.pop(0)
    flags._sync()
    flags.flush()
    assert window.settings["studio_fflags"] == {"FFlagSomething": False}
    flags._reset()
    assert window.settings["studio_fflags"] == {} and flags.rows == []

    # Folders open (and are created first).
    with tempfile.TemporaryDirectory() as directory, patch.object(studio, "OVERLAY", Path(directory) / "overlay"):
        row, = rows(page, Adw.ActionRow, "Overlay folder")
        row.emit("activated")
        assert (Path(directory) / "overlay").is_dir() and toasts[-1] == (Path(directory) / "overlay").as_uri()

    # Both Studio buttons follow an install.
    play = window.play_page
    for view in window._studio_views():
        assert view.set_studio_busy
    assert window._studio_views() == [play, page]
    window.studio_page.set_studio_busy(True, "Checking…")
    play.set_studio_busy(True, "Checking…")
    assert not page.launch_row.get_sensitive() and page.launch_row.get_title() == "Checking…"
    assert not play.studio.get_sensitive() and play.studio.get_label() == "Checking…"
    page.show_studio_progress(0.5, "Roblox Studio: 280 of 567 MB")
    play.show_studio_progress(0.5, "Roblox Studio: 280 of 567 MB")
    assert page.progress.get_visible() and play.studio_progress.get_visible()
    assert page.progress.get_text() == play.studio_progress.get_text()
    for view in window._studio_views():
        view.set_studio_busy(False)
        view.hide_studio_progress()
    assert page.launch_row.get_sensitive() and page.launch_row.get_title() == "Launch Roblox Studio"
    assert play.studio.get_sensitive() and play.studio.get_label() == "Roblox Studio"
    assert not page.progress.get_visible() and not play.studio_progress.get_visible()

    # The launch button of the section starts the same flow as Play's.
    with patch.object(app.LauncherWindow, "studio_clicked") as clicked:
        page.launch_row.emit("activated")
        clicked.assert_called_once()

    # Tabs follow the launcher's appearance like Settings' do.
    window.set_launcher_appearance("monochrome")
    assert page.appearance_tabs.get_visible_child_name() == "custom"
    window.set_launcher_appearance("gnome")
    assert page.appearance_tabs.get_visible_child_name() == "gnome"
    window.destroy()

    # No Wine in the Flatpak: the section is not there.
    real = app.os.path.exists
    with patch.object(app.os.path, "exists", side_effect=lambda path: path == "/.flatpak-info" or real(path)):
        flatpak = make_window()
        names = [flatpak.stack.get_pages().get_item(i).get_name() for i in range(flatpak.stack.get_pages().get_n_items())]
        assert names == ["play", "settings", "mods", "info"], names
        assert not hasattr(flatpak, "studio_page")
        assert flatpak._studio_views() == [flatpak.play_page]
        flatpak.destroy()

print("PASS: Studio section, tabs, settings saved and validated, flags editor, releases, GPUs, buttons, Flatpak")
