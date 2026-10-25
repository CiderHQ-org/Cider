"""Browser join links expire; the file format stays what the shim reads."""
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from quadra import uri


class PendingUriTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        base = Path(self.temporary.name)
        for name, value in (("CACHE_DIR", base), ("PENDING_URI", base / "pending-uri"),
                            ("LAST_URI", base / "last-uri.txt"), ("PENDING_LOCK", base / "pending-uri.lock")):
            context = patch.object(uri, name, value)
            context.start()
            self.addCleanup(context.stop)

    def age(self, seconds):
        stamp = time.time() - seconds
        os.utime(uri.PENDING_URI, (stamp, stamp))

    def test_fresh_link_is_kept_raw(self):
        link = "roblox-player:1+launchmode:play+gameinfo:secret+placelauncherurl:x%20y"
        uri.receive(link)
        self.age(uri.PENDING_MAX_AGE - 30)
        self.assertEqual(uri.peek_pending(), link)
        self.assertEqual(uri.PENDING_URI.read_bytes(), os.fsencode(link))
        self.assertFalse(uri.expire_pending())

    def test_old_and_future_links_are_deleted(self):
        for seconds in (uri.PENDING_MAX_AGE + 1, -3600):
            with self.subTest(age=seconds):
                uri.receive("roblox-player:1")
                self.age(seconds)
                self.assertIsNone(uri.peek_pending())
                self.assertFalse(uri.PENDING_URI.exists())
        # The record of the last link is not a pending launch and stays.
        self.assertTrue(uri.LAST_URI.exists())

    def test_missing_file_is_not_an_error(self):
        self.assertFalse(uri.expire_pending())
        self.assertIsNone(uri.peek_pending())


if __name__ == "__main__":
    unittest.main()
