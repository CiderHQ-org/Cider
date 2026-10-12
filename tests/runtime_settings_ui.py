"""Real GTK runtime switching in disposable Xvfb; no game, install or restart.

GDK_BACKEND=x11 GSK_RENDERER=cairo xvfb-run -a python3 tests/runtime_settings_ui.py
"""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch

temporary = tempfile.TemporaryDirectory()
base = Path(temporary.name)
os.environ.update(HOME=str(base), XDG_CONFIG_HOME=str(base / "config"),
                  XDG_CACHE_HOME=str(base / "cache"), XDG_DATA_HOME=str(base / "data"))
for key in ("DPREFIX", "FLATPAK_ID", "MACOBLOX_PAGE"):
    os.environ.pop(key, None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "launcher"))
# Do not run startup update checks, author avatars or other unrelated workers.
threading.Thread.start = lambda self: None
from macoblox import app, core, runtime
from gi.repository import Adw, Gio

selection_file = base / "runtime.json"
choices = {}
for variant in runtime.VARIANTS:
    root = base / variant
    client = root / "bin/darling"
    client.parent.mkdir(parents=True)
    client.write_text("#!/bin/sh\nexit 0\n"); client.chmod(0o755)
    sysroot = root / "libexec/darling"
    sysroot.mkdir(parents=True)
    choices[variant] = {"schema_version": 1, "runtime": variant,
                        "executable": str(client), "sysroot": str(sysroot),
                        "prefix": str(base / (variant + " custom prefix"))}
metadata = Path(choices["ciderdarling"]["sysroot"]) / "usr/share/ciderdarling/runtime.json"
metadata.parent.mkdir(parents=True)
metadata.write_text(json.dumps({"schema_version": 1, "name": "CiderDarling", "architecture": "x86_64"}))
original_discovery = runtime.installed_runtimes


def discovery(current):
    return original_discovery(current, selection_file=selection_file,
                              regular_clients=[entry["executable"] for entry in choices.values()],
                              cider_directory=base / "versions")


application = Adw.Application(application_id="org.ciderhq.Cider.RuntimeTest",
                              flags=Gio.ApplicationFlags.NON_UNIQUE)
application.register(None)
errors, restarts = [], []


def fixture(active="ciderdarling"):
    context = ExitStack()
    current = dict(choices[active], metadata=runtime.metadata(choices[active]["sysroot"]))
    context.enter_context(patch.object(core, "DARLING_RUNTIME", current))
    context.enter_context(patch.object(core, "DARLING_PREFIX", Path(current["prefix"])))
    context.enter_context(patch.object(core, "DARLING_EXECUTABLE", current["executable"]))
    context.enter_context(patch.object(core, "DARLING_SYSROOT", Path(current["sysroot"])))
    context.enter_context(patch.object(core, "load_settings", return_value=dict(core.DEFAULT_SETTINGS,
                                                                             setup_complete=True,
                                                                             auto_check_roblox_updates=False)))
    context.enter_context(patch.object(core, "save_settings"))
    context.enter_context(patch.object(core, "roblox_pids", return_value=[]))
    context.enter_context(patch.object(core, "restart_darling", side_effect=AssertionError("Must not stop a runtime")))
    context.enter_context(patch.object(runtime, "installed_runtimes", side_effect=discovery))
    context.enter_context(patch.object(runtime, "selection_path", return_value=selection_file))
    context.enter_context(patch.object(app, "_error_dialog", side_effect=lambda *args: errors.append(args)))
    context.enter_context(patch.object(app, "_restart_launcher", side_effect=lambda: restarts.append(True)))
    window = app.LauncherWindow(application)
    context.callback(window.destroy)
    return context, window


