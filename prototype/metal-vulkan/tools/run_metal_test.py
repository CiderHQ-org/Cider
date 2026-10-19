"""Start Roblox from the repository's launcher, without saving settings.

run_metal_test.py <x11|wayland> <seconds> [renderer] [uri]
Runs the launcher's web bridge (Roblox's embedded pages) on a GLib main loop,
like the app; ends the session after <seconds> unless Roblox exits first.
"""
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "launcher"))
import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from macoblox import core, web  # noqa: E402

backend = sys.argv[1] if len(sys.argv) > 1 else "x11"
seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 60
renderer = sys.argv[3] if len(sys.argv) > 3 else "metal"
uri = sys.argv[4] if len(sys.argv) > 4 else None
settings = dict(core.load_settings())
settings.update(renderer=renderer, vr=False, mangohud=False, display_backend=backend,
                discord_rpc=False, hide_launcher_on_launch=False,
                diagnostic_signals=bool(int(__import__("os").environ.get("QM_DIAG", "0"))))

Gtk.init()
Adw.init()
loop = GLib.MainLoop()
bridge = web.WebBridge(None)
session = core.RobloxSession(settings, launch_uri=uri)
session.web_socket = bridge.guest_path
session.web_user_agent = bridge.user_agent
bridge.session = session


def run():
    try:
        session.start()
    except Exception as error:
        print("start failed:", error, flush=True)
        print("log", session.log_path, flush=True)
        GLib.idle_add(loop.quit)
        return
    print("log", session.log_path, flush=True)
    deadline = time.time() + seconds
    status = None
    while time.time() < deadline:
        status = session.poll()
        if status is not None:
            print("exited", status, flush=True)
            break
        time.sleep(1)
    if status is None:
        session.finish("test_done")
        print("finished by test", flush=True)
    GLib.idle_add(loop.quit)


threading.Thread(target=run, daemon=True).start()
loop.run()
bridge.stop()
