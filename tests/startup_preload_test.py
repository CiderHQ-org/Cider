"""Authored pack/layout, local-file and memory budget tests; no client inputs."""
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from quadra import startup_preload


def library(payload=b"authored"):
    size = 88 + len(payload)
    return b"MTLB" + bytes(12) + struct.pack("<9Q", size, 88, len(payload), 0, 0, 0, 0, 0, 0) + payload


def shader_pack(payloads):
    """Own RBXS table with one variant/name and arbitrary authored wrapped libraries."""
    header = struct.pack("<4s6HI", b"RBXS", 11, 1, 0, 0, 1, len(payloads), 0)
    table = bytearray(len(payloads) * 64)
    position = len(header) + 64 + 68 + len(table)
    for index, payload in enumerate(payloads):
        struct.pack_into("<II", table, index * 64 + 16, position, len(payload))
        struct.pack_into("<BBH", table, index * 64 + 28, ord("v"), 0, 0)
        position += len(payload)
    return header + bytes(64 + 68) + table + b"".join(payloads)


class StartupPreloadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_wrapped_libraries_are_deduplicated_without_guessing_render_states(self):
        first, second = library(), library(b"other authored data")
        pack = self.root / "shaders.pack"
        pack.write_bytes(shader_pack([b"wrapper" + first, b"other wrapper" + first, second]))
        prepared, progress = [], []
        result = startup_preload.prepare_libraries(pack, lambda data: prepared.append(data) or True,
                                                  lambda *row: progress.append(row))
        self.assertEqual(prepared, [first, second])
        self.assertEqual(result["prepared"], 2)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(progress[-1], (3, 3, 0))

    def test_bad_payload_is_nonfatal_and_later_valid_library_is_prepared(self):
        pack = self.root / "shaders.pack"
        pack.write_bytes(shader_pack([b"MTLB" + bytes(84), library()]))
        result = startup_preload.prepare_libraries(pack, lambda data: True, lambda *row: None)
        self.assertEqual((result["status"], result["failed"], result["prepared"]), ("partial", 1, 1))

    def test_out_of_bounds_and_overlapping_pack_tables_are_rejected_before_loading(self):
        for target in (0, 2**32 - 1):
            data = bytearray(shader_pack([library()]))
            struct.pack_into("<I", data, 20 + 64 + 68 + 16, target)
            pack = self.root / "bad.pack"
            pack.write_bytes(data)
            with self.assertRaises(ValueError):
                startup_preload.prepare_libraries(pack, lambda data: self.fail("must not load"), lambda *row: None)
        pack.write_bytes(b"RBXS")
        with self.assertRaises(ValueError):
            startup_preload.prepare_libraries(pack, lambda data: False, lambda *row: None)
        data = bytearray(shader_pack([library(), library(b"second")]))
        first_offset = struct.unpack_from("<I", data, 20 + 64 + 68 + 16)[0]
        struct.pack_into("<I", data, 20 + 64 + 68 + 64 + 16, first_offset + 1)
        pack.write_bytes(data)
        with self.assertRaises(ValueError):
            startup_preload.prepare_libraries(pack, lambda data: False, lambda *row: None)

    def test_resource_warming_obeys_byte_and_time_bounds_and_skips_links(self):
        content = self.root / "content"
        content.mkdir()
        (content / "font.ttf").write_bytes(b"own font" * 1024)
        (content / "image.png").write_bytes(b"own image" * 1024)
        (content / "settings.json").write_text("not an asset")
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "hidden.ttf").write_bytes(b"not part of content")
        (content / "linked").symlink_to(outside, target_is_directory=True)
        (content / "linked.ttf").symlink_to(outside / "hidden.ttf")
        before = {p: p.read_bytes() for p in content.iterdir() if p.is_file() and not p.is_symlink()}
        with patch.object(startup_preload, "available_memory", return_value=8 << 30):
            result = startup_preload.warm_resources(self.root, lambda *row: None, maximum=32)
            self.assertEqual(result["read_bytes"], 32)
            self.assertEqual(result["status"], "limited")
            zero = startup_preload.warm_resources(self.root, lambda *row: None, seconds=0)
            self.assertEqual(zero["read_bytes"], 0)
        self.assertEqual(len(startup_preload.resource_files(self.root)), 2)
        self.assertEqual(before, {p: p.read_bytes() for p in before})

    def test_resource_warming_rejects_fifo_without_blocking_and_preserves_memory_headroom(self):
        content = self.root / "content"
        content.mkdir()
        os.mkfifo(content / "not-a-font.ttf")
        self.assertEqual(startup_preload.resource_files(self.root), [])
        with self.assertRaises(ValueError):
            startup_preload._open_regular(content / "not-a-font.ttf")
        self.assertEqual(startup_preload.resource_budget(None), 32 << 20)
        self.assertEqual(startup_preload.resource_budget(768 << 20), 0)
        self.assertEqual(startup_preload.resource_budget(1 << 30), 64 << 20)
        self.assertEqual(startup_preload.resource_budget(8 << 30), 128 << 20)


if __name__ == "__main__":
    unittest.main()
