"""VR headsets through the host's OpenXR runtime (shim: vr_device.c, vr_xr.c).

The game's OpenXR loader runs as host code inside Darling, where HOME and
the XDG directories are the guest's. The launcher therefore finds the runtime
manifest the way the host's loader would and passes it explicitly."""
import ctypes.util
import json
import os
from pathlib import Path

from .i18n import _

# Installed runtimes the loader would not find without an active_runtime.json
# (WiVRn and Monado set one only while their service manages it).
KNOWN_RUNTIMES = (
    "/usr/share/openxr/1/openxr_wivrn.json",
    "/usr/share/openxr/1/openxr_monado.json",
    "/usr/local/share/openxr/1/openxr_wivrn.json",
    "/usr/local/share/openxr/1/openxr_monado.json",
)
LOADER_PATHS = (
    "/usr/lib/libopenxr_loader.so.1",
    "/usr/lib64/libopenxr_loader.so.1",
    "/usr/lib/x86_64-linux-gnu/libopenxr_loader.so.1",
    "/usr/local/lib/libopenxr_loader.so.1",
)
DEFAULT_RENDER_SCALE = 70


def _usable_manifest(path):
    """A runtime manifest whose library exists (bare names are left to the loader)."""
    try:
        library = json.loads(path.read_text())["runtime"]["library_path"]
    except (OSError, ValueError, KeyError, TypeError):
        return False
    if not isinstance(library, str) or not library:
        return False
    if "/" not in library:
        return True
    library_path = Path(library)
    if not library_path.is_absolute():
        library_path = path.resolve().parent / library_path
    return library_path.is_file()


def active_runtime(environ=None, home=None):
    """The runtime manifest the host's OpenXR loader would use, or None."""
    environ = os.environ if environ is None else environ
    home = Path.home() if home is None else Path(home)
    candidates = []
    if environ.get("XR_RUNTIME_JSON"):
        candidates.append(environ["XR_RUNTIME_JSON"])
    config_home = environ.get("XDG_CONFIG_HOME") or str(home / ".config")
    candidates.append(os.path.join(config_home, "openxr/1/active_runtime.json"))
    for directory in (environ.get("XDG_CONFIG_DIRS") or "/etc/xdg").split(":"):
        if directory:
            candidates.append(os.path.join(directory, "openxr/1/active_runtime.json"))
    candidates.append("/etc/openxr/1/active_runtime.json")
    candidates.extend(KNOWN_RUNTIMES)
    for candidate in candidates:
        path = Path(candidate)
        if path.is_file() and _usable_manifest(path):
            return path.resolve()
    return None


def loader_installed():
    return any(Path(path).exists() for path in LOADER_PATHS) or bool(ctypes.util.find_library("openxr_loader"))


def runtime_name(manifest):
    try:
        name = json.loads(Path(manifest).read_text())["runtime"].get("name")
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        name = None
    return name if isinstance(name, str) and name else Path(manifest).stem


def validated_render_scale(value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return DEFAULT_RENDER_SCALE
    return min(150, max(40, value))


def status():
    """(runtime manifest or None, a short description for the settings row)."""
    if not loader_installed():
        return None, _("The OpenXR loader is not installed (package openxr or libopenxr-loader1).")
    runtime = active_runtime()
    if runtime is None:
        return None, _("No OpenXR runtime found. Install and start WiVRn or Monado.")
    return runtime, _("Uses {runtime}. Start it and connect the headset before playing.").format(
        runtime=runtime_name(runtime))


def shim_variables(settings):
    """MACOBLOX_* variables for the shim, and a line for the launch log."""
    if not settings.get("vr", False):
        return [], "VR: off"
    runtime = active_runtime() if loader_installed() else None
    if runtime is None:
        return [], "VR: requested, but no OpenXR loader and runtime were found"
    mode = "openxr" if settings.get("vr_mirror", True) else "openxr-headset"
    scale = validated_render_scale(settings.get("vr_render_scale", DEFAULT_RENDER_SCALE))
    variables = [f"MACOBLOX_VR={mode}", f"MACOBLOX_VR_SCALE={scale}", f"MACOBLOX_XR_RUNTIME_JSON={runtime}"]
    return variables, f"VR: {runtime_name(runtime)} ({runtime}); render scale {scale}%; " \
                      f"{'mirrored in the game window' if mode == 'openxr' else 'headset only'}"
