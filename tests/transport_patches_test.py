import hashlib
import itertools
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from quadra import transport_patches as transport


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

    def test_near_branches_accept_all_patch_states_and_reject_changed_targets(self):
        # 743 uses six-byte branches: a redirected early jump and a removed
        # late jump. Partial instruction edits must reject the whole plan.
        early = bytes.fromhex("0f85e1010000")
        late = bytes.fromhex("0f8480010000")
        data = b"header" + early + late + b"tail"
        sites = (transport.Site(6, early, bytes.fromhex("e94d02000090"), "early"),
                 transport.Site(12, late, b"\x90" * 6, "late"))
        release = transport.Release(len(data), hashlib.sha256(data).hexdigest(), sites)
        expected = b"header" + sites[0].patched + sites[1].patched + b"tail"
        for states in itertools.product((False, True), repeat=2):
            candidate = bytearray(data)
            for applied, site in zip(states, sites):
                if applied:
                    candidate[site.offset:site.offset + len(site.patched)] = site.patched
            result = self.planner(candidate, (release,))
            self.assertEqual(result, ("already patched", None) if all(states)
                             else ("patched", expected))
        for site in sites:
            candidate = bytearray(data)
            candidate[site.offset + 2] ^= 1  # Changed branch displacement.
            self.assertTrue(self.planner(candidate, (release,))[0].startswith("unsupported"))
            self.assertIsNone(self.planner(candidate, (release,))[1])
            candidate = bytearray(data)
            candidate[site.offset:site.offset + 2] = site.patched[:2]
            self.assertIsNone(self.planner(candidate, (release,))[1])

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


if __name__ == "__main__":
    unittest.main()