runtime.save_selection(choices["ciderdarling"], selection_file, current=choices["regular"])
context, window = fixture()
with context:
    page = window.settings_page
    assert page.runtime_row.get_title() == "Darling runtime"
    assert page.runtime_row.get_model().get_string(0) == "DarlingHQ's Darling"
    assert page.runtime_row.get_model().get_string(1) == "CiderHQ's CiderDarling"
    assert page.runtime_row.get_selected() == 1 and not page.runtime_apply_button.get_sensitive()
    before = selection_file.read_bytes()
    page.runtime_row.set_selected(0)
    assert page.runtime_apply_button.get_sensitive() and selection_file.read_bytes() == before
    window.busy = "building"
    page.runtime_apply_button.emit("clicked")
    assert not restarts and selection_file.read_bytes() == before
    window.busy = None
    window.session = object()
    page.runtime_apply_button.emit("clicked")
    assert not restarts and selection_file.read_bytes() == before
    window.session = None
    with patch.object(core, "roblox_pids", return_value=[999]):
        page.runtime_apply_button.emit("clicked")
    assert not restarts and selection_file.read_bytes() == before and window.busy is None
    page.runtime_apply_button.emit("clicked")
    selected = runtime.read_selection(selection_file)
    assert selected["runtime"] == "regular" and selected["prefix"] == choices["regular"]["prefix"]
    assert len(restarts) == 1
    assert runtime.remembered_runtimes(selected)["ciderdarling"]["prefix"] == choices["ciderdarling"]["prefix"]

context, window = fixture("regular")
with context:
    page = window.settings_page
    assert page.runtime_row.get_selected() == 0
    page.runtime_row.set_selected(1)
    page.runtime_apply_button.emit("clicked")
    selected = runtime.read_selection(selection_file)
    assert selected["runtime"] == "ciderdarling" and selected["prefix"] == choices["ciderdarling"]["prefix"]
    assert len(restarts) == 2

context, window = fixture()
with context:
    page = window.settings_page
    page.runtime_row.set_selected(0)
    before = selection_file.read_bytes()
    with patch.object(runtime, "save_selection", side_effect=OSError("Fixture cannot write config")):
        page.runtime_apply_button.emit("clicked")
    assert errors and len(restarts) == 2 and selection_file.read_bytes() == before and window.busy is None
    with patch.object(app, "_restart_launcher", side_effect=OSError("Fixture cannot restart")):
        page.runtime_apply_button.emit("clicked")
    assert runtime.read_selection(selection_file)["runtime"] == "regular"
    assert "Runtime saved. Close and reopen" in errors[-1][-1] and window.busy is None
    assert core.DARLING_RUNTIME["runtime"] == "ciderdarling" and len(restarts) == 2
    runtime.save_selection(choices["ciderdarling"], selection_file, current=choices["regular"])
    before = selection_file.read_bytes()
    # A runtime removed after the menu was populated must be rechecked.
    Path(choices["regular"]["executable"]).unlink()
    page.runtime_apply_button.emit("clicked")
    assert "Install this runtime" in errors[-1][-1]
    assert len(restarts) == 2 and selection_file.read_bytes() == before and window.busy is None
    assert not page.runtime_apply_button.get_sensitive()

context, window = fixture()
with context:
    page = window.settings_page
    assert "not installed" in page.runtime_row.get_model().get_string(0)
    page.runtime_row.set_selected(0)
    assert not page.runtime_apply_button.get_sensitive()
    client = Path(choices["regular"]["executable"])
    client.write_text("#!/bin/sh\nexit 0\n"); client.chmod(0o755)
    page.runtime_refresh_button.emit("clicked")
    assert page.runtime_row.get_selected() == 0 and page.runtime_apply_button.get_sensitive()
    assert page.runtime_row.get_model().get_string(0) == "DarlingHQ's Darling"

with patch.dict(os.environ, FLATPAK_ID="org.ciderhq.Cider"):
    context, window = fixture("regular")
    with context:
        page = window.settings_page
        assert not page.runtime_row.get_sensitive() and not page.runtime_apply_button.get_visible()
        assert "bundled" in page.runtime_group.get_description()
        page.apply_runtime()
        assert len(restarts) == 2

with patch.object(app.os, "execve") as execute, patch.object(app.sys, "argv", ["launcher", "roblox:old-link"]):
    app._restart_launcher()
    command, arguments, environment = execute.call_args.args
    assert command == sys.executable
    assert arguments == [sys.executable, str(core.PROJECT / "launcher/ciderhq-launcher")]
    assert environment["MACOBLOX_PAGE"] == "settings" and "roblox:old-link" not in arguments

temporary.cleanup()
print("PASS: GTK switches both ways; custom prefixes persist; busy/game, missing runtimes, failed saves and Flatpak are protected; restart does not replay a URI")
