"""Feral GameMode for Studio's Wine process. No GTK window code; Gio is only the D-Bus client."""
import logging
import os

log = logging.getLogger(__name__)

NAME = "com.feralinteractive.GameMode"
PATH = "/com/feralinteractive/GameMode"


def register(pid, gio=None):
    """Asks the GameMode daemon to optimise process `pid` while it lives (the
    daemon drops it when it exits). True when the daemon accepted it; False
    when GameMode is not installed or running, which is not an error."""
    try:
        if gio is None:
            import gi
            gi.require_version("Gio", "2.0")
            from gi.repository import Gio, GLib
        else:
            Gio, GLib = gio
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        reply = bus.call_sync(NAME, PATH, NAME, "RegisterGameByPID", GLib.Variant("(ii)", (os.getpid(), pid)),
                              GLib.VariantType("(i)"), Gio.DBusCallFlags.NONE, 2000, None)
        result = reply.unpack()[0]
    except Exception as error:  # no gi, no session bus, no GameMode: Studio runs without it
        log.info("GameMode is not available: %s", error)
        return False
    if result != 0:
        log.info("GameMode refused process %s (%s)", pid, result)
    return result == 0
