"""Observe the selected game transport in this launch's log, without GTK."""

import os
import re


_SELECTION = re.compile(
    rb"^[^\[\r\n]*\[(?:DFLog|FLog)::NetworkClient\][ \t]+Transport selection:"
    rb"[^\r\n]*\bselectedTransport=([A-Za-z][A-Za-z0-9_-]{0,31})(?=[,\s]|$)"
)


class TransportMonitor:
    # Read incrementally on the existing session worker, independently of
    # Discord presence and the visible log tab. Bound work and partial lines.
    READ_SIZE = 64 * 1024
    READS_PER_POLL = 4
    LINE_LIMIT = 8192

    def __init__(self):
        self.selected_transport = None
        self._identity = None
        self._position = 0
        self._fragment = b""
        self._discarding_line = False

    @property
    def warning_transport(self):
        selected = self.selected_transport
        return selected if selected and selected != "RakNet" else None

    def poll(self, log_path):
        if log_path is None:
            return
        try:
            with open(log_path, "rb") as source:
                status = os.fstat(source.fileno())
                identity = (status.st_dev, status.st_ino)
                if identity != self._identity or status.st_size < self._position:
                    self._identity = identity
                    self._position = 0
                    self._fragment = b""
                    self._discarding_line = False
                    self.selected_transport = None
                source.seek(self._position)
                for _ in range(self.READS_PER_POLL):
                    chunk = source.read(self.READ_SIZE)
                    if not chunk:
                        break
                    self._position += len(chunk)
                    if self._discarding_line:
                        end = chunk.find(b"\n")
                        if end < 0:
                            continue
                        chunk = chunk[end + 1:]
                        self._discarding_line = False
                    lines = (self._fragment + chunk).split(b"\n")
                    self._fragment = lines.pop()
                    for line in lines:
                        if len(line) <= self.LINE_LIMIT:
                            match = _SELECTION.search(line)
                            if match:
                                self.selected_transport = match[1].decode("ascii")
                    if len(self._fragment) > self.LINE_LIMIT:
                        self._fragment = b""
                        self._discarding_line = True
        except OSError:
            # A missing or temporarily unreadable log is not transport evidence
            # and must not interrupt an otherwise running game.
            pass
