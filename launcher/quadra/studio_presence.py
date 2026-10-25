"""Discord Rich Presence for Studio, read from Studio's own log. No GTK.

Studio writes what it is doing to Wine's debug output (see studio._wine_env).
Two lines matter: the place that was opened and the kind of document in front.
The same lines arrive more than once (Wine reports each debug string through
several channels), so only a change in what is shown is sent."""
import logging
import re
import threading
import time

from . import discord
from .i18n import _

PLACE = re.compile(r"\[FLog::CloseDataModel\] Setting place ID (\d+)")
DOCUMENT = re.compile(r"\[FLog::RobloxDocManager\] Setting current doc to type (-?\d+)")
# Document types Studio reports: none open, a place, a script.
NONE, PLACE_DOCUMENT, SCRIPT = "-1", "0", "2"

log = logging.getLogger(__name__)


class StudioPresence:
    def __init__(self, rpc, fetch=discord.fetch_game_info, clock=time.time):
        self.rpc, self.fetch, self.clock = rpc, fetch, clock
        self.place_id = None
        self.info = None
        self.document = None  # not reported yet: the first report is always shown
        self.started = clock()
        self.sent = None
        self.lock = threading.Lock()

    def feed(self, line):
        """One line of Studio's output. Never blocks on the network."""
        match = PLACE.search(line)
        if match:
            self._open_place(int(match[1]))
            return
        match = DOCUMENT.search(line)
        if match and match[1] in (NONE, PLACE_DOCUMENT, SCRIPT):
            with self.lock:
                if match[1] == self.document:
                    return
                if match[1] == NONE:
                    self.place_id, self.info, self.started = None, None, self.clock()
                self.document = match[1]
            self._publish()

    def _open_place(self, place_id):
        with self.lock:
            if place_id == self.place_id:
                return
            self.place_id, self.info, self.started = place_id, None, self.clock()
        threading.Thread(target=self._resolve, args=(place_id,), name="quadra-studio-place", daemon=True).start()

    def _resolve(self, place_id):
        try:
            info = self.fetch(place_id)
        except Exception as error:
            log.debug("Could not look up place %s: %s", place_id, error)
            info = None
        with self.lock:
            if place_id != self.place_id:
                return
            self.info = info
            showing_a_document = self.document not in (None, NONE)
        if showing_a_document:
            self._publish()

    def activity(self):
        with self.lock:
            document, info, started = self.document, self.info, self.started
        if document in (None, NONE):
            return {"details": _("Idling"), "state": None, "large_image": discord.LOGO}
        name = info["name"] if info and info.get("name") else None
        activity = {
            "details": _("Developing {name}", name=name) if name else _("Developing a place"),
            "state": _("Editing a script") if document == SCRIPT else None,
            "large_image": (info or {}).get("icon_url") or discord.LOGO,
        }
        return activity | {"start_time": started}

    def _publish(self):
        activity = self.activity()
        activity.setdefault("start_time", self.started)
        with self.lock:
            if activity == self.sent:
                return
            self.sent = activity
        self.rpc.queue_presence(large_text="Quadra Studio", **activity)

    def close(self, wait=12.0):
        """Clear the presence and give the connection's worker time to do it."""
        self.rpc.close()
        worker = getattr(self.rpc, "_worker", None)
        if worker is not None:
            worker.join(wait)
