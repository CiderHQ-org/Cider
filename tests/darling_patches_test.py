import hashlib
from dataclasses import replace
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from quadra import darling_patches as darling


def digest(data):
    return hashlib.sha256(data).hexdigest()


def image_fixture():
    data = bytearray(900)
    struct.pack_into("<8I", data, 0, 0xFEEDFACF, 0x01000007, 3, 6, 2, 176, 0, 0)
    struct.pack_into("<II16sQQQQIIII", data, 32, 0x19, 152, b"__TEXT", 0, 900, 0, 900, 7, 5, 1, 0)
    struct.pack_into("<16s16sQQ8I", data, 104, b"__text", b"__TEXT", 0x1000, 512, 256, 4, 0, 0, 0, 0, 0, 0)
    names = b"\0_map_new\0_map_insert\0_map_foreach\0"
    struct.pack_into("<6I", data, 184, 2, 24, 768, 3, 816, len(names))
    data[816:816+len(names)] = names
    for index, (name, offset) in enumerate(((1, 0), (10, 128), (22, 384))):
        struct.pack_into("<IBBHQ", data, 768+16*index, name, 0x0F, 1, 0, 0x1000+offset)
    data[256:768] = bytes(index % 251 for index in range(512))
    return bytes(data)


def release_for(data):
    sites = (darling.Site("_map_new", 0, 4, digest(data[256:260]), b"new!"),
             darling.Site("_map_insert", 0, 8, digest(data[384:392]), b"insert"),
             darling.Site("_map_foreach", 0, 4, digest(data[640:644]), b"each"))
    repaired = bytearray(data)
    for offset, site in zip((256, 384, 640), sites):
        repaired[offset:offset+site.size] = site.replacement.ljust(site.size, b"\x90")
    return darling.Release(len(data), digest(data), digest(repaired), sites)


