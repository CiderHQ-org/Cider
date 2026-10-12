import json
import os
from pathlib import Path
import shutil
import socket
import struct
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from macoblox import discord


class FakeDiscord:
    """A Discord IPC socket answering like arRPC; records each connection's
    activities (None for a clear) and whether it was closed."""

    def __init__(self, directory):
        self.connections = []
        self.lock = threading.Condition()
        self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server.bind(str(Path(directory) / "discord-ipc-0"))
        self.server.listen(4)
        threading.Thread(target=self._accept, daemon=True).start()

    def _accept(self):
        while True:
            try:
                client, _ = self.server.accept()
            except OSError:
                return
            record = {"activities": [], "closed": False}
            with self.lock:
                self.connections.append(record)
            threading.Thread(target=self._serve, args=(client, record), daemon=True).start()

    def _serve(self, client, record):
        def read(length):
            data = b""
            while len(data) < length:
                chunk = client.recv(length - len(data))
                if not chunk:
                    raise EOFError
                data += chunk
            return data

        def send(message):
            body = json.dumps(message).encode()
            client.sendall(struct.pack("<II", 1, len(body)) + body)

        try:
            while True:
                opcode, length = struct.unpack("<II", read(8))
                message = json.loads(read(length))
                if opcode == 0:
                    send({"cmd": "DISPATCH", "evt": "READY", "data": {"v": 1}, "nonce": None})
                    continue
                activity = message["args"].get("activity")
                send({"cmd": "SET_ACTIVITY", "data": activity, "evt": None, "nonce": message["nonce"]})
                with self.lock:
                    record["activities"].append(activity)
                    self.lock.notify_all()
        except (EOFError, OSError):
            pass
        finally:
            client.close()
            with self.lock:
                record["closed"] = True
                self.lock.notify_all()

    def wait(self, predicate, timeout=5):
        with self.lock:
            if not self.lock.wait_for(lambda: predicate(self.connections), timeout):
                raise AssertionError(f"timed out; connections: {self.connections}")

    def close(self):
        self.server.close()


class DiscordPresenceTests(unittest.TestCase):
    def setUp(self):
        # Unix socket paths are short; avoid long temporary directories.
        directory = tempfile.mkdtemp(prefix="cider-rpc-", dir="/tmp" if os.path.isdir("/tmp") else None)
        self.addCleanup(shutil.rmtree, directory, True)
        environment = patch.dict(os.environ, {"XDG_RUNTIME_DIR": directory, "TMPDIR": directory})
        environment.start()
        self.addCleanup(environment.stop)
        self.discord = FakeDiscord(directory)
        self.addCleanup(self.discord.close)
        pauses = patch.object(discord.DiscordRPC, "_CLEAR_AGAIN", (0.05, 0.05))
        pauses.start()
        self.addCleanup(pauses.stop)

    def start(self, **presence):
        rpc = discord.DiscordRPC()
        self.addCleanup(rpc._worker.join, 15)
        self.addCleanup(rpc.close)
        rpc.queue_presence(**presence)
        return rpc

    def test_clears_again_on_the_same_connection(self):
        rpc = self.start(details="In Main Menu")
        self.discord.wait(lambda c: c and c[0]["activities"])
        rpc.close()
        self.discord.wait(lambda c: c[0]["closed"])
        connection, = self.discord.connections
        self.assertEqual(connection["activities"][1:], [None, None, None])
        self.assertEqual(connection["activities"][0]["assets"]["large_image"], discord.LOGO)

    def test_newer_presence_stops_the_repeated_clears(self):
        with patch.object(discord.DiscordRPC, "_CLEAR_AGAIN", (0.3, 30.0)):
            old = self.start(details="Playing Roblox")
            self.discord.wait(lambda c: c and c[0]["activities"])
            old.close()
            self.discord.wait(lambda c: c[0]["activities"][-1] is None)
            self.start(details="In Main Menu")
            started = time.monotonic()
            self.discord.wait(lambda c: c[0]["closed"])
        self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(self.discord.connections[0]["activities"][1:], [None])

    def test_activity_branding_and_buttons(self):
        activity = discord.DiscordRPC._activity(
            details="Game", buttons=[("Game page", "https://www.roblox.com/games/1"),
                                     ("Get Cider", discord.WEBSITE_URL), ("Third", "https://example.com")])
        self.assertEqual(activity["assets"]["large_image"], discord.LOGO)
        self.assertEqual(activity["buttons"], [{"label": "Game page", "url": "https://www.roblox.com/games/1"},
                                               {"label": "Get Cider", "url": discord.WEBSITE_URL}])
        self.assertNotIn("buttons", discord.DiscordRPC._activity(details="Menu"))


if __name__ == "__main__":
    unittest.main()
