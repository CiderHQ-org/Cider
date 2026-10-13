import hashlib
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from macoblox import transport_patches as transport


class TransportPatchTests(unittest.TestCase):
    def setUp(self):
        self.planner = transport.plan_transport_patch
        self.data = b"executable:AB:CD:EF:tail"
        self.release = transport.Release(
            len(self.data), hashlib.sha256(self.data).hexdigest(),
            (transport.Site(11, b"AB", b"ab", "first"),
             transport.Site(14, b"CD", b"cd", "second")),
            (transport.Site(17, b"EF", b"ef", "other supported patch"),))

    def plan(self, data):
        return self.planner(data, (self.release,))

    def test_original_partial_and_already_patched_states(self):
        status, replacement = self.plan(self.data)
        self.assertEqual(status, "patched")
        self.assertEqual(replacement, b"executable:ab:cd:EF:tail")
        self.assertEqual(self.plan(bytes(replacement)), ("already patched", None))
        status, replacement = self.plan(b"executable:ab:CD:ef:tail")
        self.assertEqual(status, "patched")
        self.assertEqual(replacement, b"executable:ab:cd:ef:tail")

    def test_unknown_instruction_or_other_binary_change_rejects_all_sites(self):
        for data in (b"executable:AB:XX:EF:tail", b"executable:AB:CD:EF:fail", self.data + b"x"):
            with self.subTest(data=data):
                status, replacement = self.plan(data)
                self.assertTrue(status.startswith("unsupported"))
                self.assertIsNone(replacement)

    def test_atomic_application_preserves_execute_permission_and_verifies_again(self):
        with tempfile.TemporaryDirectory() as directory:
            binary = Path(directory) / "RobloxPlayer"
            binary.write_bytes(self.data)
            binary.chmod(0o755)
            with patch.object(transport, "plan_transport_patch", side_effect=self.plan):
                self.assertEqual(transport.apply_transport_patch(binary), "patched")
                self.assertEqual(transport.apply_transport_patch(binary), "already patched")
            self.assertEqual(binary.stat().st_mode & 0o777, 0o755)
            self.assertEqual(list(Path(directory).iterdir()), [binary])

    def test_current_release_sites_are_small_equal_length_replacements(self):
        for release in transport.RELEASES:
            for site in release.sites + release.compatible_changes:
                self.assertEqual(len(site.original), len(site.patched))
                self.assertTrue(0 <= site.offset < release.size - len(site.original))

    def test_near_dummy_branch_preserves_target_and_instruction_span(self):
        # 743 uses a six-byte conditional branch. Replacing it with a
        # five-byte JMP must adjust rel32 and pad the remaining byte.
        branches = [site for release in transport.RELEASES for site in release.sites
                    if site.original.startswith(b"\x0f\x85")]
        self.assertTrue(branches)
        for site in branches:
            with self.subTest(site=site.name):
                self.assertEqual(len(site.original), 6)
                self.assertEqual(site.patched[:1], b"\xe9")
                self.assertEqual(site.patched[5:], b"\x90")
                original_target = site.offset + 6 + struct.unpack("<i", site.original[2:])[0]
                patched_target = site.offset + 5 + struct.unpack("<i", site.patched[1:5])[0]
                self.assertEqual(patched_target, original_target)


if __name__ == "__main__":
    unittest.main()
