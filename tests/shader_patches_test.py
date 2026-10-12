import hashlib
import itertools
from pathlib import Path
import re
import struct
import tempfile
import unittest
from unittest.mock import patch

from macoblox import core, shader_patches as shaders


def fixture():
    """A synthetic RBXS pack; no client shader assets are stored in tests."""
    blobs = (
        b"#version 150\nuniform vec4 CB0[61];\nuniform vec4 MaterialLUT[256];\n"
        b"uniform vec4 ColorLUT[256];\nvoid main(){}\n",
        b"#version 150\n// a second feature variant\nuniform vec4 CB0[61];\n"
        b"uniform vec4 MaterialLUT[256];\nuniform vec4 ColorLUT[256];\nvoid main(){}\n",
    )
    prefix = (struct.pack("<4s6HI", b"RBXS", 11, 1, 0, 0, 1, 4, 0x12345678)
              + b"default".ljust(64, b"\0") + b"HeightmapDebugPS".ljust(68, b"\0"))
    start = len(prefix) + 4 * 64
    offsets = (start, start + len(blobs[0]))
    descriptors = []
    for index, source_index in enumerate((0, 0, 0, 1)):
        descriptors.append(bytes([index + 1]) * 16 + struct.pack(
            "<IIIBBH", offsets[source_index], len(blobs[source_index]), 0, ord("p"), 0, 0)
            + bytes(32))
    data = prefix + b"".join(descriptors) + b"".join(blobs)
    sources = tuple(shaders.Source(
        offsets[index], len(blob), hashlib.sha256(blob).hexdigest(),
        (0, 1, 2) if index == 0 else (3,),
        tuple(blob.index(declaration) + 7 for declaration in (
            b"uniform vec4 MaterialLUT[256];", b"uniform vec4 ColorLUT[256];")))
        for index, blob in enumerate(blobs))
    return data, shaders.Release(len(data), hashlib.sha256(data).hexdigest(), sources)


def client_parser(source):
    """Reproduce the inspected literal scan and CB sscanf contract."""
    output = []
    position = 0
    while True:
        start = source.find(b"uniform vec4", position)
        if start < 0:
            return b"".join(output) + source[position:]
        end = source.find(b";", start)
        declaration = source[start:end + 1]
        match = re.fullmatch(rb"uniform vec4 CB(\d+)\s*\[\s*(\d+)\];", declaration)
        if not match:
            raise ValueError("failed to parse uniforms in a shader")
        cb, size = match.groups()
        output.extend((source[position:start], b"layout(std140) uniform block_CB" + cb
                       + b" { vec4 CB" + cb + b"[" + size + b"]; }"))
        # The client carries the original semicolon into its next slice.
        position = end