class DarlingPatchTests(unittest.TestCase):
    def setUp(self):
        self.data = image_fixture()
        self.release = release_for(self.data)
        planner = darling.plan_sparse_map_patch
        self.plan = lambda data: planner(data, (self.release,))

    def test_complete_known_and_idempotent(self):
        status, repaired = self.plan(self.data)
        self.assertEqual(status, "patched")
        self.assertIsInstance(repaired, bytes)
        self.assertEqual(digest(repaired), self.release.patched_sha256)
        self.assertEqual(self.plan(repaired), ("already patched", None))

    def test_unknown_partial_and_site_mismatch_skip(self):
        for offset in (0, 256, 257, 890):
            changed = bytearray(self.data)
            changed[offset] ^= 1
            self.assertIsNone(self.plan(changed)[1])
        bad = darling.Release(len(self.data), digest(self.data), "", (
            darling.Site("_map_new", 0, 4, digest(b"bad!"), b"new!"),))
        self.assertIsNone(darling.plan_sparse_map_patch(self.data, (bad,))[1])

    def test_layout_failures_skip_even_with_matching_whole_hash(self):
        for offset, value in ((4, 7), (12, 2), (20, 175), (36, 144), (200, 99999), (772, 0)):
            data = bytearray(self.data)
            struct.pack_into("<I", data, offset, value)
            release = darling.Release(len(data), digest(data), "", self.release.sites)
            self.assertIsNone(darling.plan_sparse_map_patch(data, (release,))[1])

    def test_universal_slice_validation(self):
        universal = bytearray(4096 + len(self.data))
        struct.pack_into(">7I", universal, 0, 0xCAFEBABE, 1, 0x01000007, 3, 4096, len(self.data), 12)
        universal[4096:] = self.data
        self.assertEqual(darling._x86_slice(universal), (4096, self.data))
        release = darling.Release(len(universal), digest(universal), "", self.release.sites)
        self.assertEqual(darling.plan_sparse_map_patch(universal, (release,))[0], "patched")
        struct.pack_into(">I", universal, 16, 4095)
        with self.assertRaises(ValueError): darling._x86_slice(universal)

    def test_overlap_and_final_digest_rejected(self):
        overlap = darling.Release(len(self.data), digest(self.data), "", self.release.sites * 2)
        wrong_digest = darling.Release(len(self.data), digest(self.data), "0"*64, self.release.sites)
        for release in (overlap, wrong_digest):
            self.assertIsNone(darling.plan_sparse_map_patch(self.data, (release,))[1])

    def test_atomic_copy_permissions_source_preserved_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            source, destination = Path(directory)/"stock", Path(directory)/"prefix/lib"
            source.write_bytes(self.data); source.chmod(0o755)
            with patch.object(darling, "plan_sparse_map_patch", side_effect=self.plan):
                self.assertEqual(darling.install_sparse_map_copy(source, destination), "patched")
                self.assertEqual(darling.install_sparse_map_copy(source, destination), "already patched")
            self.assertEqual(source.read_bytes(), self.data)
            self.assertEqual(destination.stat().st_mode & 0o777, 0o755)
            self.assertEqual(list(destination.parent.iterdir()), [destination])

    def test_patched_source_copies_to_missing_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            source, destination = Path(directory)/"stock", Path(directory)/"prefix/lib"
            repaired = self.plan(self.data)[1]
            source.write_bytes(repaired)
            with patch.object(darling, "plan_sparse_map_patch", side_effect=self.plan):
                self.assertEqual(darling.install_sparse_map_copy(source, destination), "already patched")
            self.assertEqual(destination.read_bytes(), repaired)

    def test_custom_override_symlink_and_source_alias_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            source, destination = Path(directory)/"stock", Path(directory)/"override"
            source.write_bytes(self.data); destination.write_bytes(b"custom")
            with patch.object(darling, "plan_sparse_map_patch", side_effect=self.plan):
                self.assertIn("custom", darling.install_sparse_map_copy(source, destination))
                destination.unlink(); destination.symlink_to(source)
                self.assertIn("left unchanged", darling.install_sparse_map_copy(source, destination))
                self.assertIn("coincide", darling.install_sparse_map_copy(source, source))
            self.assertEqual(source.read_bytes(), self.data)

    def test_failed_atomic_replace_cleans_temporary_and_preserves_override(self):
        with tempfile.TemporaryDirectory() as directory:
            source, destination = Path(directory)/"stock", Path(directory)/"prefix/lib"
            source.write_bytes(self.data)
            destination.parent.mkdir(); destination.write_bytes(self.data)
            with patch.object(darling, "plan_sparse_map_patch", side_effect=self.plan), patch.object(darling.os, "replace", side_effect=OSError("fixture")):
                with self.assertRaises(OSError): darling.install_sparse_map_copy(source, destination)
            self.assertEqual(destination.read_bytes(), self.data)
            self.assertEqual(list(destination.parent.iterdir()), [destination])

    def test_concurrent_override_change_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            source, destination = Path(directory)/"stock", Path(directory)/"prefix/lib"
            source.write_bytes(self.data)
            destination.parent.mkdir(); destination.write_bytes(self.data)
            def change_override(_): destination.write_bytes(b"concurrent custom override")
            with patch.object(darling, "plan_sparse_map_patch", side_effect=self.plan), patch.object(darling.os, "fsync", side_effect=change_override):
                with self.assertRaises(RuntimeError): darling.install_sparse_map_copy(source, destination)
            self.assertEqual(destination.read_bytes(), b"concurrent custom override")
            self.assertEqual(list(destination.parent.iterdir()), [destination])

    def test_known_installed_containers_preserve_other_architecture(self):
        for relative in ("usr/lib/libSystem.B.dylib", "usr/lib/system/libsystem_c.dylib"):
            source=Path("/usr/libexec/darling")/relative
            if not source.exists(): continue
            data=source.read_bytes()
            status, result=darling.plan_sparse_map_patch(data)
            if status.startswith("unsupported"): continue
            self.assertEqual(status, "patched")
            base, image=darling._x86_slice(data)
            self.assertEqual(result[:base], data[:base])
            self.assertEqual(result[base+len(image):], data[base+len(image):])
            self.assertEqual(darling.plan_sparse_map_patch(result), ("already patched", None))

    def test_other_known_original_or_repaired_library_is_preserved(self):
        other=bytearray(self.data); other[-1]^=1; other=bytes(other)
        other_release=release_for(other)
        planner=darling.plan_sparse_map_patch
        plan=lambda data: planner(data, (self.release, other_release))
        with tempfile.TemporaryDirectory() as directory:
            source, destination=Path(directory)/"stock", Path(directory)/"override"
            source.write_bytes(self.data)
            for state in (other, plan(other)[1]):
                destination.write_bytes(state)
                with patch.object(darling, "plan_sparse_map_patch", side_effect=plan):
                    self.assertIn("custom", darling.install_sparse_map_copy(source, destination))
                self.assertEqual(destination.read_bytes(), state)

    def test_library_path_restricts_original_and_repaired_recognition(self):
        release=replace(self.release, library="usr/lib/libSystem.B.dylib")
        result=darling.plan_sparse_map_patch(self.data, (release,))[1]
        for data in (self.data, result):
            self.assertIsNone(darling.plan_sparse_map_patch(data, (release,),
                library="usr/lib/system/libsystem_c.dylib")[1])
            self.assertTrue(darling.plan_sparse_map_patch(data, (release,),
                library="usr/lib/system/libsystem_c.dylib")[0].startswith("unsupported"))

    def test_assembler_matches_manifest_without_relocations(self):
        clang = shutil.which("clang")
        if not clang: self.skipTest("clang unavailable")
        root = Path(__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/"map.o"
            subprocess.run([clang, "-target", "x86_64-apple-darwin", "-c", str(root/"darling_sparse_map.S"), "-o", str(output)], check=True)
            data = output.read_bytes()
        count, = struct.unpack_from("<I", data, 16)
        position = 32
        text = None
        for _ in range(count):
            command, size = struct.unpack_from("<II", data, position)
            if command == 0x19:
                sections, = struct.unpack_from("<I", data, position+64)
                for index in range(sections):
                    start = position+72+80*index
                    if data[start:start+16].split(b"\0")[0] == b"__text":
                        length, offset, _, _, relocations = struct.unpack_from("<Q4I", data, start+40)
                        self.assertEqual(relocations, 0)
                        text = data[offset:offset+length]
            position += size
        self.assertIsNotNone(text)
        self.assertEqual(text[:0x145], darling.INSERT_CODE)
        self.assertEqual(text[0x150:0x150+0x7A], darling.FOREACH_CODE)
        self.assertEqual(darling.INSERT_CODE[:8], bytes.fromhex("554889e54883ec40"))
        self.assertEqual(darling.FOREACH_CODE[:8], bytes.fromhex("554889e54883ec20"))


if __name__ == "__main__": unittest.main()
