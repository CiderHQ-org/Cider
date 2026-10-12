import os
import ast
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from macoblox import core, display, graphics
from session_fixture import bare_session


class DisplayTests(unittest.TestCase):
    def test_dpi_default_and_valid_scales(self):
        self.assertEqual(core.DEFAULT_SETTINGS["dpi_scale"], 1.0)
        self.assertIsInstance(core.DEFAULT_SETTINGS["dpi_scale"], float)
        for value in (1, 1.125, 1.25, 2.0, 3.75, 4):
            with self.subTest(value=value):
                self.assertEqual(display.validated_dpi_scale(value), float(value))

    def test_dpi_invalid_scales_use_default(self):
        for value in (None, True, False, "2", [], {}, float("nan"),
                      float("inf"), float("-inf"), .99, 4.01, -2, 10**1000):
            with self.subTest(value=repr(value)):
                self.assertEqual(display.validated_dpi_scale(value), 1.0)

    def test_stored_dpi_scale_is_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            settings_file = Path(directory) / "settings.json"
            with patch.object(core, "SETTINGS_FILE", settings_file):
                for value in (1.25, 4, True, "2", float("nan"), float("inf"),
                              .99, 4.01, 10**1000):
                    with self.subTest(value=repr(value)):
                        settings_file.write_text(json.dumps({"dpi_scale": value}))
                        self.assertEqual(core.load_settings()["dpi_scale"],
                                         display.validated_dpi_scale(value))

    def test_dpi_scale_reaches_guest_on_both_backends(self):
        session = bare_session()
        session.web_socket = session.dns = session.audio = None
        for backend in ("x11", "wayland"):
            with self.subTest(backend=backend):
                session.settings = dict(core.DEFAULT_SETTINGS, display_backend=backend, dpi_scale=1.25)
                with patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-0"}, clear=True), \
                        patch.object(display.Path, "is_file", return_value=True), \
                        patch.object(core, "host_vram_bytes", return_value=0), \
                        patch.object(core, "icon_argb_file", side_effect=OSError):
                    guest = dict(item.split("=", 1) for item in session.shim_variables())
                    host = session.environment()
                self.assertEqual(guest["MACOBLOX_DPI_SCALE"], "1.250")
                self.assertNotIn("GDK_SCALE", host)
                self.assertNotIn("QT_SCALE_FACTOR", host)

    def test_direct_invalid_dpi_is_sanitized_before_guest_export(self):
        session = bare_session()
        session.web_socket = session.dns = session.audio = None
        session.settings = dict(core.DEFAULT_SETTINGS, dpi_scale=float("nan"))
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(core, "host_vram_bytes", return_value=0), \
                patch.object(core, "icon_argb_file", side_effect=OSError):
            guest = dict(item.split("=", 1) for item in session.shim_variables())
        self.assertEqual(guest["MACOBLOX_DPI_SCALE"], "1.000")

    def test_texture_preset_does_not_disable_dpi(self):
        tree = ast.parse((core.PROJECT / "launcher/macoblox/app.py").read_text())
        presets = next(ast.literal_eval(node.value) for node in tree.body
                       if isinstance(node, ast.Assign) and any(
                           isinstance(target, ast.Name) and target.id == "PRESETS"
                           for target in node.targets))
        texture = next(preset for preset in presets if preset["title"] == "Texture quality override")
        self.assertNotIn("DFFlagDisableDPIScale", texture["also"])

    def test_manual_dpi_fast_flag_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            flags = Path(directory) / "flags.json"
            flags.write_text(json.dumps({"DFFlagDisableDPIScale": True}))
            with patch.object(core, "FAST_FLAGS", flags):
                self.assertEqual(core.load_fast_flags(), {"DFFlagDisableDPIScale": True})
                self.assertEqual(json.loads(flags.read_text()), {"DFFlagDisableDPIScale": True})

    def test_default_keeps_x11(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(display.window_environment({}, Path("missing")),
                             {"MACOBLOX_WAYLAND": "0", "EGL_PLATFORM": "x11"})
            self.assertEqual(core.DEFAULT_SETTINGS["display_backend"], "x11")

    def test_wayland_requires_session_and_helper(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "Wayland desktop"):
                display.window_environment({"display_backend": "wayland"}, Path("missing"))
        with patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-0"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "helper is missing"):
                display.window_environment({"display_backend": "wayland"}, Path("missing"))

    def test_opt_in_changes_host_and_guest_platform(self):
        with tempfile.TemporaryDirectory() as directory:
            helper = Path(directory) / "helper.so"
            helper.touch()
            with patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-0", "MACOBLOX_WAYLAND": "1"}, clear=True):
                values = display.window_environment({}, helper)
                self.assertEqual(values["EGL_PLATFORM"], "wayland")
                self.assertEqual(values["MACOBLOX_WAYLAND_HELPER"], str(helper))

    def test_unknown_backend_is_rejected(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                display.window_environment({"display_backend": "invalid"}, Path("missing"))

    def test_nvidia_icd_is_scoped_to_native_wayland_vulkan(self):
        with tempfile.TemporaryDirectory() as directory:
            helper = Path(directory) / "helper.so"
            helper.touch()
            with patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-0"}, clear=True), \
                    patch.object(graphics, "wayland_vulkan_environment", return_value={"VK_ADD_DRIVER_FILES": "/cache/egl.json"}) as drivers:
                for settings in ({}, {"renderer": "vulkan"}, {"display_backend": "wayland"}):
                    display.window_environment(settings, helper)
                drivers.assert_not_called()
                values = display.window_environment({"display_backend": "wayland", "renderer": "vulkan"}, helper)
                self.assertEqual(values["VK_ADD_DRIVER_FILES"], "/cache/egl.json")
                drivers.assert_called_once()

    def test_native_wayland_driver_configuration_reaches_host_and_guest(self):
        session = bare_session()
        session.settings = dict(core.DEFAULT_SETTINGS, display_backend="wayland", renderer="vulkan")
        session.web_socket = session.dns = session.audio = None
        with patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-0"}, clear=True), \
                patch.object(display.Path, "is_file", return_value=True), \
                patch.object(graphics, "wayland_vulkan_environment", return_value={"VK_ADD_DRIVER_FILES": "/cache/egl.json"}), \
                patch.object(core, "host_vram_bytes", return_value=0), \
                patch.object(core, "icon_argb_file", side_effect=OSError):
            host = session.environment()
            guest = dict(item.split("=", 1) for item in session.shim_variables())
        self.assertEqual(host["VK_ADD_DRIVER_FILES"], "/cache/egl.json")
        self.assertEqual(guest["VK_ADD_DRIVER_FILES"], host["VK_ADD_DRIVER_FILES"])
        self.assertEqual(host["EGL_PLATFORM"], "wayland")
        self.assertEqual(guest["EGL_PLATFORM"], "wayland")