class ShaderPatchTests(unittest.TestCase):
    def setUp(self):
        self.planner = shaders.plan_shader_patch
        self.data, self.release = fixture()
        self.positions = [source.offset + site for source in self.release.sources for site in source.sites]

    def plan(self, data):
        return self.planner(data, (self.release,))

    def test_all_original_partial_and_patched_states(self):
        expected = bytearray(self.data)
        for position in self.positions:
            expected[position] = ord("\t")
        for changes in itertools.product((False, True), repeat=4):
            data = bytearray(self.data)
            for changed, position in zip(changes, self.positions):
                if changed:
                    data[position] = ord("\t")
            status, replacement = self.plan(data)
            if all(changes):
                self.assertEqual((status, replacement), ("already patched", None))
            else:
                self.assertEqual((status, replacement), ("patched", expected))

    def test_preserves_glsl_tokens_and_named_arrays_and_repairs_cpu_parser(self):
        _, replacement = self.plan(self.data)
        self.assertEqual(len(replacement), len(self.data))
        self.assertEqual([index for index, (a, b) in enumerate(zip(self.data, replacement)) if a != b],
                         self.positions)
        for source in self.release.sources:
            original = self.data[source.offset:source.offset + source.size]
            repaired = bytes(replacement[source.offset:source.offset + source.size])
            self.assertEqual(re.findall(rb"\S+", original), re.findall(rb"\S+", repaired))
            with self.assertRaisesRegex(ValueError, "failed to parse uniforms"):
                client_parser(original)
            rewritten = client_parser(repaired)
            self.assertIn(b"layout(std140) uniform block_CB0 { vec4 CB0[61]; };", rewritten)
            self.assertIn(b"uniform\tvec4 MaterialLUT[256];", rewritten)
            self.assertIn(b"uniform\tvec4 ColorLUT[256];", rewritten)

    def test_unsupported_modification_or_size_rejects_every_change(self):
        cases = [self.data + b"x", self.data[:-1]]
        for position in (0, 16, len(self.data) - 4, *self.positions):
            changed = bytearray(self.data)
            changed[position] = ord("X")
            cases.append(changed)
        for data in cases:
            status, replacement = self.plan(data)
            self.assertTrue(status.startswith("unsupported"))
            self.assertIsNone(replacement)

    def test_layout_rejects_invalid_source_range_name_variant_and_shared_reference(self):
        table = 20 + 64 + 68
        for offset, value in ((4, b"\x0a\x00"), (table + 16, struct.pack("<I", 1)),
                              (table + 20, struct.pack("<I", 0)), (table + 28, b"x"),
                              (table + 29, b"\x01"), (table + 30, b"\x01\x00"),
                              (84, b"X")):
            data = bytearray(self.data)
            data[offset:offset + len(value)] = value
            release = shaders.Release(len(data), hashlib.sha256(data).hexdigest(), self.release.sources)
            self.assertIsNone(shaders.plan_shader_patch(data, (release,))[1])

    def test_atomic_write_preserves_permissions_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            pack = Path(directory) / "shaders_glsl3.pack"
            pack.write_bytes(self.data)
            pack.chmod(0o640)
            with patch.object(shaders, "plan_shader_patch", side_effect=self.plan):
                self.assertEqual(shaders.apply_shader_patch(pack), "patched")
                self.assertEqual(shaders.apply_shader_patch(pack), "already patched")
            self.assertEqual(pack.stat().st_mode & 0o777, 0o640)
            self.assertEqual(list(Path(directory).iterdir()), [pack])

    def test_concurrent_update_is_not_overwritten_and_temporary_is_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            pack = Path(directory) / "shaders_glsl3.pack"
            pack.write_bytes(self.data)
            newer = self.data + b"updated"
            with patch.object(shaders, "plan_shader_patch", side_effect=self.plan), \
                    patch.object(shaders.os, "fsync", side_effect=lambda _: pack.write_bytes(newer)):
                with self.assertRaisesRegex(RuntimeError, "shader pack changed"):
                    shaders.apply_shader_patch(pack)
            self.assertEqual(pack.read_bytes(), newer)
            self.assertEqual(list(Path(directory).iterdir()), [pack])

    def test_known_manifest_only_changes_four_whitespace_bytes(self):
        self.assertEqual(len(shaders.RELEASES), 2)
        self.assertEqual(len({release.sha256 for release in shaders.RELEASES}), 2)
        for release in shaders.RELEASES:
            with self.subTest(size=release.size):
                self.assertEqual(sum(len(source.sites) for source in release.sources), 4)
                self.assertEqual(tuple(len(source.descriptors) for source in release.sources), (3, 1))
                self.assertTrue(all(0 < source.offset < source.offset + source.size <= release.size
                                    for source in release.sources))

    def test_launch_hook_applies_supported_pack_and_leaves_unknown_pack(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "client.app"
            pack = bundle / "Contents" / "Resources" / "shaders" / "shaders_glsl3.pack"
            pack.parent.mkdir(parents=True)
            pack.write_bytes(self.data)
            with patch.object(core, "APP_BUNDLE", bundle), \
                    patch.object(shaders, "plan_shader_patch", side_effect=self.plan):
                core.ensure_shader_compatibility()
                self.assertEqual(self.plan(pack.read_bytes()), ("already patched", None))
                unknown = self.data + b"modded pack"
                pack.write_bytes(unknown)
                with self.assertLogs("macoblox", level="WARNING") as log:
                    core.ensure_shader_compatibility()
                self.assertIn("unsupported shader pack", log.output[0])
                self.assertEqual(pack.read_bytes(), unknown)

    def test_launch_hook_tolerates_missing_pack_and_reports_write_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "client.app"
            pack = bundle / "Contents" / "Resources" / "shaders" / "shaders_glsl3.pack"
            with patch.object(core, "APP_BUNDLE", bundle), \
                    patch.object(shaders, "apply_shader_patch", side_effect=OSError("write failed")) as apply:
                core.ensure_shader_compatibility()
                apply.assert_not_called()
                pack.parent.mkdir(parents=True)
                pack.touch()
                with self.assertLogs("macoblox", level="WARNING") as log:
                    core.ensure_shader_compatibility()
                self.assertIn("write failed", log.output[0])


if __name__ == "__main__":
    unittest.main()
