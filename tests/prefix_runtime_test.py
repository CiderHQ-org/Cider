import hashlib
import json
import tempfile
from dataclasses import replace
import unittest
from pathlib import Path
from unittest.mock import patch

from quadra import core, darling_patches
from darling_patches_test import image_fixture, release_for


class PrefixRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        base = Path(self.temporary.name)
        self.prefix = base / "prefix"
        self.sysroot = base / "sysroot"
        self.native = base / "build" / "native"
        self.relative = Path("usr/lib/system/libsystem_c.dylib")
        self.stock = self.sysroot / self.relative
        self.stock.parent.mkdir(parents=True)
        self.stock.write_bytes(b"stock")
        self.stamps = base / "cache" / "prefix-libraries.json"
        for name, value in (("DARLING_PREFIX", self.prefix),
                            ("DARLING_SYSROOT", self.sysroot),
                            ("NATIVE_BUILD", self.native),
                            ("PREFIX_STAMPS", self.stamps),
                            ("NOROOT_LIB", None)):
            context = patch.object(core, name, value)
            context.start()
            self.addCleanup(context.stop)

    def recorded(self):
        try:
            return json.loads(self.stamps.read_text())[str(self.prefix.resolve())]
        except FileNotFoundError:
            return {}

    @staticmethod
    def digest(data):
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def planner(stock, repaired):
        """A pinned release: `stock` is repaired to `repaired`."""
        def plan(data, **_):
            if data == stock:
                return "patched", repaired
            if data == repaired:
                return "already patched", None
            return "unsupported Darling library; left unchanged", None
        return plan

    def stage(self, source, destination, *, library):
        status, replacement = darling_patches.plan_sparse_map_patch(source.read_bytes(), library=library)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes() if replacement is None else replacement)
        return status

    def prepare(self, libraries):
        with patch.object(core, "_missing_frameworks", return_value=[]), \
                patch.object(core, "_patched_ffmpeg_bridges", return_value=[]), \
                patch.object(core, "_patched_kqueue_runtime", return_value=libraries), \
                patch.object(core, "darlingserver_running", return_value=False):
            return core.prepare_prefix({})

    def test_unknown_stock_is_preserved(self):
        with patch.object(darling_patches, "install_sparse_map_copy") as install:
            self.assertEqual(core._patched_kqueue_runtime(), [])
            install.assert_not_called()
        self.assertEqual(self.stock.read_bytes(), b"stock")

    def test_existing_unknown_prefix_override_wins_over_stock(self):
        installed = self.prefix / self.relative
        installed.parent.mkdir(parents=True)
        installed.write_bytes(b"custom")
        with patch.object(darling_patches, "plan_sparse_map_patch",
                          return_value=("unsupported", None)) as plan:
            self.assertEqual(core._patched_kqueue_runtime(), [])
            plan.assert_called_once_with(b"custom", library=self.relative.as_posix())
        self.assertEqual(installed.read_bytes(), b"custom")

    def test_known_repaired_prefix_needs_no_restart(self):
        installed = self.prefix / self.relative
        installed.parent.mkdir(parents=True)
        installed.write_bytes(b"repaired")
        with patch.object(darling_patches, "plan_sparse_map_patch",
                          side_effect=self.planner(b"stock", b"repaired")), \
                patch.object(darling_patches, "install_sparse_map_copy") as install:
            self.assertEqual(core._patched_kqueue_runtime(), [])
            install.assert_not_called()
        # A copy from before the records is adopted with its runtime's hash.
        self.assertEqual(self.recorded(), {self.relative.as_posix(): {
            "source": self.digest(b"stock"), "installed": self.digest(b"repaired")}})

    def test_runtime_update_restages_the_launchers_copy(self):
        installed = self.prefix / self.relative
        installed.parent.mkdir(parents=True)
        installed.write_bytes(b"old repaired")
        core._record_prefix_stamps({self.relative.as_posix(): {
            "source": self.digest(b"old stock"), "installed": self.digest(b"old repaired")}})
        self.stock.write_bytes(b"new stock")
        with patch.object(darling_patches, "plan_sparse_map_patch",
                          side_effect=self.planner(b"new stock", b"new repaired")), \
                patch.object(darling_patches, "install_sparse_map_copy", side_effect=self.stage):
            libraries = core._patched_kqueue_runtime()
            self.assertEqual(libraries, [(self.relative, self.native / "libsystem_c.dylib")])
            self.assertEqual(self.prepare(libraries), [])
        self.assertEqual(installed.read_bytes(), b"new repaired")
        self.assertEqual(self.recorded()[self.relative.as_posix()],
                         {"source": self.digest(b"new stock"), "installed": self.digest(b"new repaired")})

    def test_unrepairable_runtime_update_uncovers_the_runtime_file(self):
        installed = self.prefix / self.relative
        installed.parent.mkdir(parents=True)
        installed.write_bytes(b"old repaired")
        self.stock.write_bytes(b"fixed upstream")
        # Recognized as this launcher's repair without a record (older releases).
        with patch.object(darling_patches, "plan_sparse_map_patch",
                          side_effect=self.planner(b"old stock", b"old repaired")):
            libraries = core._patched_kqueue_runtime()
            self.assertEqual(libraries, [(self.relative, None)])
            self.prepare(libraries)
        self.assertFalse(installed.exists())  # the overlay shows the runtime's file
        self.assertNotIn(self.relative.as_posix(), self.recorded())
        # A rootless prefix is a full copy of one runtime: its own repaired
        # copy stays, rather than mixing in one file from a newer runtime.
        installed.write_bytes(b"old repaired")
        with patch.object(core, "NOROOT_LIB", "/fixture/noroot.so"), \
                patch.object(darling_patches, "plan_sparse_map_patch",
                             side_effect=self.planner(b"old stock", b"old repaired")):
            self.prepare(core._patched_kqueue_runtime())
        self.assertEqual(installed.read_bytes(), b"old repaired")

    def test_unknown_overrides_are_reported_and_kept(self):
        custom = self.prefix / "usr/lib/system/libsystem_m.dylib"
        custom.parent.mkdir(parents=True)
        custom.write_bytes(b"hand placed")
        (self.sysroot / "usr/lib/system/libsystem_m.dylib").write_bytes(b"runtime")
        own = self.prefix / self.relative
        own.write_bytes(b"repaired")
        core._record_prefix_stamps({self.relative.as_posix(): {
            "source": self.digest(b"stock"), "installed": self.digest(b"repaired")}})
        (self.prefix / "usr/lib/system/only-in-prefix.dylib").write_bytes(b"not shadowing")
        with self.assertLogs("quadra", level="WARNING"):
            notes = self.prepare([])
        self.assertEqual(len(notes), 1)
        self.assertIn("usr/lib/system/libsystem_m.dylib", notes[0])
        self.assertNotIn(self.relative.as_posix(), notes[0])
        self.assertNotIn("only-in-prefix", notes[0])
        self.assertEqual(custom.read_bytes(), b"hand placed")
        with patch.object(core, "NOROOT_LIB", "/fixture/noroot.so"):
            self.assertEqual(core._unknown_prefix_overrides(), [])

    def test_ffmpeg_bridge_copy_follows_the_runtime(self):
        relative = Path("usr/lib/native/libavcodec.dylib")
        source, installed = self.sysroot / relative, self.prefix / relative
        source.parent.mkdir(parents=True)
        source.write_bytes(b"\x55new bridge libavcodec.so.61")
        installed.parent.mkdir(parents=True)
        installed.write_bytes(b"\xc3old bridge libavcodec.so.60")  # an older release's copy
        patches = (patch.object(core, "NATIVE_LIBS", [relative.as_posix()]),
                   patch.object(core, "_initializer_offset", return_value=0),
                   patch.object(core, "_host_libraries", return_value=set()))
        for context in patches:
            context.start()
            self.addCleanup(context.stop)
        bridges = core._patched_ffmpeg_bridges()
        self.assertEqual(bridges, [(relative, self.native / "libavcodec.dylib")])
        self.assertEqual(bridges[0][1].read_bytes(), b"\xc3new bridge libavcodec.so.61")
        with patch.object(core, "_missing_frameworks", return_value=[]), \
                patch.object(core, "_patched_kqueue_runtime", return_value=[]), \
                patch.object(core, "_patched_ffmpeg_bridges", return_value=bridges), \
                patch.object(core, "darlingserver_running", return_value=False):
            core.prepare_prefix({})
        self.assertEqual(installed.read_bytes(), b"\xc3new bridge libavcodec.so.61")
        self.assertEqual(core._patched_ffmpeg_bridges(), [])
        # The host now has the library: the runtime's own bridge works again.
        with patch.object(core, "_host_libraries", return_value={"libavcodec.so.61"}):
            self.assertEqual(core._patched_ffmpeg_bridges(), [(relative, None)])
        # A bridge someone else put there stays.
        installed.write_bytes(b"\x55custom bridge libavcodec.so.61")
        self.assertEqual(core._patched_ffmpeg_bridges(), [])

    def test_library_symlinks_and_parent_escape_are_preserved(self):
        self.prefix.mkdir()
        (self.prefix / "usr").symlink_to(self.sysroot / "usr", target_is_directory=True)
        with patch.object(darling_patches, "plan_sparse_map_patch") as plan:
            self.assertEqual(core._patched_kqueue_runtime(), [])
            plan.assert_not_called()

    def test_stage_is_validated_and_installed_through_atomic_copy_helper(self):
        def stage(source, destination, *, library):
            self.assertEqual(source, self.stock)
            self.assertEqual(library, self.relative.as_posix())
            destination.parent.mkdir(parents=True)
            destination.write_bytes(b"repaired")
            return "patched"

        with patch.object(darling_patches, "plan_sparse_map_patch",
                          side_effect=lambda data, **_: ("patched", b"repaired") if data == b"stock"
                          else ("already patched", None)), \
                patch.object(darling_patches, "install_sparse_map_copy", side_effect=stage):
            libraries = core._patched_kqueue_runtime()
        self.assertEqual(libraries, [(self.relative, self.native / "libsystem_c.dylib")])
        self.prefix.mkdir()
        with patch.object(core, "_missing_frameworks", return_value=[]), \
                patch.object(core, "_patched_ffmpeg_bridges", return_value=[]), \
                patch.object(core, "_patched_kqueue_runtime", return_value=libraries), \
                patch.object(core, "darlingserver_running", return_value=False), \
                patch.object(core, "restart_darling") as restart, \
                patch.object(darling_patches, "install_sparse_map_copy", return_value="patched") as install:
            core.prepare_prefix({})
            install.assert_called_once_with(libraries[0][1], self.prefix / self.relative,
                                           library=self.relative.as_posix())
            restart.assert_not_called()

    def test_both_independent_kqueue_libraries_are_staged(self):
        base_library = self.sysroot / "usr/lib/libSystem.B.dylib"
        base_library.parent.mkdir(parents=True, exist_ok=True)
        base_library.write_bytes(b"stock")

        def stage(source, destination, *, library):
            self.assertIn(source, (base_library, self.stock))
            self.assertEqual(source.name, destination.name)
            self.assertEqual(library, source.relative_to(self.sysroot).as_posix())
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"repaired")
            return "patched"

        with patch.object(darling_patches, "plan_sparse_map_patch",
                          side_effect=lambda data, **_: ("patched", b"repaired") if data == b"stock"
                          else ("already patched", None)), \
                patch.object(darling_patches, "install_sparse_map_copy", side_effect=stage):
            libraries = core._patched_kqueue_runtime()
        self.assertEqual(libraries, [
            (Path("usr/lib/libSystem.B.dylib"), self.native / "libSystem.B.dylib"),
            (self.relative, self.native / "libsystem_c.dylib"),
        ])

    def test_wrong_family_staged_and_installed_libraries_are_preserved(self):
        data=image_fixture()
        other=bytearray(data); other[-1]^=1; other=bytes(other)
        release=replace(release_for(data), library=self.relative.as_posix())
        other_release=replace(release_for(other), library="usr/lib/libSystem.B.dylib")
        planner=darling_patches.plan_sparse_map_patch
        def plan(value, *, library=None):
            return planner(value, (release, other_release), library=library)
        self.stock.write_bytes(data)
        staged=self.native/self.relative.name
        staged.parent.mkdir(parents=True)
        wrong=plan(other)[1]
        staged.write_bytes(wrong)
        with patch.object(darling_patches, "plan_sparse_map_patch", side_effect=plan):
            self.assertEqual(core._patched_kqueue_runtime(), [])
        self.assertEqual(staged.read_bytes(), wrong)
        installed=self.prefix/self.relative
        installed.parent.mkdir(parents=True)
        for state in (other, wrong):
            installed.write_bytes(state)
            with patch.object(darling_patches, "plan_sparse_map_patch", side_effect=plan):
                self.assertEqual(core._patched_kqueue_runtime(), [])
            self.assertEqual(installed.read_bytes(), state)
        self.assertEqual(self.stock.read_bytes(), data)
