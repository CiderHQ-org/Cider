"""Run: PYTHONPATH=launcher python3 -m unittest discover -s tests -p '*_test.py'."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from quadra import core, vr


def manifest(directory, name, library):
    path = Path(directory) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"file_format_version": "1.0.0",
                                "runtime": {"name": name.split(".")[0], "library_path": library}}))
    return path


class RuntimeDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.library = self.root / "libruntime.so"
        self.library.write_bytes(b"")
        self.known = patch.object(vr, "KNOWN_RUNTIMES", ())
        self.known.start()

    def tearDown(self):
        self.known.stop()
        self.directory.cleanup()

    def environ(self, **values):
        base = {"XDG_CONFIG_HOME": str(self.root / "config"), "XDG_CONFIG_DIRS": str(self.root / "xdg")}
        base.update(values)
        return base

    def test_follows_the_loader_order(self):
        user = manifest(self.root / "config/openxr/1", "active_runtime.json", str(self.library))
        system = manifest(self.root / "xdg/openxr/1", "active_runtime.json", str(self.library))
        explicit = manifest(self.root, "explicit.json", str(self.library))
        self.assertEqual(vr.active_runtime(self.environ(XR_RUNTIME_JSON=str(explicit)), self.root),
                         explicit.resolve())
        self.assertEqual(vr.active_runtime(self.environ(), self.root), user.resolve())
        user.unlink()
        self.assertEqual(vr.active_runtime(self.environ(), self.root), system.resolve())

    def test_skips_manifests_whose_library_is_missing_and_resolves_relative_paths(self):
        manifest(self.root / "config/openxr/1", "active_runtime.json", str(self.root / "missing.so"))
        relative = manifest(self.root / "xdg/openxr/1", "active_runtime.json", "../../../libruntime.so")
        self.assertEqual(vr.active_runtime(self.environ(), self.root), relative.resolve())

    def test_symlinked_active_runtime_resolves_to_the_runtime_manifest(self):
        target = manifest(self.root / "share", "openxr_wivrn.json", str(self.library))
        link = self.root / "config/openxr/1/active_runtime.json"
        link.parent.mkdir(parents=True)
        link.symlink_to(target)
        self.assertEqual(vr.active_runtime(self.environ(), self.root), target.resolve())
        self.assertEqual(vr.runtime_name(target), "openxr_wivrn")

    def test_known_runtime_is_the_last_resort(self):
        wivrn = manifest(self.root / "share", "openxr_wivrn.json", str(self.library))
        with patch.object(vr, "KNOWN_RUNTIMES", (str(self.root / "missing.json"), str(wivrn))):
            self.assertEqual(vr.active_runtime(self.environ(), self.root), wivrn.resolve())
        self.assertIsNone(vr.active_runtime(self.environ(), self.root))

    def test_damaged_manifests_are_ignored(self):
        broken = self.root / "config/openxr/1/active_runtime.json"
        broken.parent.mkdir(parents=True)
        for text in ("not json", "[]", '{"runtime": {}}', '{"runtime": {"library_path": 3}}'):
            with self.subTest(text=text):
                broken.write_text(text)
                self.assertIsNone(vr.active_runtime(self.environ(), self.root))


class ShimVariableTests(unittest.TestCase):
    def test_off_by_default(self):
        self.assertFalse(core.DEFAULT_SETTINGS["vr"])
        self.assertEqual(vr.shim_variables(dict(core.DEFAULT_SETTINGS)), ([], "VR: off"))

    def test_enabled_passes_mode_scale_and_runtime(self):
        runtime = Path("/runtimes/openxr_wivrn.json")
        with patch.object(vr, "loader_installed", return_value=True), \
                patch.object(vr, "active_runtime", return_value=runtime), \
                patch.object(vr, "runtime_name", return_value="WiVRn"):
            variables, line = vr.shim_variables({"vr": True, "vr_render_scale": 85, "vr_mirror": False})
        self.assertEqual(variables, ["QUADRA_VR=openxr-headset", "QUADRA_VR_SCALE=85",
                                     f"QUADRA_XR_RUNTIME_JSON={runtime}"])
        self.assertIn("WiVRn", line)
        self.assertIn("headset only", line)

    def test_enabled_without_runtime_launches_on_the_desktop(self):
        with patch.object(vr, "loader_installed", return_value=True), \
                patch.object(vr, "active_runtime", return_value=None):
            variables, line = vr.shim_variables({"vr": True})
        self.assertEqual(variables, [])
        self.assertIn("no OpenXR", line)
        with patch.object(vr, "loader_installed", return_value=False):
            self.assertEqual(vr.shim_variables({"vr": True})[0], [])

    def test_render_scale_is_clamped(self):
        for value, expected in ((70, 70), (10, 40), (500, 150), ("85", 85), ("bad", 70), (None, 70), (72.6, 72)):
            with self.subTest(value=value):
                self.assertEqual(vr.validated_render_scale(value), expected)


if __name__ == "__main__":
    unittest.main()
