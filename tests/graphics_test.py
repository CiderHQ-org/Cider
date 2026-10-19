"""Run: PYTHONPATH=launcher python3 -m unittest discover -s tests -p '*_test.py'."""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from macoblox import core, graphics
from session_fixture import bare_session


class GraphicsTests(unittest.TestCase):
    def test_gpu_budget_uses_selected_adapter_and_current_free_memory(self):
        output = "NVIDIA GeForce RTX 3060 Ti, 8192, 4096\nNVIDIA Other, 24576, 20000\n"
        with patch.object(core.Path, "glob", return_value=[]), \
                patch.object(core.subprocess, "check_output", return_value=output):
            self.assertEqual(core.host_vram_bytes("zink (NVIDIA GeForce RTX 3060 Ti)"),
                             (4096 - 256) * 1024 * 1024)
            self.assertEqual(core.host_vram_bytes(), (4096 - 256) * 1024 * 1024)
            self.assertEqual(core.host_vram_bytes("NVIDIA Other"), 24576 * 1024 * 1024 * 3 // 4)

    def test_gpu_budget_fallback_is_conservative_and_bad_reports_are_ignored(self):
        for output in ("", "bad driver output", "GPU, 8192, 9000", "GPU, 8192, -1"):
            with self.subTest(output=output), patch.object(core.Path, "glob", return_value=[]), \
                    patch.object(core.subprocess, "check_output", return_value=output):
                self.assertEqual(core.host_vram_bytes(), 512 * 1024 * 1024)

    def test_vulkan_dependency_check_identifies_each_missing_component(self):
        with patch.object(graphics, "mesa_egl_manifest", return_value=None), \
                patch.object(graphics.Path, "is_file", return_value=False):
            self.assertEqual(graphics.missing_vulkan_dependencies(), ["Mesa EGL", "Zink"])
        with patch.object(graphics, "mesa_egl_manifest", return_value="/mesa.json"), \
                patch.object(graphics.Path, "is_file", return_value=False):
            self.assertEqual(graphics.missing_vulkan_dependencies(), ["Zink"])

    def test_dependency_install_skips_authentication_when_already_installed(self):
        with patch.object(graphics, "missing_vulkan_dependencies", return_value=[]), \
                patch.object(graphics.subprocess, "run") as run:
            self.assertFalse(graphics.ensure_vulkan_dependencies())
            run.assert_not_called()

    def test_installer_uses_run0_authentication_without_a_shell(self):
        releases = (("arch", "pacman", "mesa"), ("ubuntu", "apt-get", "libgl1-mesa-dri"),
                    ("fedora", "dnf", "mesa-dri-drivers"))
        for distro, manager, package in releases:
            with self.subTest(distro=distro), \
                    patch.object(graphics.Path, "is_file", return_value=False), \
                    patch.object(graphics.platform, "freedesktop_os_release", return_value={"ID": distro}), \
                    patch.object(graphics, "_system_program", side_effect=lambda cmd: "/usr/bin/" + cmd):
                command, environment = graphics.vulkan_install_command()
                self.assertEqual(environment, {})
                self.assertEqual(command[0], "/usr/bin/run0")
                self.assertEqual(command[3], "/usr/bin/" + manager)
                self.assertIn(package, command)
                self.assertNotIn("--no-ask-password", command)
                self.assertNotIn("-Sy", command)
                self.assertNotIn("sh", command)

    def test_installer_rechecks_files_and_reports_cancelled_authentication(self):
        with patch.object(graphics, "missing_vulkan_dependencies", side_effect=[["Zink"], []]), \
                patch.object(graphics, "vulkan_install_command", return_value=(["run0", "package-manager"], {})), \
                patch.object(graphics.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")):
            self.assertTrue(graphics.ensure_vulkan_dependencies())
        for backend in ("run0", "pkexec", "sudo", "terminal"):
            with self.subTest(backend=backend), \
                    patch.object(graphics, "missing_vulkan_dependencies", return_value=["Zink"]) as missing, \
                    patch.object(graphics, "vulkan_install_command", return_value=([backend, "package-manager"], {})) as plan, \
                    patch.object(graphics.subprocess, "run", return_value=subprocess.CompletedProcess([], 126, "", "Not authorized")) as run:
                with self.assertRaisesRegex(RuntimeError, "Authentication may have been cancelled"):
                    graphics.ensure_vulkan_dependencies()
                plan.assert_called_once()
                run.assert_called_once()
                missing.assert_called_once()
        with patch.object(graphics, "missing_vulkan_dependencies", return_value=["Zink"]), \
                patch.object(graphics, "vulkan_install_command", return_value=(["terminal", "package-manager"], {})), \
                patch.object(graphics.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")):
            with self.assertRaisesRegex(RuntimeError, "still missing: Zink"):
                graphics.ensure_vulkan_dependencies()

    def test_installer_reports_no_prompt_and_keeps_flatpak_in_its_runtime(self):
        with patch.object(graphics.Path, "is_file", return_value=False), \
                patch.object(graphics.platform, "freedesktop_os_release", return_value={"ID": "arch"}), \
                patch.object(graphics, "_system_program", side_effect=lambda cmd: "/usr/bin/pacman" if cmd == "pacman" else None):
            with self.assertRaisesRegex(RuntimeError, "No administrator prompt is available"):
                graphics.vulkan_install_command()
        with patch.object(graphics.Path, "is_file", return_value=True), \
                patch.object(graphics, "_system_program") as system_program:
            with self.assertRaisesRegex(RuntimeError, "Flatpak graphics runtime"):
                graphics.vulkan_install_command()
            system_program.assert_not_called()

    def test_pkexec_fallback_does_not_try_other_prompts(self):
        with patch.object(graphics, "_system_program", side_effect=lambda cmd: None if cmd == "run0" else "/usr/bin/" + cmd) as program, \
                patch.object(graphics, "_askpass_program") as askpass:
            command, environment = graphics._authenticated_install_command(["/usr/bin/pacman", "-S", "mesa"])
        self.assertEqual(command, ["/usr/bin/pkexec", "/usr/bin/pacman", "-S", "mesa"])
        self.assertEqual(environment, {})
        self.assertEqual([call.args[0] for call in program.call_args_list], ["run0", "pkexec"])
        askpass.assert_not_called()

    def test_sudo_graphical_fallback_passes_helper_without_changing_process_environment(self):
        with patch.object(graphics, "_system_program", side_effect=lambda cmd: "/usr/bin/sudo" if cmd == "sudo" else None), \
                patch.object(graphics, "_askpass_program", return_value="/usr/bin/ksshaskpass"), \
                patch.dict(graphics.os.environ, {"DISPLAY": ":123"}, clear=True), \
                patch.object(graphics, "missing_vulkan_dependencies", side_effect=[["Zink"], []]), \
                patch.object(graphics.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")) as run:
            command, environment = graphics._authenticated_install_command(["/usr/bin/pacman", "-S", "mesa"])
            self.assertEqual(command, ["/usr/bin/sudo", "-A", "--", "/usr/bin/pacman", "-S", "mesa"])
            with patch.object(graphics, "vulkan_install_command", return_value=(command, environment)):
                self.assertTrue(graphics.ensure_vulkan_dependencies())
            self.assertEqual(run.call_args.kwargs["env"], {"DISPLAY": ":123", "SUDO_ASKPASS": "/usr/bin/ksshaskpass"})
            self.assertNotIn("SUDO_ASKPASS", graphics.os.environ)
            self.assertNotIn("shell", run.call_args.kwargs)

    def test_terminal_fallbacks_wait_and_preserve_argument_boundaries(self):
        terminals = (("gnome-terminal", ["--wait", "--"]), ("konsole", ["--separate", "-e"]),
                     ("xfce4-terminal", ["--disable-server", "--execute"]), ("kitty", ["--"]),
                     ("alacritty", ["-e"]), ("foot", ["--"]), ("xterm", ["-e"]))
        package_command = ["/usr/bin/apt-get", "install", "libegl-mesa0", "libgl1-mesa-dri"]
        for terminal, arguments in terminals:
            with self.subTest(terminal=terminal), \
                    patch.object(graphics, "_system_program", side_effect=lambda cmd: "/usr/bin/" + cmd if cmd in ("sudo", terminal) else None), \
                    patch.object(graphics, "_askpass_program", return_value=None):
                command, environment = graphics._authenticated_install_command(package_command)
            self.assertEqual(command, ["/usr/bin/" + terminal, *arguments, "/usr/bin/sudo", "--", *package_command])
            self.assertEqual(environment, {})

    def test_askpass_detects_configured_and_installed_executable_helpers(self):
        with patch.dict(graphics.os.environ, {"SUDO_ASKPASS": "/custom/password helper"}, clear=True), \
                patch.object(graphics.Path, "is_file", return_value=True), \
                patch.object(graphics.os, "access", return_value=True), \
                patch.object(graphics, "_system_program") as program:
            self.assertEqual(graphics._askpass_program(), "/custom/password helper")
            program.assert_not_called()
        with patch.dict(graphics.os.environ, {}, clear=True), \
                patch.object(graphics, "_system_program", return_value=None), \
                patch.object(graphics.Path, "is_file", return_value=False):
            self.assertIsNone(graphics._askpass_program())
        with patch.dict(graphics.os.environ, {"SUDO_ASKPASS": "/not-executable"}, clear=True), \
                patch.object(graphics, "_system_program", return_value=None), \
                patch.object(graphics.Path, "is_file", return_value=True), \
                patch.object(graphics.os, "access", return_value=False):
            self.assertIsNone(graphics._askpass_program())
        with patch.dict(graphics.os.environ, {}, clear=True), \
                patch.object(graphics, "_system_program", return_value=None), \
                patch.object(graphics.Path, "is_file", autospec=True,
                             side_effect=lambda path: str(path) == "/usr/lib/gcr4-ssh-askpass"), \
                patch.object(graphics.os, "access", return_value=True):
            self.assertEqual(graphics._askpass_program(), "/usr/lib/gcr4-ssh-askpass")

    def test_default_preserves_host_driver_selection(self):
        self.assertEqual(graphics.renderer_environment("opengl"), {})
        self.assertEqual(core.DEFAULT_SETTINGS["renderer"], "opengl")

    def test_metal_paths_reach_both_host_and_guest_without_changing_egl(self):
        session = bare_session(dict(core.DEFAULT_SETTINGS, renderer="metal"))
        session.web_socket = session.dns = session.audio = None
        with patch.dict(os.environ, {}, clear=True), \
                patch.object(core, "METAL_DIR", Path("/build with spaces/metal")), \
                patch.object(core, "host_vram_bytes", return_value=0), \
                patch.object(core, "icon_argb_file", side_effect=OSError):
            host = session.environment()
            guest = dict(item.split("=", 1) for item in session.shim_variables())
        self.assertEqual(host["MACOBLOX_METAL"], "1")
        self.assertEqual(guest["MACOBLOX_METAL_HOST_LIBRARY"], host["MACOBLOX_METAL_HOST_LIBRARY"])
        self.assertEqual(guest["MACOBLOX_METAL_FRAMEWORKS"], "/Volumes/SystemRoot/build with spaces/metal")
        self.assertNotIn("MESA_LOADER_DRIVER_OVERRIDE", host)
        self.assertNotIn("MESA_LOADER_DRIVER_OVERRIDE", guest)

    def test_renderer_switch_clears_previous_darling_metal_framework(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            application = root / "RobloxPlayer.app/Contents/MacOS/RobloxPlayer"
            application.parent.mkdir(parents=True)
            application.write_text('#!/bin/sh\nprintf "%s\\n" "${MACOBLOX_METAL:-off}" "${DYLD_FRAMEWORK_PATH:-unset}"\n')
            application.chmod(0o755)
            inherited = {**os.environ, "MACOBLOX_METAL": "1",
                         "MACOBLOX_METAL_FRAMEWORKS": "/previous/metal", "DYLD_FRAMEWORK_PATH": "/previous/metal"}
            for variables, expected in (([], ["off", "unset"]),
                    (["MACOBLOX_METAL=1", "MACOBLOX_METAL_FRAMEWORKS=/new path/metal"], ["1", "/new path/metal"])):
                result = subprocess.run(["bash", "--noprofile", "--norc", "-c", core.LAUNCH_SCRIPT,
                                         "test", str(root), "/shim", "", *variables],
                                        env=inherited, capture_output=True, text=True, check=True)
                self.assertEqual(result.stdout.splitlines(), expected)

    def test_metal_probe_refuses_software_and_reports_device_errors(self):
        for record, status, message in (({"device": "llvmpipe"}, 0, "software Vulkan device"),
                                         ({"error": "missing swapchain extension"}, 1, "missing swapchain extension")):
            with self.subTest(record=record), patch.object(graphics.subprocess, "run",
                    return_value=subprocess.CompletedProcess([], status, json.dumps(record), "")):
                with self.assertRaisesRegex(RuntimeError, message):
                    graphics.validate_metal({}, "/metal.so")

    def test_wayland_nvidia_adds_egl_icd_and_reuses_atomic_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "nvidia_icd.json"
            egl = root / "libEGL_nvidia.so.0"
            egl.touch()
            original = {"file_format_version": "1.0.1", "ICD":
                        {"library_path": str(root / "libGLX_nvidia.so.0"), "api_version": "1.4.351"}}
            source.write_text(json.dumps(original))
            with patch.dict(os.environ, {"XDG_CACHE_HOME": str(root / "cache")}, clear=True), \
                    patch.object(graphics.Path, "glob", autospec=True,
                                 side_effect=lambda path, pattern: [source] if pattern == "*.json" else []):
                first = graphics.wayland_vulkan_environment()
                target = Path(first["VK_ADD_DRIVER_FILES"])
                before = target.stat().st_mtime_ns
                self.assertEqual(graphics.wayland_vulkan_environment(), first)
                self.assertEqual(target.stat().st_mtime_ns, before)
            self.assertEqual(json.loads(source.read_text()), original)
            self.assertEqual(json.loads(target.read_text()),
                             {**original, "ICD": {**original["ICD"], "library_path": str(egl.resolve())}})
            self.assertTrue(target.is_absolute())
            self.assertEqual(target.name, source.name)
            self.assertEqual(list(target.parent.glob(".nvidia-egl-*")), [])
            self.assertNotIn("VK_DRIVER_FILES", first)
            self.assertNotIn("VK_ICD_FILENAMES", first)

    def test_wayland_vulkan_keeps_all_explicit_driver_overrides(self):
        for name in ("VK_DRIVER_FILES", "VK_ICD_FILENAMES", "VK_ADD_DRIVER_FILES"):
            for value in ("/custom/driver.json", ""):
                with self.subTest(name=name, value=value), \
                        patch.dict(os.environ, {name: value}, clear=True), \
                        patch.object(graphics.Path, "glob") as glob:
                    self.assertEqual(graphics.wayland_vulkan_environment(), {name: value})
                    glob.assert_not_called()

    def test_wayland_nvidia_finds_xdg_manifest_and_preserves_driver_filters(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "config/vulkan/icd.d/custom_nvidia.json"
            source.parent.mkdir(parents=True)
            egl = root / "libEGL_nvidia.so.0"
            egl.touch()
            source.write_text(json.dumps({"ICD": {"library_path": str(root / "libGLX_nvidia.so.0")}}))
            original_glob = Path.glob
            values = {"XDG_CONFIG_HOME": str(root / "config"), "XDG_CACHE_HOME": str(root / "cache"),
                      "VK_LOADER_DRIVERS_SELECT": source.name, "VK_LOADER_DRIVERS_DISABLE": "*intel*"}
            with patch.dict(os.environ, values, clear=True), \
                    patch.object(graphics.Path, "glob", autospec=True,
                                 side_effect=lambda path, pattern: original_glob(path, pattern) if path.is_relative_to(root) else []):
                env = graphics.wayland_vulkan_environment()
            self.assertEqual(Path(env["VK_ADD_DRIVER_FILES"]).name, source.name)
            self.assertEqual(env["VK_LOADER_DRIVERS_SELECT"], source.name)
            self.assertEqual(env["VK_LOADER_DRIVERS_DISABLE"], "*intel*")

    def test_wayland_vulkan_ignores_non_glx_or_unusable_nvidia_manifests(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "nvidia_icd.json"
            cases = ("bad json", '[]', '{"ICD": {"library_path": null}}',
                     '{"ICD": {"library_path": "libEGL_nvidia.so.0"}}',
                     json.dumps({"ICD": {"library_path": str(Path(directory) / "libGLX_nvidia.so.0")}}))
            for contents in cases:
                source.write_text(contents)
                with self.subTest(contents=contents), patch.dict(os.environ, {}, clear=True), \
                        patch.object(graphics.Path, "glob", autospec=True,
                                     side_effect=lambda path, pattern: [source] if pattern == "*.json" else []):
                    self.assertEqual(graphics.wayland_vulkan_environment(), {})

    def test_vulkan_selects_mesa_egl_and_keeps_metal_disabled(self):
        with patch.object(graphics.Path, "is_file", return_value=True):
            env = graphics.renderer_environment("vulkan")
        self.assertEqual(env["MESA_LOADER_DRIVER_OVERRIDE"], "zink")
        self.assertEqual(env["MACOBLOX_METAL"], "0")
        self.assertEqual(env["EGL_PLATFORM"], "x11")
        self.assertTrue(env["__EGL_VENDOR_LIBRARY_FILENAMES"].endswith("50_mesa.json"))

    def test_missing_mesa_is_actionable(self):
        with patch.object(graphics.Path, "is_file", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "Install them or select OpenGL"):
                graphics.renderer_environment("vulkan")

    def test_software_fallback_is_rejected(self):
        for name in ("llvmpipe", "zink Vulkan (lavapipe)", "zink Vulkan (llvmpipe)",
                     "NVIDIA GeForce RTX 5070 Ti"):
            with self.subTest(name=name), patch.object(graphics.subprocess, "run", return_value=
                    subprocess.CompletedProcess([], 0, json.dumps({"renderer": name}))):
                with self.assertRaisesRegex(RuntimeError, "Select OpenGL"):
                    graphics.validate_vulkan({})

    def test_hardware_and_driver_failure(self):
        name = "zink Vulkan 1.4 (NVIDIA GeForce RTX 5070 Ti)"
        with patch.object(graphics.subprocess, "run", return_value=
                          subprocess.CompletedProcess([], 0, json.dumps({"renderer": name}))):
            self.assertEqual(graphics.validate_vulkan({}), name)
        for result in (subprocess.CompletedProcess([], -11, ""),
                       subprocess.CompletedProcess([], 1, '{"error":"no X11 display"}')):
            with patch.object(graphics.subprocess, "run", return_value=result):
                with self.assertRaisesRegex(RuntimeError, "Select OpenGL"):
                    graphics.validate_vulkan({})
        with patch.object(graphics.subprocess, "run", side_effect=subprocess.TimeoutExpired([], 20)):
            with self.assertRaisesRegex(RuntimeError, "Select OpenGL"):
                graphics.validate_vulkan({})

    def test_renderer_reaches_guest_and_nvidia_cache_uses_host_path(self):
        session = bare_session()
        # The Settings switch turns the overlay on; its configuration from the
        # launcher's environment then reaches the guest unchanged.
        session.settings = dict(core.DEFAULT_SETTINGS, renderer="vulkan", mangohud=True)
        session.web_socket = session.dns = session.audio = None
        with patch.object(graphics.Path, "is_file", return_value=True), \
                patch.object(core, "host_vram_bytes", return_value=0), \
                patch.dict(core.os.environ, {"MANGOHUD": "1", "MANGOHUD_CONFIG": "fps,frametime,gpu_name", "MANGOHUD_CONFIGFILE": "/tmp/hud config.conf"}), \
                patch.object(core, "icon_argb_file", side_effect=OSError):
            env = dict(item.split("=", 1) for item in session.shim_variables())
        self.assertEqual(env["MESA_LOADER_DRIVER_OVERRIDE"], "zink")
        self.assertEqual(env["MACOBLOX_METAL"], "0")
        self.assertEqual(env["__GL_SHADER_DISK_CACHE_PATH"], str(core.CACHE_DIR / "nvidia-shader-cache"))
        self.assertEqual(env["MANGOHUD"], "1")
        self.assertEqual(env["MANGOHUD_CONFIG"], "fps,frametime,gpu_name")
        self.assertEqual(env["MANGOHUD_CONFIGFILE"], "/tmp/hud config.conf")

    def test_mangohud_disabled_by_default(self):
        # Off is explicit: an overlay inherited from the desktop or an earlier
        # Darling session must not turn itself on.
        self.assertFalse(core.DEFAULT_SETTINGS["mangohud"])
        off = {"MANGOHUD": "0", "MACOBLOX_MANGOHUD_OPENGL": ""}
        for inherited in ({}, {"MANGOHUD": "1", "MANGOHUD_CONFIG": "fps"}):
            with self.subTest(inherited=inherited), patch.dict(graphics.os.environ, inherited, clear=True):
                self.assertEqual(graphics.mangohud_environment("opengl"), off)
                self.assertEqual(graphics.mangohud_environment("vulkan"), off)

    def test_mangohud_opengl_uses_bridge_and_preserves_settings(self):
        settings = {"MANGOHUD": "0", "MANGOHUD_CONFIG": "fps,frametime",
                    "MANGOHUD_CONFIGFILE": "/tmp/hud config.conf"}
        with patch.dict(graphics.os.environ, settings, clear=True), \
                patch.object(graphics.Path, "is_file", return_value=True):
            env = graphics.mangohud_environment("opengl", True)
        self.assertEqual(env["MANGOHUD"], "1")
        self.assertTrue(env["MACOBLOX_MANGOHUD_OPENGL"].endswith("libMangoHud_opengl.so"))
        self.assertEqual(env["MANGOHUD_CONFIG"], settings["MANGOHUD_CONFIG"])
        self.assertEqual(env["MANGOHUD_CONFIGFILE"], settings["MANGOHUD_CONFIGFILE"])
        self.assertNotIn("LD_PRELOAD", env)

    def test_mangohud_vulkan_does_not_load_opengl_hooks(self):
        with patch.dict(graphics.os.environ, {}, clear=True), \
                patch.object(graphics.Path, "is_file", return_value=False):
            self.assertEqual(graphics.mangohud_environment("vulkan", True),
                             {"MANGOHUD": "1", "MACOBLOX_MANGOHUD_OPENGL": ""})
            with self.assertRaisesRegex(RuntimeError, "Install MangoHud or turn it off"):
                graphics.mangohud_environment("opengl", True)

    def test_mangohud_toggle_reaches_host_and_guest(self):
        session = bare_session()
        session.settings = dict(core.DEFAULT_SETTINGS, mangohud=True)
        session.web_socket = session.dns = session.audio = None
        with patch.dict(core.os.environ, {}, clear=True), \
                patch.object(graphics.Path, "is_file", return_value=True), \
                patch.object(core, "host_vram_bytes", return_value=0), \
                patch.object(core, "icon_argb_file", side_effect=OSError):
            host = session.environment()
            guest = dict(item.split("=", 1) for item in session.shim_variables())
        for name in ("MANGOHUD", "MACOBLOX_MANGOHUD_OPENGL"):
            self.assertEqual(host[name], guest[name])
        self.assertEqual(guest["MANGOHUD"], "1")


if __name__ == "__main__":
    unittest.main()
