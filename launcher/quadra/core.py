"""Backend of the Quadra launcher: paths, settings, fast flags, Roblox
updates and running the macOS client through Darling. No GTK here."""

import csv
import functools
import hashlib
import json
import logging
import os
import plistlib
import re
import resource
import shutil
import signal
import socket
import stat
import struct
import subprocess
import tempfile
import threading
import sys
import time
import urllib.request
import urllib.error
import zipfile
from pathlib import Path

from . import __version__
from .gpus import GPU_ENVIRONMENT
from .i18n import _
from .rootless_scope import rootless_process_in_prefix
from .paths import migrate_directories, user_directory
from .runtime import resolve_runtime, guest_variables
from .transport_monitor import TransportMonitor
from .roblox_downloads import open_public

PROJECT = Path(__file__).resolve().parents[2]
# Everything the launcher writes: the project folder for a git checkout, the
# user's data folder when the sources are installed read-only (a package).
DATA_DIR = PROJECT if os.access(PROJECT, os.W_OK) else user_directory("DATA")
APP_BUNDLE = DATA_DIR / "RobloxPlayer.app"
BUILD_DIR = DATA_DIR / "build"
# A package may ship the shim built already (the Flatpak has no compiler).
PREBUILT_SHIM = os.environ.get("QUADRA_PREBUILT_SHIM")
SHIM_DIR = Path(PREBUILT_SHIM) if PREBUILT_SHIM else BUILD_DIR
SHIM = SHIM_DIR / "libQuadraShims.dylib"
# Frameworks RobloxPlayer links that Darling lacks; stubs from frameworks/.
FRAMEWORKS = ["CoreML", "CoreHaptics", "DeviceCheck"]
FRAMEWORKS_BUILD = SHIM_DIR / "frameworks"
# Quadra M2VK (renderer "metal"): Metal.framework and the host library,
# built by prototype/metal-vulkan/build.sh the first time the renderer is used.
METAL_DIR = SHIM_DIR / "metal"
METAL_HOST_LIBRARY = METAL_DIR / "libquadra_metal_host.so"
METAL_FRAMEWORK = METAL_DIR / "Metal.framework" / "Versions" / "A" / "Metal"
METAL_BUILD_SCRIPT = PROJECT / "prototype" / "metal-vulkan" / "build.sh"
# Keep the selected client, build root and guest prefix together even when
# regular Darling and CiderDarling are both installed.
DARLING_RUNTIME = resolve_runtime()
DARLING_EXECUTABLE = DARLING_RUNTIME["executable"]
DARLING_SYSROOT = Path(DARLING_RUNTIME["sysroot"])
DARLING_PREFIX = Path(DARLING_RUNTIME["prefix"])
# Rootless Darling (for sandboxes such as Flatpak, see flatpak/darling-noroot.c):
# this library is preloaded into `darling` only, never into the launcher.
NOROOT_LIB = os.environ.get("QUADRA_NOROOT_LIB")
# Darling's bridges to host libraries that Roblox never uses, relative to the
# macOS root: when the host lacks the library, they are patched to load nothing.
NATIVE_LIBS = [f"usr/lib/native/{name}.dylib"
               for name in ("libavcodec", "libavformat", "libavutil", "libswresample", "libjpeg", "libfuse")]
NATIVE_LIBS.append("System/Library/Frameworks/OpenGL.framework/Versions/A/Libraries/libGLU.dylib")
NATIVE_BUILD = BUILD_DIR / "native"
BUILD_SCRIPT = PROJECT / "build_debug_shim.sh"
LOGS = DATA_DIR / "logs"
BACKUPS = DATA_DIR / "backups"
DOWNLOADS = DATA_DIR / "downloads"
ICONS = PROJECT / "branding" / "icons"
FAST_FLAGS = APP_BUNDLE / "Contents" / "MacOS" / "ClientSettings" / "ClientAppSettings.json"

CONFIG_DIR = user_directory("CONFIG")
CACHE_DIR = user_directory("CACHE")
# Written by the shim when Roblox starts terminating; see RobloxSession.poll.
QUIT_SENTINEL = CACHE_DIR / "game-closing"
# The last error shown in a dialog, for reports; cleared after a success.
LAST_ERROR = CACHE_DIR / "last-error.txt"
SETTINGS_FILE = CONFIG_DIR / "settings.json"
# Cookies and site data of Roblox's embedded web pages (web.py): sign-in state.
WEB_DATA_DIR = CONFIG_DIR / "web"

DARLING_HOME = DARLING_PREFIX / "Users" / os.environ.get("USER", "user")
SESSION_DIR = migrate_directories(DARLING_HOME / "Library" / "QuadraHQ",
                                  DARLING_HOME / "Library" / "CiderHQ",
                                  DARLING_HOME / "Library" / "MacOBlox")
SESSION_FILES = [
    SESSION_DIR / "Cookies.plist",
    SESSION_DIR / "Keychain",
]

VERSION_URL = "https://clientsettingscdn.roblox.com/v2/client-version/MacPlayer"
DOWNLOAD_URL = "https://setup.rbxcdn.com/mac/{upload}-RobloxPlayer.zip"

DEFAULT_SETTINGS = {
    "setup_complete": False,
    "language": "en",
    "launcher_appearance": "grid",
    "mouse_sensitivity": 1.0,
    "scroll_sensitivity": 1.5,
    "auto_patch_throttle": True,
    "raw_mouse": True,
    "display_backend": "x11",
    "dpi_scale": 1.0,
    "renderer": "opengl",
    "metal_shader_preload": True,
    "metal_library_preload": True,
    "metal_resource_preload": True,
    "metal_diagnostics": False,
    # Quadra M2VK tuning (graphics.metal_tuning_environment); the values are the defaults.
    "metal_accuracy": "fast",
    "metal_present_mode": "auto",
    "metal_memory_priority": True,
    "metal_compile_threads": 0,
    "metal_warm_states": 256,
    "metal_vram_limit_gib": 0,
    # Play with OpenGL this once, rather than not at all, when Quadra M2VK cannot start.
    "metal_fallback": True,
    "gpu": "auto",
    "roblox_channel": "",
    "mangohud": False,
    # VR through the host's OpenXR runtime (see vr.py); experimental.
    "vr": False,
    "vr_render_scale": 70,
    "vr_mirror": True,
    "hide_menu_bar": False,
    "dns": "system",
    "dns_custom": "",
    "show_launcher_after_exit": True,
    "diagnostic_signals": False,
    "trace_udp": False,
    "trace_lock": False,
    "trace_events": False,
    "trace_gl": False,
    "fps_log": False,
    "trace_keys": False,
    "keep_logs": 30,
    "show_sidebar": True,
    "framerate_cap": 0,
    "hide_launcher_on_launch": True,
    "show_playtime": True,
    # Sends the game server's IP address to RoValra, so it is opt-in. (The
    # former show_server_location key was saved as true for everyone.)
    "server_location_lookup": False,
    "playtime_seconds": 0,
    "discord_rpc": True,
    "discord_rpc_game": True,
    "discord_rpc_icon": False,
    "discord_rpc_time": True,
    "auto_check_roblox_updates": True,
    "auto_check_ciderdarling_updates": True,
    "mod_death_sound": "default",
    "mod_custom_death_sound": "",
    "mod_old_character_sounds": False,
    "mod_cursor_type": "default",
    "mod_custom_cursor": "",
    "mod_custom_font": "",
    "enable_custom_mods": True,
    # Lets diagnostics read the game's thread stacks under Yama ptrace_scope=1.
    "allow_debugger": False,
    "trace_text_input": False,
    # CiderDarling only (Settings -> CiderDarling); see ciderdarling_variables.
    "cider_trace": False,
    "cider_verbose_server_log": False,
    "cider_thread_kicks": False,
    # Milliseconds between looks at the game's idle I/O loops (QUADRA_KEVENT_POLL_MS in net_trace.c). Without it
    # the menu waited about 18 s after leaving a game for a loop that was never woken; 0 turns it off.
    "kevent_poll_ms": 100,
    # Roblox Studio (studio.py), through Wine. See Settings -> Studio.
    "studio_renderer": "dxvk",   # dxvk, dxvk-sarek, d3d11 (Wine's OpenGL), d3d11fl10 or vulkan
    "studio_gpu": "",            # PCI address of the GPU Studio renders on; "" is the system default
    "studio_gamemode": True,
    "studio_webview": True,      # Edge WebView2, which Studio's sign-in and web panels need
    "studio_discord": True,
    "studio_theme": True,        # follow the system's light/dark preference
    "studio_backup": True,       # keep Studio's sign-in and settings outside the Wine prefix
    "studio_wine": "",           # a Kombucha release tag; "" is the newest stable
    "studio_wine_root": "",      # a Wine folder of your own (it holds bin/wine); replaces Kombucha
    "studio_version": "",        # a Studio deployment (version-...) to stay on; "" is the newest
    "studio_channel": "",        # a deployment channel; "" is the one of the signed-in account
    "studio_fflags": {},         # extra Studio fast flags
}

# Settings -> environment variables understood by the shim.
TRACE_ENV = {
    "diagnostic_signals": "QUADRA_DIAGNOSTIC_SIGNALS",
    "trace_udp": "QUADRA_TRACE_UDP",
    "trace_lock": "QUADRA_TRACE_LOCK",
    "trace_events": "QUADRA_TRACE_EVENTS",
    "trace_gl": "QUADRA_TRACE_GL",
    "fps_log": "QUADRA_FPS_LOG",
    "trace_keys": "QUADRA_TRACE_KEYS",
    "allow_debugger": "QUADRA_ALLOW_DEBUGGER",
}
# These also apply when set in the launcher's own environment.
TRACE_ENV_INHERITED = ("diagnostic_signals", "allow_debugger")


def load_settings():
    """Settings with defaults for anything missing. A stored value of the
    wrong type (a hand edit, a damaged file) falls back to its default rather
    than failing every launch later."""
    settings = dict(DEFAULT_SETTINGS)
    try:
        stored = json.loads(SETTINGS_FILE.read_text())
    except (OSError, ValueError):
        stored = {}
    if not isinstance(stored, dict):
        return settings
    for key, value in stored.items():
        if key == "launcher_appearance":
            settings[key] = value if isinstance(value, str) and value in ("grid", "gnome", "monochrome") else "grid"
            continue
        if key == "dpi_scale":
            from .display import validated_dpi_scale
            settings[key] = validated_dpi_scale(value)
            continue
        default = DEFAULT_SETTINGS.get(key)
        if isinstance(default, bool):
            valid = isinstance(value, bool)
        elif isinstance(default, (int, float)):
            valid = isinstance(value, (int, float)) and not isinstance(value, bool)
            value = type(default)(value) if valid else value
        else:
            valid = default is None or isinstance(value, type(default))
        if valid:
            settings[key] = value
    return settings


def _write_atomically(path, text):
    """Replace `path` in one step, so a crash or a full disk leaves the old file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text)
    temporary.replace(path)


def save_settings(settings):
    _write_atomically(SETTINGS_FILE, json.dumps(settings, indent=2, ensure_ascii=False))


def clear_last_error():
    """Forget the last error once an install or launch has succeeded."""
    try:
        LAST_ERROR.unlink(missing_ok=True)
    except OSError:
        pass


# ---------------------------------------------------------------- fast flags

def load_fast_flags():
    try:
        data = json.loads(FAST_FLAGS.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_fast_flags(flags):
    _write_atomically(FAST_FLAGS, json.dumps(flags, indent=2, ensure_ascii=False))


def parse_flag_value(text):
    """Turn what the user typed into the JSON value Roblox expects."""
    stripped = text.strip()
    lowered = stripped.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    try:
        return int(stripped)
    except ValueError:
        return stripped


def format_flag_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def format_playtime(seconds: int) -> str:
    """Format playtime in seconds into a concise string like '1M', '2H 15M'."""
    seconds = max(0, int(seconds))
    total_mins = seconds // 60
    if total_mins < 60:
        return f"{max(1, total_mins)}M" if seconds >= 60 else "0M"
    hours = total_mins // 60
    mins = total_mins % 60
    if mins:
        return f"{hours}H {mins}M"
    return f"{hours}H"


# ------------------------------------------------------------------ versions

def installed_version():
    try:
        with open(APP_BUNDLE / "Contents" / "Info.plist", "rb") as file:
            version = plistlib.load(file).get("CFBundleShortVersionString")
    except Exception:  # missing or damaged: plistlib raises several kinds
        return None
    return version if isinstance(version, str) else None


def _validated_deployment(data):
    if not isinstance(data, dict):
        raise ValueError("Invalid Roblox deployment response")
    version, upload = data.get("version"), data.get("clientVersionUpload")
    if (not isinstance(version, str) or not re.fullmatch(r"\d{1,10}(?:\.\d{1,10}){3}", version)
            or not isinstance(upload, str) or not re.fullmatch(r"version-[0-9a-fA-F]{16,64}", upload)):
        raise ValueError("Invalid Roblox deployment version or upload identifier")
    return version, upload


def version_is_newer(candidate, installed):
    try:
        return tuple(map(int, candidate.split("."))) > tuple(map(int, installed.split(".")))
    except (AttributeError, TypeError, ValueError):
        return candidate != installed


def latest_version(channel="", required_log=None):
    """Check the public release unless a required update names a channel.

    A previously reported rollout channel may be restricted to signed-in
    clients. It must never become the default for setup or routine checks.
    """
    if not isinstance(channel, str) or (channel and not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", channel)):
        raise RuntimeError("Invalid Roblox update channel")
    url = VERSION_URL + ("/channel/" + channel if channel else "")
    try:
        with open_public(url, timeout=10) as response:
            data = json.loads(response.read(65536))
    except urllib.error.HTTPError as error:
        if channel and error.code in (401, 403):
            target = required_client_update(required_log)
            if (target and target.get("channel") == channel and target.get("upload")
                    and version_is_newer(target["version"], installed_version())):
                return target["version"], target["upload"]
            raise RuntimeError(f"Roblox restricts update checks for channel {channel}. Start Roblox and use its required-update dialog to install the version requested by the client.") from error
        raise
    return _validated_deployment(data)


REPO_URL = "https://github.com/QuadraHQ/Quadra.git"
RELEASES_URL = "https://github.com/QuadraHQ/Quadra/releases/latest"
LAUNCHER_RELEASE_URL = "https://api.github.com/repos/QuadraHQ/Quadra/releases/latest"
# Keep these patterns aligned with install.sh. Hosting files stay on main,
# while partial app fetches only materialize blobs selected by this checkout.
LAUNCHER_SPARSE_PATTERNS = """/*
!/website/
!/.github/
!/vercel.json
!/.vercel/
!/.vercelignore
"""


def parse_version_tuple(ver):
    return tuple(int(x) for x in re.findall(r"\d+", ver)) if ver else (0,)


def check_launcher_update():
    """Checks GitHub for a newer release of Quadra.
    Returns (has_update, latest_version_string, release_url); raises when
    GitHub cannot be reached, so a failed check is not reported as up to date."""
    req = urllib.request.Request(LAUNCHER_RELEASE_URL, headers={"User-Agent": "Quadra"})
    with urllib.request.urlopen(req, timeout=6) as response:
        data = json.loads(response.read().decode())
    tag = str(data.get("tag_name") or "").lstrip("v")
    html_url = data.get("html_url") or RELEASES_URL
    has_update = bool(tag) and parse_version_tuple(tag) > parse_version_tuple(__version__)
    return has_update, tag, html_url


def _git(*args, input=None):
    return subprocess.run(["git", "-C", str(PROJECT), *args], input=input,
                          capture_output=True, text=True)


def update_launcher(progress=None):
    """Updates Quadra the way install.sh does: pulls the checkout
    (fast-forward only, so a failed update never leaves a half merge),
    rebuilds the shim and reinstalls the menu entries. Returns (True,
    message), or (False, release page) when this is not a git checkout
    (Flatpak, packages)."""
    if not (PROJECT / ".git").is_dir():
        return False, RELEASES_URL
    if progress:
        progress(0.2, _("Pulling latest version…"))
    # Match the installer's migration of recognized legacy repository URLs.
    origin = _git("remote", "get-url", "origin").stdout.strip()
    legacy_remotes = {
        "https://github.com/narezy/MacOBlox", "https://github.com/narezy/MacOBlox.git",
        "https://github.com/aubree-lat/MacOBlox", "https://github.com/aubree-lat/MacOBlox.git",
        "git@github.com:aubree-lat/MacOBlox", "git@github.com:aubree-lat/MacOBlox.git",
        "ssh://git@github.com/aubree-lat/MacOBlox", "ssh://git@github.com/aubree-lat/MacOBlox.git",
        "https://github.com/CiderHQ-org/Cider", "https://github.com/CiderHQ-org/Cider.git",
        "git@github.com:CiderHQ-org/Cider", "git@github.com:CiderHQ-org/Cider.git",
        "ssh://git@github.com/CiderHQ-org/Cider", "ssh://git@github.com/CiderHQ-org/Cider.git",
    }
    if origin in legacy_remotes:
        result = _git("remote", "set-url", "origin", REPO_URL)
        if result.returncode:
            raise RuntimeError(_("Could not update the files in {path}:\n{output}",
                                 path=PROJECT, output=(result.stderr or result.stdout).strip()))
    for arguments, patterns in (
        (("config", "remote.origin.promisor", "true"), None),
        (("config", "remote.origin.partialclonefilter", "blob:none"), None),
        (("sparse-checkout", "set", "--no-cone", "--stdin"), LAUNCHER_SPARSE_PATTERNS),
        (("fetch", "--filter=blob:none", "origin", "main"), None),
        (("merge", "--ff-only", "origin/main"), None),
    ):
        result = _git(*arguments, input=patterns)
        if result.returncode != 0:
            raise RuntimeError(_("Could not update the files in {path}:\n{output}",
                                 path=PROJECT, output=(result.stderr or result.stdout).strip()))

    if progress:
        progress(0.6, _("Building shim…"))
    ok, output = build_shim()
    if not ok:
        raise RuntimeError(_("Could not build the shim:\n{output}", output=output))

    if progress:
        progress(0.9, _("Updating launcher shortcuts…"))
    install_script = PROJECT / "launcher" / "install.sh"
    if install_script.exists():
        subprocess.run([str(install_script)], cwd=str(PROJECT), check=True,
                       capture_output=True)

    if progress:
        progress(1.0, _("Quadra updated successfully"))
    # This process keeps running the code it started with.
    return True, _("Quadra updated. Restart it to use the new version.")


# A shortcut to Settings -> CiderDarling while CiderDarling is installed; the
# same entry as packaging/org.quadrahq.Quadra.CiderDarling.desktop and the one
# launcher/install.sh writes. The marker line identifies a copy we may remove.
CIDERDARLING_SHORTCUT = "org.quadrahq.Quadra.CiderDarling.desktop"
SHORTCUT_MARKER = "X-QuadraHQ-Managed=true"
CIDERDARLING_DESKTOP = """[Desktop Entry]
Type=Application
Name=CiderDarling Settings
Name[ru]=Настройки CiderDarling
Comment=Graphics card, runtime and diagnostics settings for CiderDarling
Comment[ru]=Видеокарта, среда и диагностика для CiderDarling
Exec={command} --ciderdarling-settings
Icon=quadrahq
Terminal=false
Categories=Game;
Keywords=ciderdarling;darling;gpu;
StartupNotify=true
{marker}
"""


def _desktop_command():
    """How desktop entries start this launcher: the packages' wrapper (it sets
    the prebuilt shim path), or this checkout's script as a quoted argument."""
    if PREBUILT_SHIM:
        return "quadrahq"
    text = str(PROJECT / "launcher" / "quadrahq-launcher").replace("\\", "\\\\\\\\")
    for character in '"`$':
        text = text.replace(character, "\\\\" + character)
    return '"' + text.replace("%", "%%") + '"'


def sync_ciderdarling_shortcut(installed, applications=None):
    """Add the CiderDarling settings shortcut when CiderDarling is installed
    and the entry is missing, and remove our copy when it is not installed;
    True when the entry changed. An existing entry is left as it is: its
    command is launcher/install.sh's to update (another checkout may run)."""
    if os.environ.get("FLATPAK_ID"):
        return False
    if applications is None:
        data = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        applications = Path(data) / "applications"
    entry = Path(applications) / CIDERDARLING_SHORTCUT
    try:
        existing = entry.read_text() if entry.is_file() and not entry.is_symlink() else None
        ours = existing is not None and SHORTCUT_MARKER in existing.splitlines()
        if installed:
            if entry.exists() or entry.is_symlink():
                return False
            _write_atomically(entry, CIDERDARLING_DESKTOP.format(command=_desktop_command(),
                                                                 marker=SHORTCUT_MARKER))
        elif ours:
            entry.unlink()
        else:
            return False
    except OSError as error:
        logging.getLogger("quadra").warning("Could not update the CiderDarling shortcut: %s", error)
        return False
    try:
        subprocess.run(["update-desktop-database", str(applications)], stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
    except (OSError, subprocess.SubprocessError):
        pass
    return True


def update_roblox(upload, progress=None, expected_version=None):
    """Download the official macOS client and swap it in, keeping fast flags.
    The previous bundle is moved to backups/, and that path is returned (None
    when there was no client before). progress(fraction, text)."""
    if not isinstance(upload, str) or not re.fullmatch(r"version-[0-9a-fA-F]{16,64}", upload):
        raise RuntimeError("Invalid Roblox client upload identifier")
    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    archive = DOWNLOADS / f"{upload}-RobloxPlayer.zip"
    try:
        def fallback_progress():
            if progress:
                progress(0.0, _("Roblox returned 403; trying another download server"))
        with open_public(DOWNLOAD_URL.format(upload=upload), timeout=30,
                         on_fallback=fallback_progress) as response, open(archive, "wb") as out:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            while chunk := response.read(1 << 16):
                out.write(chunk)
                done += len(chunk)
                if progress and total:
                    progress(done / total * 0.9, _("Downloading {done} of {total} MB",
                                                      done=done >> 20, total=total >> 20))
            if total and done != total:
                raise OSError(f"Incomplete Roblox download: received {done} of {total} bytes. The installed client was kept.")
    except BaseException:
        archive.unlink(missing_ok=True)  # no half-downloaded client left behind
        raise
    # Unpack next to the bundle: the swap below is a rename, which fails
    # across filesystems (downloads/ may be a link to another disk).
    unpack = Path(tempfile.mkdtemp(prefix=".unpack-", dir=DATA_DIR))
    try:
        if not zipfile.is_zipfile(archive):
            raise RuntimeError(_("The download is not a zip archive"))
        if progress:
            progress(0.92, _("Unpacking"))
        # unzip keeps the executable bits, zipfile does not.
        subprocess.run(["unzip", "-q", str(archive), "-d", str(unpack)], check=True)
        new_bundle = unpack / "RobloxPlayer.app"
        if not new_bundle.is_dir():
            raise RuntimeError(_("The archive has no RobloxPlayer.app"))
        if expected_version is not None:
            with (new_bundle / "Contents" / "Info.plist").open("rb") as file:
                downloaded = plistlib.load(file).get("CFBundleShortVersionString")
            if downloaded != expected_version:
                raise RuntimeError(f"Roblox download version mismatch: requested {expected_version}, received {downloaded}. The installed client was kept.")
        flags = load_fast_flags()
        old_version = installed_version() or "unknown"
        BACKUPS.mkdir(parents=True, exist_ok=True)
        backup = BACKUPS / f"RobloxPlayer-{old_version}.app"
        if backup.exists():
            shutil.rmtree(backup)
        had_bundle = APP_BUNDLE.exists()
        if had_bundle:
            APP_BUNDLE.rename(backup)
        try:
            new_bundle.rename(APP_BUNDLE)
        except OSError:
            if had_bundle:
                backup.rename(APP_BUNDLE)  # never leave the user without a client
            raise
    finally:
        shutil.rmtree(unpack, ignore_errors=True)
        archive.unlink(missing_ok=True)
    if had_bundle:
        # Keep only the newest backup: each is a whole client of several
        # hundred MB. (Not on a first install: an older backup may then be
        # the only other client there is.)
        for old in BACKUPS.glob("RobloxPlayer-*.app"):
            if old != backup:
                shutil.rmtree(old, ignore_errors=True)
    if flags:
        save_fast_flags(flags)
    apply_throttle_patch()
    ensure_raknet_transport()
    ensure_shader_compatibility()
    if progress:
        progress(1.0, _("Done"))
    return backup if had_bundle else None


def throttle_patch_state():
    """Whether the startup render throttle is patched out of the installed
    client: 'patched', 'original' or 'unsupported' (no client, or a build
    whose code shape the patcher does not recognize)."""
    try:
        r = subprocess.run(
            [sys.executable, str(PROJECT / "patch_startup_throttle.py"),
             str(APP_BUNDLE), "--check"],
            capture_output=True, text=True, timeout=120)
    except Exception:
        return "unsupported"
    out = (r.stdout or "").strip()
    return out if out in ("patched", "original") else "unsupported"


def run_throttle_patcher(*flags):
    """Run the patcher and return its output; raises on a failure exit."""
    try:
        r = subprocess.run(
            [sys.executable, str(PROJECT / "patch_startup_throttle.py"),
             str(APP_BUNDLE), *flags],
            capture_output=True, text=True, timeout=120)
    except Exception as e:
        raise RuntimeError(str(e)) from e
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "").strip() or f"exit {r.returncode}")
    return (r.stdout or "").strip()


def remove_throttle_patch():
    """Restore the original client bytes; the inverse of the patch."""
    return run_throttle_patcher("--undo")


def apply_throttle_patch():
    """Re-apply the startup-throttle patch to the client binary (see
    patch_startup_throttle.py at the project root).

    The macOS client throttles the menu to ~3 FPS for its first 10 seconds
    under Darling (the normal release path needs a preRenderJob that is never
    created here). The patcher locates its site by pattern, so it survives
    client updates and skips itself when the code shape changes. Runs on
    installs, updates and every launch when auto_patch_throttle is on; a run
    costs ~0.3 s."""
    if not load_settings().get("auto_patch_throttle", True):
        return
    try:
        output = run_throttle_patcher()
    except Exception as e:
        logging.getLogger("quadra").warning("Startup throttle patch failed: %s", e)
        return
    if "(patched at" in output:
        logging.getLogger("quadra").info(output)
    elif "not found" in output:
        logging.getLogger("quadra").warning("Startup throttle patch: %s", output)
    # "already disabled" stays silent.


def ensure_raknet_transport():
    """Ensure FastFlags in ClientAppSettings.json and the client binary disable
    RbxTransport (QUIC) and enforce RakNet. Under Darling, RbxTransport fails socket
    connection, causing an ~11 s freeze before Roblox disconnects with Error 256."""
    try:
        flags = load_fast_flags()
        needed = {
            "FFlagUseRbxTransportClient": "False",
            "FFlagUseRbxTransportClient3": "False",
            "FFlagUseRbxTransportServer": "False",
            "FFlagShareRbxTransport": "False",
            "FFlagRbxTransportRuntime": "False",
            "DFFlagDebugDisableRbxTransportDummyClient": "True",
            "FFlagDebugDisableRbxTransportDummyClient": "True",
            "FStringRbxTransportDummyClientEnabledMinorVersions": "",
            "FStringRbxTransportDummyClientEnabledMinorVersions_PlaceFilter": "none",
            "DFIntRbxTransportDummyClientConnectionTimeoutMs": 0,
            "DFIntRbxTransportQuicHandshakeTimeoutMs": 0,
            # The Pop-latency STUN probe sends UDP bursts to 24 datacenters
            # every 0.5 s for ~5 s: it delays the first join (menu appears
            # late) and blocks the render switch after leaving a game.
            "DFFlagEnablePopLatencyProbe3": "False",
            "DFFlagAttachPopUdpProbeToGameJoin2": "False",
            # While on RakNet, Roblox opens a shadow RbxTransport connection
            # ("DummyClient will connect") that can never connect under
            # Darling; closing the session then waits for it, freezing the
            # return to the menu for seconds.
            "DFFlagRakNetFallbackToRbxTransportEvent": "False",
            "DFFlagRakNetFallbackToRbxTransportStatus": "False",
            "DFFlagConnectDummyServiceClientEarly": "False",
            "DFIntRbxTransportClientConnectionWaitIntervalMs": 0,
            # Disable client-side HTTP throttling and retry queues (which freeze
            # menu return for 5-6 s when batch thumbnails get throttled).
            "DFFlagHttpLocalThrottle": "False",
            "FFlagHttpLocalThrottle": "False",
            "DFIntHttpMaxRetries": 0,
            "DFIntHttpMaxRetryAfterSec": 0,
            "DFIntHttpRbxApiMaxThrottledQueueSize": 0,
            "DFIntHttpRetryAndLocalThrottleJitterMaxPercent": 0,
            "DFFlagHttpRetryOnExplicitHeader": "False",
            "DFFlagDebugSlimLoaderDisableHTTPRetry": "True",
            "FFlagDebugSlimLoaderDisableHTTPRetry": "True",
            "DFIntBatchThumbnailMaxWaitMs": 0,
            "DFIntBatchThumbnailMinWaitMs": 0,
            "DFIntBatchThumbnailExponentialInitialWaitMs": 0,
            "DFIntBatchThumbnailMaxExponentialRetries": 0,
            "DFIntBatchThumbnailAllowedExternalTimedOutRetries": 0,
            "DFIntLuaAppThumbnailsApiRetryTimeMultiplier": 0,
        }
        changed = False
        for k, v in needed.items():
            if flags.get(k) != v:
                flags[k] = v
                changed = True
        if changed:
            save_fast_flags(flags)

        binary = APP_BUNDLE / "Contents" / "MacOS" / "RobloxPlayer"
        if binary.is_file():
            from .transport_patches import apply_transport_patch
            status = apply_transport_patch(binary)
            if status.startswith("unsupported"):
                data = binary.read_bytes()
                status += f"; size={len(data)}; sha256={hashlib.sha256(data).hexdigest()}"
                logging.getLogger("quadra").warning("RakNet compatibility: %s", status)
            elif status == "patched":
                logging.getLogger("quadra").info("Verified RakNet compatibility patches applied")
            return status
        return "client not installed"
    except Exception as e:
        logging.getLogger("quadra").warning("Failed to ensure RakNet transport: %s", e)
        return f"compatibility preparation failed: {e}"


def ensure_shader_compatibility():
    """Repair the verified GLSL pack's HeightmapDebugPS parser failure."""
    pack = APP_BUNDLE / "Contents" / "Resources" / "shaders" / "shaders_glsl3.pack"
    if not pack.is_file():
        return "shader pack not installed"
    try:
        from .shader_patches import apply_shader_patch
        status = apply_shader_patch(pack)
        if status.startswith("unsupported"):
            data = pack.read_bytes()
            status += f"; size={len(data)}; sha256={hashlib.sha256(data).hexdigest()}"
            logging.getLogger("quadra").warning("GLSL compatibility: %s", status)
        elif status == "patched":
            logging.getLogger("quadra").info("Verified HeightmapDebugPS shader compatibility repair applied")
        return status
    except Exception as e:
        logging.getLogger("quadra").warning("Failed to ensure GLSL compatibility: %s", e)
        return f"compatibility preparation failed: {e}"


def delete_roblox():
    """Completely delete the local RobloxPlayer.app bundle and any mod backups."""
    if APP_BUNDLE.exists():
        if APP_BUNDLE.is_dir():
            shutil.rmtree(APP_BUNDLE, ignore_errors=True)
        else:
            APP_BUNDLE.unlink(missing_ok=True)
    mods_backup = DATA_DIR / "mods_backup"
    if mods_backup.exists() and mods_backup.is_dir():
        shutil.rmtree(mods_backup, ignore_errors=True)


# ----------------------------------------------------------------- processes

def _user_commands():
    """(pid, argv) of this user's processes."""
    uid = os.getuid()
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid != uid:
                continue
            argv = (entry / "cmdline").read_bytes().split(b"\0")
        except OSError:
            continue
        yield int(entry.name), [arg.decode(errors="replace") for arg in argv if arg]


def _user_processes():
    """(pid, command line joined by spaces) of this user's processes."""
    for pid, argv in _user_commands():
        yield pid, " ".join(argv)


def roblox_pids(names=("RobloxPlayer", "RobloxCrashHandler")):
    """Host PIDs of Roblox executables in the selected Darling prefix."""
    namespaces = _prefix_namespaces()
    return [pid for pid, argv in _user_commands()
            if argv and Path(argv[0]).name in names and _process_in_prefix(pid, namespaces)]


def _darlingservers():
    """darlingserver processes of our prefix."""
    return [pid for pid, argv in _user_commands() if _server_for_prefix(pid, argv)]


def _foreign_darlingservers():
    """Our prefix's darlingservers started by another runtime installation.
    An update installs a new CiderDarling revision for the same prefix, and
    the old revision's server would go on serving its own libraries.
    darling execs INSTALL_PREFIX/bin/darlingserver next to itself."""
    try:
        expected = (Path(shutil.which(DARLING_EXECUTABLE) or DARLING_EXECUTABLE).resolve().parent
                    / "darlingserver")
    except (OSError, RuntimeError):
        return []
    if not expected.is_file():
        return []  # another layout (a wrapper): nothing to compare with
    foreign = []
    for pid in _darlingservers():
        try:
            running = os.readlink(f"/proc/{pid}/exe").removesuffix(" (deleted)")
        except OSError:
            continue  # unknown: leave it
        if Path(running) != expected:
            foreign.append(pid)
    return foreign


def _server_for_prefix(pid, argv):
    if len(argv) < 2 or Path(argv[0]).name != "darlingserver":
        return False
    try:
        prefix = Path(argv[1])
        if not prefix.is_absolute():
            prefix = Path(os.readlink(f"/proc/{pid}/cwd")) / prefix
        return prefix.resolve() == DARLING_PREFIX.resolve()
    except (OSError, RuntimeError):
        return False


def _mountinfo_prefix(text):
    """Identify Darling's prefix overlay; ambiguous/missing evidence is None.

    Darling mounts upperdir=prefix,workdir=prefix.workdir on prefix itself.
    A rootless copy has no such evidence, so its orphan scope stays unknown.
    """
    def decode(value):
        return re.sub(r"\\([0-7]{3})", lambda match: chr(int(match.group(1), 8)), value)

    prefixes = set()
    for line in text.splitlines():
        before, separator, after = line.partition(" - ")
        fields, filesystem = before.split(), after.split()
        if not separator or len(fields) < 6 or len(filesystem) < 3 or filesystem[0] != "overlay":
            continue
        options = dict(option.split("=", 1) for option in filesystem[2].split(",") if "=" in option)
        upper, work = options.get("upperdir"), options.get("workdir")
        if upper is None or work is None:
            continue
        upper, work, mounted = decode(upper), decode(work), decode(fields[4])
        if not Path(upper).is_absolute() or work != upper + ".workdir":
            continue
        try:
            prefix = Path(upper).resolve()
            if Path(mounted).resolve() == prefix:
                prefixes.add(prefix)
        except (OSError, RuntimeError):
            pass
    return next(iter(prefixes)) if len(prefixes) == 1 else None


def _process_prefix(pid):
    try:
        return _mountinfo_prefix(Path(f"/proc/{pid}/mountinfo").read_text(errors="surrogateescape"))
    except OSError:
        return None


def _process_in_prefix(pid, namespaces=()):
    try:
        if Path(f"/proc/{pid}").stat().st_uid != os.getuid():
            return False
        namespace = _mount_namespace(pid)
        if namespace is None:
            return rootless_process_in_prefix(pid, DARLING_PREFIX, NOROOT_LIB)
        if namespace in namespaces:
            return True
        argv = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        argv = [argument.decode(errors="replace") for argument in argv if argument]
        return (_server_for_prefix(pid, argv)
                or rootless_process_in_prefix(pid, DARLING_PREFIX, NOROOT_LIB)
                or _process_prefix(pid) == DARLING_PREFIX.resolve())
    except (OSError, RuntimeError):
        return False


def _mount_namespace(pid):
    try:
        return os.readlink(f"/proc/{pid}/ns/mnt")
    except OSError:
        return None


def _prefix_namespaces(servers=None):
    """Private mount namespaces of freshly verified selected-prefix servers."""
    host = _mount_namespace(os.getpid())
    if host is None:
        return set()
    namespaces = set()
    for pid in _darlingservers() if servers is None else servers:
        namespace = _mount_namespace(pid)
        if namespace is None or namespace == host:
            continue
        try:
            if Path(f"/proc/{pid}").stat().st_uid != os.getuid():
                continue
            argv = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
            argv = [argument.decode(errors="replace") for argument in argv if argument]
            if _server_for_prefix(pid, argv) and _mount_namespace(pid) == namespace:
                namespaces.add(namespace)
        except OSError:
            pass
    return namespaces


def _roblox_process_in_prefix(pid, namespaces=(), names=("RobloxPlayer", "RobloxCrashHandler")):
    """Recheck executable name and prefix immediately before a scoped signal."""
    try:
        argv = Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\0")
        name = Path(argv[0].decode(errors="replace")).name if argv[0] else ""
        return name in names and _process_in_prefix(pid, namespaces)
    except OSError:
        return False


def _darling_processes():
    """(pid, mount namespace) of this user's Darling processes: every macOS
    program, Darling's daemons included, runs under the mldr loader."""
    found = []
    for pid, _argv in _user_commands():
        try:
            if os.readlink(f"/proc/{pid}/exe").rsplit("/", 1)[-1] == "mldr":
                found.append((pid, _mount_namespace(pid)))
        except OSError:
            pass
    return found


def _container_processes(servers):
    """Darling processes in the containers of the darlingservers `servers`
    (private mount namespaces, or proven prefix runtime mappings for rootless
    guests). launchd and the daemons may not be server children."""
    namespaces = _prefix_namespaces(servers)
    server_ids = set(servers)
    rootless_selected = bool(NOROOT_LIB) and any(
        pid in server_ids and _server_for_prefix(pid, argv) for pid, argv in _user_commands())
    return [pid for pid, namespace in _darling_processes()
            if namespace in namespaces or (rootless_selected and
                rootless_process_in_prefix(pid, DARLING_PREFIX, NOROOT_LIB))]


def _orphaned_darling_processes():
    """Orphaned Darling processes proven to belong to the selected prefix."""
    server_commands = [(pid, argv) for pid, argv in _user_commands()
                       if argv and Path(argv[0]).name == "darlingserver"]
    servers = [pid for pid, _argv in server_commands]
    alive = {_mount_namespace(pid) for pid in servers} - {None}
    selected_server_alive = any(_server_for_prefix(pid, argv) for pid, argv in server_commands)
    try:
        selected = DARLING_PREFIX.resolve()
    except (OSError, RuntimeError):
        return []
    overlay_orphans, rootless_orphans = [], []
    for pid, namespace in _darling_processes():
        if namespace is not None and namespace not in alive and _process_prefix(pid) == selected:
            overlay_orphans.append(pid)
        elif (NOROOT_LIB and not selected_server_alive and
              rootless_process_in_prefix(pid, selected, NOROOT_LIB)):
            rootless_orphans.append(pid)
    # A server may have started while the guest mappings were being scanned.
    # A shared namespace cannot distinguish its current guests from orphans.
    if rootless_orphans and darlingserver_running():
        rootless_orphans = []
    return overlay_orphans + rootless_orphans


def _terminate(pids, wait=5.0, *, scope=None):
    """Terminate only verified targets, using stable handles through escalation."""
    return _terminate_scoped(pids, wait, scope if scope is not None else _process_in_prefix)


def _terminate_scoped(pids, wait, scope):
    """Use stable pidfds and verify scope before signaling; unknowns stay."""
    if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
        return
    targets = {}
    try:
        for pid in dict.fromkeys(pids):
            try:
                descriptor = os.pidfd_open(pid)
            except OSError:
                continue
            try:
                accepted = scope(pid)
            except BaseException:
                os.close(descriptor)
                raise
            if not accepted:
                os.close(descriptor)
                continue
            targets[pid] = descriptor
            try:
                signal.pidfd_send_signal(descriptor, signal.SIGTERM)
            except OSError:
                pass
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline and any(_process_state(pid) not in (None, "Z") for pid in targets):
            time.sleep(0.1)
        for pid, descriptor in targets.items():
            if _process_state(pid) not in (None, "Z"):
                try:
                    signal.pidfd_send_signal(descriptor, signal.SIGKILL)
                except OSError:
                    pass
    finally:
        for descriptor in targets.values():
            os.close(descriptor)


def _signal_scoped(pids, sig, scope):
    """Send one signal through a pidfd after checking the current scope."""
    if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
        return
    for pid in dict.fromkeys(pids):
        try:
            descriptor = os.pidfd_open(pid)
        except OSError:
            continue
        try:
            if scope(pid):
                try:
                    signal.pidfd_send_signal(descriptor, sig)
                except OSError:
                    pass
        finally:
            os.close(descriptor)


def _terminate_roblox(pids, wait=3):
    namespaces = _prefix_namespaces()
    _terminate(pids, wait, scope=lambda pid: _roblox_process_in_prefix(pid, namespaces))


def _kill_crash_handlers():
    namespaces = _prefix_namespaces()
    _signal_scoped(roblox_pids(("RobloxCrashHandler",)), signal.SIGKILL,
                   lambda pid: _roblox_process_in_prefix(pid, namespaces, ("RobloxCrashHandler",)))


def _terminate_frontend(process):
    """End this session's owned frontend and proven prefix descendants."""
    if process.poll() is not None:
        return
    namespaces = _prefix_namespaces()
    descendants = [pid for pid in _with_descendants([process.pid]) if pid != process.pid]
    _terminate(descendants, wait=1, scope=lambda pid: _process_in_prefix(pid, namespaces))
    # An unreaped Popen child cannot have its PID reused. Recheck ownership
    # after opening the pidfd; descendants are checked individually above.
    _terminate([process.pid], wait=2,
               scope=lambda pid: pid == process.pid and process.poll() is None)
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass


def clear_orphaned_darling():
    """End proven selected-prefix leftovers; preserve other/unknown scopes."""
    orphans = _orphaned_darling_processes()
    if orphans:
        def still_orphaned(pid):
            if NOROOT_LIB:
                # Never fall through to broad server/prefix membership if the
                # collected guest has vanished or its PID has been reused.
                return (rootless_process_in_prefix(pid, DARLING_PREFIX, NOROOT_LIB)
                        and not darlingserver_running())
            try:
                process = Path(f"/proc/{pid}")
                if process.stat().st_uid != os.getuid():
                    return False
                if os.readlink(process / "exe").rsplit("/", 1)[-1] != "mldr":
                    return False
                namespace = _mount_namespace(pid)
                live = {_mount_namespace(server) for server, argv in _user_commands()
                        if argv and Path(argv[0]).name == "darlingserver"}
                return (namespace is not None and namespace not in live
                        and _process_prefix(pid) == DARLING_PREFIX.resolve())
            except (OSError, RuntimeError):
                return False
        # Scope is rechecked after obtaining the stable pidfd, so a server
        # starting after collection cannot make new rootless guests targets.
        _terminate(orphans, scope=still_orphaned)
    return len(orphans)


# Nice values. Darling runs the game at about -4, while darlingserver,
# Darling's daemons (launchd, notifyd... all "mldr") and the audio player
# inherit the launcher's nice value, +10 when the desktop starts apps niced.
# The game waits on darlingserver for most of its system calls and on the
# player for every audio period; niced below the game, they got about a
# twentieth of its CPU share while it kept the cores busy: frame times of
# seconds, network stalls, crackling and silent audio.
SERVER_NICE = -5
PLAYER_NICE = -11


def _nice_target(nice):
    """`nice`, or the lowest nice value RLIMIT_NICE lets this user set."""
    soft = resource.getrlimit(resource.RLIMIT_NICE)[0]
    return nice if soft == resource.RLIM_INFINITY else max(nice, 20 - soft)


def _raise_priority(pid, nice):
    """Give every thread of `pid` (Linux keeps nice values per thread) the
    nice value `nice` if that is better than its own; True if it was set."""
    try:
        current = os.getpriority(os.PRIO_PROCESS, pid)
        threads = [int(tid) for tid in os.listdir(f"/proc/{pid}/task")]
    except OSError:
        return False
    if nice >= current:
        return False
    done = False
    for tid in threads:
        try:
            os.setpriority(os.PRIO_PROCESS, tid, nice)
            done = True
        except OSError:
            pass
    return done


def _with_descendants(roots):
    """`roots` and every process below them."""
    children = {}
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            try:
                stat = (entry / "stat").read_text()
                parent = int(stat.rsplit(")", 1)[1].split()[1])
            except (OSError, ValueError, IndexError):
                continue
            children.setdefault(parent, []).append(int(entry.name))
    found, pending = [], list(roots)
    while pending:
        pid = pending.pop()
        found.append(pid)
        pending.extend(children.get(pid, []))
    return found


def raise_darling_priority():
    """Raise darlingserver and every process under it (Darling's daemons;
    the game, already better, stays as it is) to SERVER_NICE. Returns how
    many processes changed."""
    target = _nice_target(SERVER_NICE)
    return sum(_raise_priority(pid, target) for pid in _with_descendants(_darlingservers()))


def darling_version(env=None):
    """What `darling --version` calls itself (a release prints its commit),
    for the launch log: reports from another Darling build than the tested
    one are otherwise hard to tell apart."""
    try:
        result = subprocess.run([DARLING_EXECUTABLE, "--version"], capture_output=True, text=True,
                                timeout=5, env=env, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    lines = (result.stdout or result.stderr).strip().splitlines()
    return lines[0].strip() if lines else "unknown"


def darlingserver_running():
    return bool(_darlingservers())


def darling_environment(settings=None, notes=None):
    """Environment for every `darling` command the launcher runs.

    darlingserver keeps the environment of the command that started it. An
    inherited DSERVER_LOG_STDERR copied every server message into the launch
    log (one grew to 143 MB), so DSERVER_LOG_* is only kept on request:
    CIDER_KEEP_DSERVER_LOG=1, or CiderDarling's verbose server log setting.
    `notes` collects a line for the launch log about what was dropped.
    """
    env = dict(os.environ)
    env["DPREFIX"] = str(DARLING_PREFIX)
    # Darling's Mesa receives X11 displays; a Wayland session may say otherwise.
    env["EGL_PLATFORM"] = "x11"
    if NOROOT_LIB:
        env["LD_PRELOAD"] = NOROOT_LIB
    if env.get("CIDER_KEEP_DSERVER_LOG") != "1":
        dropped = sorted(name for name in env if name.startswith("DSERVER_LOG_"))
        for name in dropped:
            del env[name]
        if dropped:
            note = (f"Ignoring inherited {', '.join(dropped)} for darlingserver "
                    "(CIDER_KEEP_DSERVER_LOG=1 keeps them)")
            logging.getLogger("quadra").info(note)
            if notes is not None:
                notes.append(note)
    if (settings and settings.get("cider_verbose_server_log")
            and DARLING_RUNTIME["runtime"] == "ciderdarling"):
        env["DSERVER_LOG_LEVEL"] = "debug"
    return env


def _is_x11_reachable(display: str) -> bool:
    """Test whether an X11 server is reachable on the given DISPLAY string."""
    if not display:
        return False
    if display.startswith(":"):
        num = display[1:].split(".")[0]
        sock_path = f"/tmp/.X11-unix/X{num}"
        if not os.path.exists(sock_path):
            return False
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                s.connect(sock_path)
                return True
        except OSError:
            return False
    try:
        host, port_str = display.split(":")
        port = 6000 + int(port_str.split(".")[0])
        with socket.create_connection((host or "127.0.0.1", port), timeout=0.5):
            return True
    except (OSError, ValueError):
        return False


def _find_working_x11_display() -> str | None:
    """Find any active local X11 display socket under /tmp/.X11-unix/."""
    socket_dir = Path("/tmp/.X11-unix")
    if not socket_dir.is_dir():
        return None
    for entry in socket_dir.glob("X*"):
        num = entry.name[1:]
        if num.isdigit():
            cand = f":{num}"
            if _is_x11_reachable(cand):
                return cand
    return None


def ensure_x11(env: dict[str, str]) -> None:
    """Ensure an X11 display is reachable, attempting to start Xwayland or recover if needed."""
    display = env.get("DISPLAY", ":0")
    if _is_x11_reachable(display):
        return

    # Check for another active X11 display socket
    alt = _find_working_x11_display()
    if alt:
        env["DISPLAY"] = alt
        return

    # In Wayland, try reviving user's Xwayland service (e.g. xwayland-satellite)
    if env.get("WAYLAND_DISPLAY"):
        try:
            res = subprocess.run(
                ["systemctl", "--user", "start", "xwayland-satellite.service"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3
            )
            if res.returncode == 0:
                for _i in range(25):
                    time.sleep(0.1)
                    if _is_x11_reachable(display):
                        return
                    alt = _find_working_x11_display()
                    if alt:
                        env["DISPLAY"] = alt
                        return
        except Exception:
            pass

    # Final check
    alt = _find_working_x11_display()
    if alt:
        env["DISPLAY"] = alt
        return

    raise RuntimeError(
        _("Cannot connect to X11 display {display}. Make sure an X server or Xwayland is running.",
          display=display)
    )


def stop_roblox():
    _terminate_roblox(roblox_pids(), wait=3)


def _darling_path(path):
    """Path of a file under the Darling prefix as seen inside the container."""
    return "/" + str(path.relative_to(DARLING_PREFIX))


def signed_in():
    """Whether a Roblox login is saved (only the cookie's name is read)."""
    try:
        with open(SESSION_FILES[0], "rb") as file:
            cookies = plistlib.load(file)
    except Exception:  # missing or damaged (plistlib raises several kinds)
        return False
    return any(isinstance(c, dict) and c.get("Name") == ".ROBLOSECURITY" and c.get("Value")
               for c in cookies if isinstance(cookies, list))


def _log_tail(log_path, limit=32768):
    try:
        with open(log_path, "rb") as file:
            file.seek(0, os.SEEK_END)
            file.seek(max(0, file.tell() - limit))
            return file.read(limit).decode(errors="replace")
    except (OSError, TypeError):
        return ""


def required_client_update(log_path):
    """Validated deployment requested by this client, including gated channels.

    Do not forward logged URLs or authentication. Uploads are downloaded only
    from our fixed official CDN URL, and their bundle version is checked before
    replacing the installed client. A channel without a response is retained
    so recovery cannot silently check the unrelated production deployment.
    """
    tail = _log_tail(log_path, 262144)
    if ("flow end: app_closed_for_update" not in tail and
            "Found new version and the updater launched. Drain reporting and quit." not in tail):
        return None
    channels = re.findall(r"\[FLog::UpdateController\] UpdateController: versionQueryUrl: "
                          r"https://clientsettingscdn\.roblox\.com/v2/client-version/MacPlayer"
                          r"(?:/channel/([A-Za-z0-9_-]{1,64}))?(?=\s|$)", tail)
    target = {"channel": channels[-1]} if channels else {}
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\[FLog::UpdateController\] version response:\s*", tail):
        try:
            data, _end = decoder.raw_decode(tail[match.end():match.end() + 4096])
            version, upload = _validated_deployment(data)
            target.update(version=version, upload=upload)
        except (ValueError, TypeError):
            continue
    # A second launch can choose FORCE using a valid UpdateController cache
    # without logging another network response. Never use another channel's
    # cache (the production/zbeta mismatch is what caused this update loop).
    if ("upload" not in target and "channel" in target and
            "[FLog::UpdateController] Cache valid (" in tail and
            "[FLog::UpdateController] Cache channel mismatch" not in tail):
        for match in re.finditer(r'\[FLog::UpdateController\] channel: "([A-Za-z0-9_-]{0,64})", '
                                 r'timestamp: \d+, json:\s*', tail):
            if match.group(1) != target["channel"]:
                continue
            try:
                data, _end = decoder.raw_decode(tail[match.end():match.end() + 4096])
                version, upload = _validated_deployment(data)
                target.update(version=version, upload=upload)
            except (ValueError, TypeError):
                continue
    return target or None


def exit_reason(log_path):
    """A known cause for a game that quit, from its log, or None."""
    tail = _log_tail(log_path)
    if ("flow end: app_closed_for_update" in tail or
            "Found new version and the updater launched. Drain reporting and quit." in tail):
        return "update_required"
    if "class WKWebView" in tail or "Selector setDetachesHiddenViews:" in tail:
        return "captcha"
    if "X connection to " in tail and "broken (explicit kill or server shutdown)" in tail:
        return "x11_broken"
    if ("[MangoHud]" in tail and "filesystem_error" in tail and
            re.search(r"Permission denied: [\"']/proc/\d+/fdinfo", tail)):
        return "mangohud_fdinfo"
    return None


def logout():
    """Delete the saved Roblox session. Returns True when it is gone.
    Blocks up to a minute: call it off the GTK thread."""
    shutil.rmtree(WEB_DATA_DIR, ignore_errors=True)
    # Files inside ~/.darling must not be removed from the host while
    # darlingserver runs: its overlay then stops showing new files to the host.
    if darlingserver_running():
        try:
            subprocess.run([DARLING_EXECUTABLE, "shell", "/bin/rm", "-rf",
                            *[_darling_path(path) for path in SESSION_FILES]],
                           env=darling_environment(), stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        except (OSError, subprocess.SubprocessError):
            pass
    else:
        for path in SESSION_FILES:
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                elif path.exists():
                    path.unlink()
            except OSError:
                pass
    return not any(path.exists() for path in SESSION_FILES)


# Launch logs past this total are removed oldest first (count is `keep_logs`).
LOGS_MAX_BYTES = 200 * 1024 * 1024


def cleanup_logs(keep, current=None, max_bytes=LOGS_MAX_BYTES):
    """Remove old files written by the launcher itself: launch logs
    (launch-YYYYmmdd-HHMMSS.log) beyond `keep` or beyond `max_bytes` in
    total, and CiderDarling traces likewise. `current` is never removed;
    logs from run_debug.sh and other tools are left alone."""
    for glob, pattern in (("launch-*.log", r"launch-\d{8}-\d{6}\.log"),
                          ("ciderdarling-trace-*.jsonl", r"ciderdarling-trace-\d{8}-\d{6}\.jsonl"),
                          ("metal-performance-*.jsonl", r"metal-performance-\d{8}-\d{6}-\d+\.jsonl")):
        logs = []
        for path in LOGS.glob(glob):
            try:
                if re.fullmatch(pattern, path.name) and path != current and not path.is_symlink():
                    info = path.stat()
                    logs.append((info.st_mtime, info.st_size, path))
            except OSError:
                pass
        logs.sort(key=lambda entry: entry[0], reverse=True)
        total = 0
        for index, (_mtime, size, path) in enumerate(logs):
            total += size
            if index < max(0, keep) and total <= max_bytes:
                continue
            try:
                path.unlink()
            except OSError:
                pass


# darlingserver appends to this for as long as the prefix exists.
DSERVER_LOG_MAX_BYTES = 32 * 1024 * 1024


def rotate_dserver_log(limit=DSERVER_LOG_MAX_BYTES):
    """Keep one older dserver.log (dserver.log.old) when it grew past `limit`.
    Only while Darling is stopped: the server holds the file open."""
    log = DARLING_PREFIX / "private" / "var" / "log" / "dserver.log"
    try:
        if log.is_symlink() or not log.is_file() or log.stat().st_size <= limit:
            return False
        if darlingserver_running():
            return False
        log.replace(log.with_name("dserver.log.old"))
        return True
    except OSError:
        return False


SHIM_STAMP = BUILD_DIR / "sources.sha256"


def _shim_sources_hash():
    """Hash of everything the shim build uses, and of the launcher version."""
    digest = hashlib.sha256(__version__.encode())
    digest.update(str(DARLING_SYSROOT).encode())
    digest.update(str(DARLING_RUNTIME["metadata"].get("source_revision", "")).encode())
    for path in sorted([*PROJECT.glob("*.c"), *PROJECT.glob("*.cpp"), *PROJECT.glob("*.m"), *PROJECT.glob("*.h"),
                        *(PROJECT / "frameworks").glob("*"), BUILD_SCRIPT]):
        try:
            digest.update(path.name.encode() + b"\0" + path.read_bytes())
        except OSError:
            pass
    return digest.hexdigest()


def build_shim():
    if PREBUILT_SHIM:
        return True, _("The shim comes built with this package")
    stamp = _shim_sources_hash()
    result = subprocess.run([str(BUILD_SCRIPT)], capture_output=True, text=True,
                            env=dict(os.environ, QUADRA_BUILD_DIR=str(BUILD_DIR),
                                     DARLING_SYSROOT=str(DARLING_SYSROOT)))
    if result.returncode == 0:
        try:
            _write_atomically(SHIM_STAMP, stamp + "\n")
        except OSError:
            pass
    return result.returncode == 0, (result.stdout + result.stderr).strip()


def shim_built():
    """Built, and from the current sources: after a launcher update (git
    pull, a package upgrade) the next start rebuilds the shim."""
    if not (SHIM.exists() and all((FRAMEWORKS_BUILD / f"{name}.framework" / name).exists()
                                  for name in FRAMEWORKS)):
        return False
    if PREBUILT_SHIM:
        return True
    try:
        return SHIM_STAMP.read_text().strip() == _shim_sources_hash()
    except OSError:
        return False


def _metal_sources_hash():
    digest = hashlib.sha256(__version__.encode())
    digest.update(str(DARLING_SYSROOT).encode())
    root = PROJECT / "prototype" / "metal-vulkan"
    sources = [root / "quadra_metal.h", METAL_BUILD_SCRIPT, *(root / "framework").glob("*"),
               root / "host" / "Cargo.toml", root / "host" / "Cargo.lock", *(root / "host" / "src").rglob("*.rs")]
    # Cargo.toml and Cargo.lock pin the immutable Quadra M2VK dependency.
    for path in sorted(sources):
        try:
            digest.update(str(path.relative_to(PROJECT)).encode() + b"\0" + path.read_bytes())
        except OSError:
            pass
    return digest.hexdigest()


def metal_built():
    if not (METAL_HOST_LIBRARY.exists() and METAL_FRAMEWORK.exists()):
        return False
    if PREBUILT_SHIM:
        return True
    try:
        return (METAL_DIR / "sources.sha256").read_text().strip() == _metal_sources_hash()
    except OSError:
        return False


def build_metal():
    """prototype/metal-vulkan/build.sh: the framework needs clang and lld, the host library
    Rust 1.98 or newer (its first build downloads its crates)."""
    if PREBUILT_SHIM:
        return metal_built(), _("Quadra M2VK is not part of this package")
    if not shutil.which("cargo"):
        return False, _("Quadra M2VK needs Rust (cargo) 1.98 or newer to build. Install Rust or select another renderer.")
    stamp = _metal_sources_hash()
    result = subprocess.run([str(METAL_BUILD_SCRIPT)], capture_output=True, text=True,
                            env=dict(os.environ, QUADRA_BUILD_DIR=str(BUILD_DIR),
                                     DARLING_SYSROOT=str(DARLING_SYSROOT)))
    if result.returncode == 0:
        try:
            _write_atomically(METAL_DIR / "sources.sha256", stamp + "\n")
        except OSError:
            pass
    return result.returncode == 0, (result.stdout + result.stderr).strip()[-4000:]


def missing_tools():
    """Programs the launcher needs that are not installed."""
    needed = {DARLING_EXECUTABLE: "darling", "unzip": "unzip"}
    if not PREBUILT_SHIM:
        needed.update({"clang": "clang", "ld.lld": "lld"})
    missing = [package for program, package in needed.items() if not shutil.which(program)]
    if not DARLING_SYSROOT.is_dir() and "darling" not in missing:
        missing.append(f"darling ({DARLING_SYSROOT})")
    return missing


def _missing_frameworks():
    """Stub frameworks the prefix lacks, or holds in an older build."""
    relative = Path("System/Library/Frameworks")
    missing = []
    for name in FRAMEWORKS:
        if (DARLING_SYSROOT / relative / f"{name}.framework").exists():
            continue  # Darling has the real one
        binary = Path(f"{name}.framework") / "Versions" / "A" / name
        try:
            if (DARLING_PREFIX / relative / binary).read_bytes() == (FRAMEWORKS_BUILD / binary).read_bytes():
                continue
        except OSError:
            pass
        missing.append(name)
    return missing


def _install_framework(name):
    """Put the fresh build of a stub framework into the prefix. Copying it
    over the old copy failed on the old copy's symlinks (File exists), so it
    is copied next to it and swapped in."""
    frameworks = DARLING_PREFIX / "System" / "Library" / "Frameworks"
    target = frameworks / f"{name}.framework"
    staged = frameworks / f".{name}.framework.new"
    old = frameworks / f".{name}.framework.old"
    frameworks.mkdir(parents=True, exist_ok=True)
    for leftover in (staged, old):  # from an interrupted earlier run
        if leftover.is_dir() and not leftover.is_symlink():
            shutil.rmtree(leftover)
    shutil.copytree(FRAMEWORKS_BUILD / f"{name}.framework", staged, symlinks=True)
    if target.exists() or target.is_symlink():
        target.rename(old)
    staged.rename(target)
    shutil.rmtree(old, ignore_errors=True)


def prepare_prefix(env):
    """Puts the stub frameworks and repaired runtime libraries into the
    Darling prefix. Its system folders belong to root, so programs inside
    Darling cannot write there; the files go straight into the prefix's
    upper layer (~/.darling) while Darling is stopped, then Darling sees them
    on its next start. Returns lines for the launch log."""
    frameworks = _missing_frameworks()
    bridges = _patched_ffmpeg_bridges()
    kqueue_libraries = _patched_kqueue_runtime()
    if frameworks or bridges or kqueue_libraries:
        _install_prefix_files(env, frameworks, bridges, kqueue_libraries)
    unknown = _unknown_prefix_overrides()
    if not unknown:
        return []
    note = ("Prefix libraries not made by Quadra hide the selected runtime's own and were left "
            f"unchanged (remove them if they came from an older Darling): {', '.join(unknown)}")
    logging.getLogger("quadra").warning(note)
    return [note]


def _install_prefix_files(env, frameworks, bridges, kqueue_libraries):
    if not DARLING_PREFIX.is_dir():
        # Let Darling create the prefix first.
        try:
            subprocess.run([DARLING_EXECUTABLE, "shell", "true"], env=env, stdin=subprocess.DEVNULL,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)
        except (OSError, subprocess.SubprocessError):
            pass
        if not DARLING_PREFIX.is_dir():
            raise RuntimeError(_("Darling could not create its prefix in {path}", path=DARLING_PREFIX))
    if darlingserver_running():
        restart_darling()
    for name in frameworks:
        _install_framework(name)
    from . import darling_patches
    stamps = {}
    for relative, path in [*bridges, *kqueue_libraries]:
        target = DARLING_PREFIX / relative
        if target.is_symlink():
            continue
        if path is None:
            _restore_runtime_library(relative)
        elif not target.exists() and (relative, path) in kqueue_libraries:
            status = darling_patches.install_sparse_map_copy(path, target, library=relative.as_posix())
            logging.getLogger("quadra").info("Darling kqueue map: %s", status)
        else:
            # Planning found no file there or a copy this launcher made.
            _replace_prefix_file(path, target)
        stamps[relative.as_posix()] = _prefix_stamp(relative)
    _record_prefix_stamps(stamps)


# Copies the launcher put into a prefix, by prefix and macOS path: the sha256
# of the selected runtime's file each was made from and of the copy itself.
# A runtime update changes the first, so the copy is made again from the new
# file instead of hiding it; a prefix file without a record is someone else's.
PREFIX_STAMPS = CACHE_DIR / "prefix-libraries.json"


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _prefix_stamps():
    try:
        if PREFIX_STAMPS.stat().st_size > 1 << 20:
            return {}
        entries = json.loads(PREFIX_STAMPS.read_text()).get(str(DARLING_PREFIX.resolve()))
        return entries if isinstance(entries, dict) else {}
    except (OSError, ValueError, AttributeError, RuntimeError):
        return {}


def _prefix_stamp(relative):
    """The record for a prefix file now in place, or None when there is none."""
    try:
        return {"source": _sha256((DARLING_SYSROOT / relative).read_bytes()),
                "installed": _sha256((DARLING_PREFIX / relative).read_bytes())}
    except OSError:
        return None


def _record_prefix_stamps(changes):
    """Update records ({macOS path: record or None}); unchanged ones stay."""
    try:
        data = json.loads(PREFIX_STAMPS.read_text())
        data = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        data = {}
    try:
        key = str(DARLING_PREFIX.resolve())
    except (OSError, RuntimeError):
        return
    entries = data.get(key) if isinstance(data.get(key), dict) else {}
    updated = dict(entries)
    for relative, record in changes.items():
        if record is None:
            updated.pop(relative, None)
        else:
            updated[relative] = record
    if updated == entries:
        return
    data[key] = updated
    try:
        _write_atomically(PREFIX_STAMPS, json.dumps(data, indent=2) + "\n")
    except OSError as error:
        logging.getLogger("quadra").warning("Could not record prefix libraries: %s", error)


def _owned_prefix_copy(relative, data, source_data, stamps, recognized):
    """Whether the prefix file holding `data` may be replaced: a copy this
    launcher recorded, an unchanged copy of the runtime's own file (as in a
    rootless prefix), or a repair only this launcher makes (copies from
    releases before the records). Anything else is a custom override."""
    record = stamps.get(relative)
    if isinstance(record, dict) and record.get("installed") == _sha256(data):
        return True
    return data == source_data or recognized(data)


def _replace_prefix_file(source, target):
    """Atomically put a copy of `source` at `target` (Darling is stopped)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    data = Path(source).read_bytes()
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            os.fchmod(output.fileno(), stat.S_IMODE(Path(source).stat().st_mode))
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _restore_runtime_library(relative):
    """Undo this launcher's copy of a library the runtime now provides as is."""
    target = DARLING_PREFIX / relative
    if NOROOT_LIB:
        # A rootless prefix is a full copy of the macOS root: copy it back.
        _replace_prefix_file(DARLING_SYSROOT / relative, target)
    else:
        target.unlink(missing_ok=True)  # the overlay shows the runtime's file again


def _unknown_prefix_overrides(limit=4096):
    """Prefix libraries that hide one of the selected runtime's and that this
    launcher did not make (macOS paths), e.g. a hand-copied libsystem_m."""
    if NOROOT_LIB:
        return []  # a rootless prefix is a full copy of the macOS root
    try:
        prefix = DARLING_PREFIX.resolve()
    except (OSError, RuntimeError):
        return []
    stamps = _prefix_stamps()
    found, seen = [], 0
    for top in ("usr/lib", "System/Library/Frameworks/OpenGL.framework"):
        for directory, _directories, names in os.walk(DARLING_PREFIX / top):
            for name in names:
                seen += 1
                if seen > limit:
                    return sorted(found)
                path = Path(directory) / name
                if not name.endswith(".dylib"):
                    continue
                try:
                    relative = path.relative_to(DARLING_PREFIX)
                    if (path.is_symlink() or not path.is_file()
                            or not path.resolve().is_relative_to(prefix)
                            or not (DARLING_SYSROOT / relative).is_file()):
                        continue
                    record = stamps.get(relative.as_posix())
                    if isinstance(record, dict) and record.get("installed") == _sha256(path.read_bytes()):
                        continue
                except (OSError, ValueError, RuntimeError):
                    continue
                found.append(relative.as_posix())
    return sorted(found)


def _patched_kqueue_runtime():
    """Stage the known library repair for this prefix from the selected
    runtime's own file, again when that changed; preserve custom overrides.
    Returns (macOS path, staged file) pairs; None restores the runtime's file."""
    from . import darling_patches
    libraries = []
    stamps, current = _prefix_stamps(), {}
    # Darling builds contain independent copies of libkqueue. Its active
    # close path lives in libSystem.B; libc also has a private copy.
    for relative in (Path("usr/lib/libSystem.B.dylib"),
                     Path("usr/lib/system/libsystem_c.dylib")):
        library = relative.as_posix()
        installed = DARLING_PREFIX / relative
        if (installed.is_symlink()
                or not installed.resolve().is_relative_to(DARLING_PREFIX.resolve())):
            continue
        # A rootless prefix holds its own copy of every system library: repair
        # that copy, or these two would come from a newer runtime than the rest.
        source = installed if NOROOT_LIB and installed.is_file() else DARLING_SYSROOT / relative

        def recognized(value, library=library):
            status = darling_patches.plan_sparse_map_patch(value, library=library)[0]
            # A rootless prefix starts as a copy of a (possibly older) root.
            return status == "already patched" or (bool(NOROOT_LIB) and status == "patched")

        try:
            source_data = source.read_bytes() if source.is_file() else None
            data = installed.read_bytes() if installed.exists() else None
            if data is not None and not _owned_prefix_copy(library, data, source_data, stamps, recognized):
                continue  # a custom override: reported by _unknown_prefix_overrides
            if source_data is None:
                continue
            status, expected = darling_patches.plan_sparse_map_patch(source_data, library=library)
            if status != "patched":
                if status != "already patched":
                    logging.getLogger("quadra").debug("Darling kqueue map: %s", status)
                if data is not None and data != source_data:
                    libraries.append((relative, None))  # our copy of an older runtime file
                continue
            if data == expected:
                current[library] = {"source": _sha256(source_data), "installed": _sha256(data)}
                continue
            staged = NATIVE_BUILD / relative.name
            staged_status = darling_patches.install_sparse_map_copy(source, staged, library=library)
            if staged_status not in ("patched", "already patched"):
                continue
            staged_data = staged.read_bytes()
            if (staged_data != expected
                    or darling_patches.plan_sparse_map_patch(staged_data,
                        library=library)[0] != "already patched"):
                continue
            libraries.append((relative, staged))
        except OSError as error:
            logging.getLogger("quadra").warning("Could not stage Darling kqueue repair: %s", error)
    _record_prefix_stamps(current)
    return libraries


def _initializer_offset(data):
    """File offset of the `_initializer` function in the x86_64 slice of a
    (fat) Mach-O library, or None."""
    slice_offset = 0
    if data[:4] == b"\xca\xfe\xba\xbe":
        for index in range(struct.unpack_from(">I", data, 4)[0]):
            cputype, _sub, offset, _size, _align = struct.unpack_from(">5I", data, 8 + index * 20)
            if cputype == 0x01000007:
                slice_offset = offset
                break
        else:
            return None
    if data[slice_offset:slice_offset + 4] != b"\xcf\xfa\xed\xfe":
        return None
    ncmds = struct.unpack_from("<I", data, slice_offset + 16)[0]
    position = slice_offset + 32
    segments, symtab = [], None
    for _command in range(ncmds):
        command, size = struct.unpack_from("<II", data, position)
        if command == 0x19:  # LC_SEGMENT_64
            segments.append(struct.unpack_from("<4Q", data, position + 24))
        elif command == 0x2:  # LC_SYMTAB
            symtab = struct.unpack_from("<4I", data, position + 8)
        position += size
    if not symtab:
        return None
    symoff, nsyms, stroff, _strsize = symtab
    for index in range(nsyms):
        strx, _type, _sect, _desc, value = struct.unpack_from("<IBBHQ", data, slice_offset + symoff + index * 16)
        name_start = slice_offset + stroff + strx
        if data[name_start:data.index(b"\0", name_start)] != b"_initializer":
            continue
        for vmaddr, vmsize, fileoff, _filesize in segments:
            if vmaddr <= value < vmaddr + vmsize:
                return slice_offset + fileoff + value - vmaddr
    return None


def _host_libraries():
    try:
        output = subprocess.run(["ldconfig", "-p"], capture_output=True, text=True).stdout
    except OSError:
        return set()
    return {line.split()[0] for line in output.splitlines()[1:] if line.strip()}


def _patched_ffmpeg_bridges():
    """Darling's bridges to host libraries (/usr/lib/native/libav*.dylib and
    others) load one exact host version from an initializer, and the game
    exits when it is missing ("Cannot load libavformat.so.60"). Roblox does
    not need these, so when the host has another version (or none, as in the
    Flatpak), the prefix gets copies whose initializer returns right away.
    Copies are made from the selected runtime's file, and made again when it
    changed. Returns (path in the macOS root, patched file) pairs to install;
    None restores the runtime's own file."""
    host = None
    patched = []
    stamps, current = _prefix_stamps(), {}

    def initializer(data):
        try:
            offset = _initializer_offset(data)
        except (ValueError, IndexError, struct.error):
            return None
        return data[offset] if offset is not None and offset < len(data) else None

    def recognized(data):
        # 0xC3 (ret) is this launcher's patch; a rootless prefix starts as a
        # copy of a (possibly older) root with the stock 0x55 (push %rbp).
        return initializer(data) == 0xC3 or (bool(NOROOT_LIB) and initializer(data) == 0x55)

    for relative in map(Path, NATIVE_LIBS):
        installed = DARLING_PREFIX / relative
        name = relative.stem
        try:
            if (installed.is_symlink()
                    or not installed.resolve().is_relative_to(DARLING_PREFIX.resolve())):
                continue
            source_data = (DARLING_SYSROOT / relative).read_bytes()
            data = installed.read_bytes() if installed.exists() else None
        except (OSError, RuntimeError):
            continue
        if (data is not None and
                not _owned_prefix_copy(relative.as_posix(), data, source_data, stamps, recognized)):
            continue  # a custom override: reported by _unknown_prefix_overrides
        wanted = source_data
        library = re.search(rb"%s\.so\.\d+" % name.encode(), source_data)
        host = _host_libraries() if host is None else host
        if library and library.group().decode() not in host and initializer(source_data) == 0x55:
            data_patched = bytearray(source_data)
            data_patched[_initializer_offset(source_data)] = 0xC3  # ret
            wanted = bytes(data_patched)
        if data == wanted:
            if wanted != source_data:
                current[relative.as_posix()] = {"source": _sha256(source_data),
                                                "installed": _sha256(data)}
            continue
        if wanted == source_data:
            if data is not None:
                patched.append((relative, None))  # our copy of an older runtime file
            continue
        try:
            NATIVE_BUILD.mkdir(parents=True, exist_ok=True)
            (NATIVE_BUILD / f"{name}.dylib").write_bytes(wanted)
            (NATIVE_BUILD / f"{name}.dylib").chmod(0o755)
        except OSError as error:
            logging.getLogger("quadra").warning("Could not stage %s: %s", relative, error)
            continue
        patched.append((relative, NATIVE_BUILD / f"{name}.dylib"))
    _record_prefix_stamps(current)
    return patched


def _process_state(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0]
    except (OSError, IndexError):
        return None


def clear_stale_darling():
    """If the container's init (darlingserver, whose PID is in .init.pid) is
    gone or a zombie, darling refuses to start ("Cannot open mnt namespace
    file"); move its pid file and socket aside so a new server starts. After
    a reboot the PID may belong to an unrelated process: only one of our
    prefix's darlingservers counts as alive."""
    prefix = DARLING_PREFIX
    try:
        pid = int((prefix / ".init.pid").read_text().strip())
    except OSError:
        return
    except ValueError:
        pid = None
    if pid is not None and pid in _darlingservers():
        return
    for name in (".init.pid", ".darlingserver.sock"):
        path = prefix / name
        if path.exists():
            path.rename(prefix / (name + ".stale"))


def restart_darling():
    """Stops the prefix's darlingserver and everything in its container
    (launchd, Darling's daemons, a game still closing), and proven selected-
    prefix leftovers; the next darling command starts them again. The
    daemons are not darlingserver's children: stopping only its descendants
    left them running without a server. Blocks for up to a few seconds: call
    it off the GTK thread."""
    servers = _darlingservers()
    namespaces = _prefix_namespaces(servers)
    processes = set(_with_descendants(servers)) | set(_container_processes(servers))
    processes |= set(_orphaned_darling_processes())
    # The container's programs first, so none of them runs on without its server.
    belongs = lambda pid: _process_in_prefix(pid, namespaces)
    _terminate(sorted(processes - set(servers)), scope=belongs)
    _terminate(servers, scope=belongs)
    clear_stale_darling()


def icon_argb_file():
    """Write the logo in _NET_WM_ICON layout for the shim (see QUADRA_ICON_ARGB)."""
    target = CACHE_DIR / "icon-quadrahq.argb"
    sources = [(ICONS / f"quadrahq-{size}.png", size) for size in (32, 64, 128)]
    if target.exists() and all(source.exists() and target.stat().st_mtime >= source.stat().st_mtime
                               for source, _size in sources):
        return target
    from gi.repository import GdkPixbuf  # only needed here

    words = bytearray()
    for source, size in sources:
        if not source.exists():
            continue
        pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(source), size, size, True)
        if not pixbuf.get_has_alpha():
            pixbuf = pixbuf.add_alpha(False, 0, 0, 0)
        width, height, stride = pixbuf.get_width(), pixbuf.get_height(), pixbuf.get_rowstride()
        pixels = pixbuf.get_pixels()
        words += struct.pack("<II", width, height)
        for y in range(height):
            row = pixels[y * stride:y * stride + width * 4]
            for x in range(0, width * 4, 4):
                r, g, b, a = row[x], row[x + 1], row[x + 2], row[x + 3]
                words += struct.pack("<I", (a << 24) | (r << 16) | (g << 8) | b)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    target.write_bytes(bytes(words))
    return target


# shellspawn can inherit the environment of an already-running Darling server.
# Clear GPU selectors before restoring this session's host selections so an
# Automatic launch cannot retain the previous game's offload/ICD overrides.
LAUNCH_SCRIPT = "unset " + " ".join(GPU_ENVIRONMENT) + "\n" + r'''
project=$1 shim_dir=$2 launch_uri=$3; shift 3
unset MACOBLOX_METAL MACOBLOX_METAL_FRAMEWORKS MACOBLOX_METAL_HOST_LIBRARY MACOBLOX_METAL_SHADER_CACHE DYLD_FRAMEWORK_PATH
for kv in "$@"; do export "$kv"; done
# Roblox's own frame rate limit (FramerateCap, its Maximum Frame Rate
# setting), from the launcher's FPS limit. Set here, inside Darling, right
# before the game starts: Roblox rewrites the file when it quits, and a file
# in the prefix replaced from the host is not always seen by a running
# Darling. Bash only (3.2), which splits ${var/a/b} at a "/" even inside
# quotes, so the patterns come from variables.
case ${QUADRA_FRAMERATE_CAP:-} in
  '' | *[!0-9]*) ;;
  *)
    cap_file="$HOME/Library/Roblox/GlobalBasicSettings_13.xml"
    if [ -f "$cap_file" ]; then
      content=$(<"$cap_file")
      wanted="<int name=\"FramerateCap\">$QUADRA_FRAMERATE_CAP</int>"
      pattern='<int name="FramerateCap">-?[0-9]+</int>'
      if [[ $content =~ $pattern ]]; then
        old=${BASH_REMATCH[0]}
        content=${content/$old/$wanted}
      else
        close='</Properties>'
        insert=$'\t'"$wanted"$'\n\t\t</Properties>'
        content=${content/$close/$insert}
      fi
      printf '%s\n' "$content" > "$cap_file"
    fi ;;
esac
app="$project/RobloxPlayer.app/Contents/MacOS"
cd "$app" || exit 1
# Nothing may run between these exports and exec: every program started
# after them would get the shim injected too.
export DYLD_FORCE_FLAT_NAMESPACE=1
export DYLD_INSERT_LIBRARIES="$shim_dir/libQuadraShims.dylib"
export DYLD_LIBRARY_PATH="$shim_dir:$app"
if [ -n "${MACOBLOX_METAL_FRAMEWORKS:-}" ]; then
  export DYLD_FRAMEWORK_PATH="$MACOBLOX_METAL_FRAMEWORKS"
fi
if [ -n "$launch_uri" ]; then
  # Roblox's native macOS browser handoff is the -protocolString argument.
  # Keep the value as one opaque argument; the client owns the protocol
  # format. The shim logs this argument and suppresses Cocoa reinjection when
  # it is present, so one launch has one URL delivery path.
  export QUADRA_PENDING_URI="$launch_uri"
  exec ./RobloxPlayer -protocolString "$launch_uri"
fi
exec ./RobloxPlayer
'''


def host_vram_bytes(renderer=None, adapter=None):
    """Conservative graphics budget for the selected GPU, never the largest.

    Reserve memory for the compositor/driver and account for current use. If
    the renderer does not identify one GPU, use the smallest measured budget
    rather than claiming the memory of a different adapter. Unknown adapters
    get 512 MiB instead of the former invented 8 GiB.
    """
    candidates = []

    def budget(total, free):
        if total < 64 * 1024 * 1024 or free < 0 or free > total:
            return None
        reserve = min(256 * 1024 * 1024, total // 4)
        return max(64 * 1024 * 1024, min(total * 3 // 4, max(0, free - reserve)))

    for path in Path("/sys/class/drm").glob("card*/device/mem_info_vram_total"):
        try:
            total = int(path.read_text().strip())
            used_file = path.with_name("mem_info_vram_used")
            used = int(used_file.read_text().strip()) if used_file.is_file() else total // 4
            value = budget(total, total - used)
            if value is not None:
                candidates.append((path.parent.resolve().name, "", value))
        except (OSError, ValueError):
            pass
    try:
        fields = "name,memory.total,memory.free"
        if adapter:
            fields = "pci.bus_id," + fields
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=" + fields, "--format=csv,noheader,nounits"],
            stderr=subprocess.DEVNULL, text=True, timeout=1)
        from .gpus import pci_address
        for row in csv.reader(out.splitlines()):
            try:
                address = None
                parts = [part.strip() for part in row]
                if adapter:
                    address, name, total, free = parts
                    address = pci_address(address)
                else:
                    name, total, free = parts
                value = budget(int(total) * 1024 * 1024, int(free) * 1024 * 1024)
                if value is not None:
                    candidates.append((address, name, value))
            except ValueError:
                continue
    except (OSError, csv.Error, subprocess.SubprocessError):
        pass
    if adapter:
        values = [value for address, _name, value in candidates if address == adapter["pci"]]
    else:
        selected = [value for _address, name, value in candidates
                    if name and renderer and name.lower() in renderer.lower()]
        values = selected or [value for _address, _name, value in candidates]
    return min(values) if values else 512 * 1024 * 1024


@functools.lru_cache(maxsize=4)
def _pwcat_raw_supported(program):
    """PipeWire 1.0.x has pw-cat, but cannot consume our raw PCM FIFO."""
    if not program:
        return False
    try:
        help_text = subprocess.run([program, "--help"], capture_output=True, text=True,
                                   env=dict(os.environ, LC_ALL="C"), timeout=2)
        return help_text.returncode == 0 and "--raw" in help_text.stdout
    except (OSError, subprocess.SubprocessError):
        return False


class HostAudio:
    """Game sound played on the host. The shim writes raw float32 stereo
    44.1 kHz audio into a FIFO and pw-cat plays it through PipeWire, or pacat
    through PulseAudio where only that is reachable (the Flatpak). Darling's
    own audio (CoreAudio over PulseAudio on GCD) overflows Darling's
    workqueue thread stacks within seconds, so it is not used. The launcher
    keeps the FIFO open read/write for the whole session, so pw-cat never
    sees end of file and the game can reopen it any time."""

    NAME = "Roblox (Quadra)"

    def __init__(self, fifo, keep=None, player=None):
        self.fifo, self.keep, self.player = fifo, keep, player
        self.restarted_at = 0.0
        self._state_lock = threading.RLock()
        self._stopped = False
        self._owned_paths = set()
        # The microphone (voice chat): the shim reads raw float32 audio from a
        # second FIFO. A recorder runs only while the game asks for it, with
        # a request file next to the FIFO naming the rate and channel count.
        self.input_fifo = fifo.with_name(fifo.name.replace("audio-", "audio-in-"))
        self.request = Path(str(self.input_fifo) + ".request")
        self.recorder = None
        self.recording = None
        self.error_output = None
        self.log_path = None
        self.pulse_fallback = False

    def _keep_recording(self):
        wanted = None
        try:
            rate, channels = self.request.read_text().split()[:2]
            if 8000 <= int(rate) <= 192000 and 1 <= int(channels) <= 2:
                wanted = (int(rate), int(channels))
        except (OSError, ValueError):
            pass
        if self.recorder and (self.recorder.poll() is not None or wanted != self.recording):
            self._stop_recorder()
        if wanted and not self.recorder:
            command = self._recorder_command(self.input_fifo, *wanted)
            if command:
                try:
                    self.recorder = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    self.recording = wanted
                except OSError:
                    pass

    def _stop_recorder(self):
        with self._state_lock:
            recorder, self.recorder = self.recorder, None
            self.recording = None
            self._stop_process(recorder)

    @staticmethod
    def _stop_process(process):
        """Stop and reap an owned audio subprocess without skipping cleanup."""
        if process is None:
            return
        try:
            process.terminate()
        except OSError:
            pass
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except OSError:
                pass
            try:
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass
        except OSError:
            pass

    @classmethod
    def _recorder_command(cls, fifo, rate, channels):
        runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
        pipewire = os.environ.get("PIPEWIRE_REMOTE") or (runtime / "pipewire-0").exists()
        if pipewire and _pwcat_raw_supported(shutil.which("pw-cat")):
            return ["pw-cat", "--record", "--raw", "--format", "f32", "--rate", str(rate),
                    "--channels", str(channels), "--latency", "20ms", "--media-role", "Communication",
                    "-P", '{ application.name = "Roblox" application.icon-name = "quadrahq" '
                          f'media.name = "Roblox microphone (Quadra)" }}',
                    str(fifo)]
        if shutil.which("pacat"):
            return ["pacat", "--record", "--raw", "--format=float32le", f"--rate={rate}",
                    f"--channels={channels}", "--latency-msec=20", "--client-name=Roblox",
                    "--stream-name=Roblox microphone (Quadra)", "--property=media.role=phone", str(fifo)]
        return None

    @classmethod
    def _spawn(cls, fifo, error_output=None, force_pulse=False):
        command = cls._player_command(fifo, force_pulse=force_pulse)
        if not command:
            raise OSError("No compatible audio playback helper is installed")
        # Audio before the game (see PLAYER_NICE); `nice` takes a relative value.
        change = _nice_target(PLAYER_NICE) - os.getpriority(os.PRIO_PROCESS, 0)
        if change < 0 and shutil.which("nice"):
            command = ["nice", "-n", str(change), *command]
        return subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=error_output if error_output is not None else subprocess.DEVNULL)

    def _report_player_exit(self, status):
        detail = ""
        if self.error_output:
            try:
                self.error_output.seek(0)
                detail = self.error_output.read(4096).decode(errors="replace").strip()
                self.error_output.seek(0)
                self.error_output.truncate()
            except (OSError, ValueError):
                detail = "playback error output unavailable"
        if self.log_path:
            try:
                with open(self.log_path, "ab") as log:
                    log.write(f"[Quadra Audio] Playback helper exited with code {status}; {detail or 'no error output'}\n".encode())
            except OSError:
                pass

    def keep_playing(self):
        """Restart the player if it has exited (PipeWire restarted, say):
        the game keeps writing into the FIFO and would stay silent."""
        with self._state_lock:
            if self._stopped:
                return
            self._keep_recording()
            status = self.player.poll()
            if status is None or time.monotonic() - self.restarted_at < 5:
                return
            self.restarted_at = time.monotonic()
            self._report_player_exit(status)
            # PipeWire's PulseAudio server is also usable when native playback
            # initialization fails. Keep the fallback for this game session.
            if shutil.which("pacat"):
                self.pulse_fallback = True
            if self._player_command(self.fifo, force_pulse=self.pulse_fallback):
                try:
                    self.player = self._spawn(self.fifo, self.error_output, self.pulse_fallback)
                except OSError:
                    pass

    @classmethod
    def _player_command(cls, fifo, force_pulse=False):
        runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
        pipewire = os.environ.get("PIPEWIRE_REMOTE") or (runtime / "pipewire-0").exists()
        if not force_pulse and pipewire and _pwcat_raw_supported(shutil.which("pw-cat")):
            return ["pw-cat", "--playback", "--raw", "--format", "f32", "--rate", "44100",
                    "--channels", "2", "--latency", "40ms", "--media-role", "Game",
                    "-P", '{ application.name = "Roblox" application.icon-name = "quadrahq" '
                          f'media.name = "{cls.NAME}" }}',
                    str(fifo)]
        if shutil.which("pacat"):
            return ["pacat", "--playback", "--raw", "--format=float32le", "--rate=44100",
                    "--channels=2", "--latency-msec=40", "--client-name=Roblox",
                    f"--stream-name={cls.NAME}", "--property=media.role=game", str(fifo)]
        return None

    @classmethod
    def start(cls):
        if not cls._player_command(""):
            return None
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        fifo = CACHE_DIR / f"audio-{os.getpid()}.fifo"
        audio = cls(fifo)
        try:
            audio.error_output = tempfile.TemporaryFile(dir=CACHE_DIR)
            fifo.unlink(missing_ok=True)
            os.mkfifo(fifo, 0o600)
            audio._owned_paths.add(fifo)
            audio.keep = os.open(fifo, os.O_RDWR)
            for path in (audio.input_fifo, audio.request):
                try:
                    path.unlink()
                except OSError:
                    pass
            os.mkfifo(audio.input_fifo, 0o600)
            audio._owned_paths.add(audio.input_fifo)
            audio.player = cls._spawn(fifo, audio.error_output)
            return audio
        except BaseException:
            audio.stop()
            raise

    def stop(self):
        # pw-cat sits in a blocking read on the FIFO and only sees SIGTERM
        # once that returns: closing the last writer ends the read (end of
        # file). A player that still hangs is killed and reaped.
        with self._state_lock:
            if self._stopped:
                return
            self._stopped = True
            self._stop_recorder()
            if self.input_fifo in self._owned_paths:
                for path in (self.input_fifo, self.request):
                    try:
                        path.unlink()
                    except OSError:
                        pass
            keep, self.keep = self.keep, None
            if keep is not None:
                try:
                    os.close(keep)
                except OSError:
                    pass
            player, self.player = self.player, None
            self._stop_process(player)
            if self.error_output:
                self.error_output.close()
                self.error_output = None
            if self.fifo in self._owned_paths:
                try:
                    self.fifo.unlink()
                except OSError:
                    pass
            self._owned_paths.clear()


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True  # another user's process (EPERM) is alive
    return True


def sweep_audio_fifos(directory=None):
    """Remove audio FIFOs left by launchers that were killed (HostAudio.stop
    never ran): only this user's FIFOs named audio-<pid>.fifo or
    audio-in-<pid>.fifo whose process is gone. Returns how many went."""
    directory = CACHE_DIR if directory is None else Path(directory)
    removed = 0
    try:
        entries = list(directory.iterdir())
    except OSError:
        return 0
    for path in entries:
        match = re.fullmatch(r"audio-(?:in-)?([1-9]\d{0,9})\.fifo", path.name)
        if not match:
            continue
        pid = int(match.group(1))
        try:
            info = path.lstat()
            if (not stat.S_ISFIFO(info.st_mode) or info.st_uid != os.getuid()
                    or pid == os.getpid() or _pid_alive(pid)):
                continue
            path.unlink()
            removed += 1
        except OSError:
            pass
    return removed


# Time Roblox gets to finish its own quit (see RobloxSession.finish).
QUIT_GRACE_SECONDS = 6
# darlingserver's inherited stdout and stderr (see RobloxSession._start).
WARMUP_OUTPUT_LIMIT = 16384


def _warmup_output_path():
    return LOGS / f"darlingserver-{DARLING_RUNTIME['runtime']}.out"


def _darling_warmup(env):
    """Start the prefix's darlingserver with `darling shell true`; its exit
    status. The server keeps this command's stdout and stderr for its whole
    life, so they go to a file of its own (replaced per warmup: the previous
    server of this runtime is gone by then)."""
    LOGS.mkdir(parents=True, exist_ok=True)
    with open(_warmup_output_path(), "wb") as output:
        return subprocess.run([DARLING_EXECUTABLE, "shell", "true"], env=env,
                              stdin=subprocess.DEVNULL, stdout=output,
                              stderr=subprocess.STDOUT, timeout=120).returncode


def _warmup_output():
    """The warmup's output so far, for the launch log ("" when empty)."""
    text = _log_tail(_warmup_output_path(), WARMUP_OUTPUT_LIMIT)
    return text if not text or text.endswith("\n") else text + "\n"


def _prepare_darling_server(env, log):
    """Warm up the server, preserving transient retries and known failures."""
    for _attempt in range(2):
        # A first process can fail to check in while the server starts. Keep
        # the server's output separate so it cannot hold the launch log open.
        if darlingserver_running():
            return
        log.write(b"[Quadra Startup] Darling warmup starting\n")
        log.flush()
        status = _darling_warmup(env)
        output = _warmup_output()
        log.write(output.encode(errors="replace"))
        log.write(f"[Quadra Startup] Darling warmup status={status}\n".encode())
        if status and "Cannot mount overlay: No such device" in output:
            log.write(b"[Quadra Startup] OverlayFS unavailable; stopping before Roblox starts\n")
            log.flush()
            raise RuntimeError(_(
                "Darling could not start because the kernel's OverlayFS filesystem is unavailable. "
                "Roblox has not started.\n\n"
                "Run sudo modprobe overlay in a terminal, then try launching again. "
                "If the module is missing after a kernel update, reboot into the installed kernel. "
                "A custom kernel needs CONFIG_OVERLAY_FS enabled."))


class RobloxSession:
    """One run of the client. poll() returns None while it is running."""

    def __init__(self, settings, launch_uri=None):
        self.settings = settings
        self.shader_preload_progress = None
        self.preload_stage_progress = None
        self.shader_preload_cancel = threading.Event()
        self._metal_preload_skipped = False
        self.metal_diagnostics_path = LOGS / (time.strftime("metal-performance-%Y%m%d-%H%M%S-") + str(os.getpid()) + ".jsonl")
        # This is intentionally opaque.  Do not split, decode, normalize or
        # otherwise inspect a browser handoff before giving it to Roblox.
        self.launch_uri = launch_uri
        self.log_path = None
        self.process = None
        self._lifecycle_logged = False
        self._lifecycle_lock = threading.Lock()
        self.seen_roblox = False
        self.gone_since = None
        self.game_pids = []
        self.scanned_at = 0.0
        self.dns = None
        self.audio = None
        # The launcher's browser window for Roblox's embedded pages (web.py):
        # its socket as the guest sees it, and WebKit's user agent.
        self.web_socket = None
        self.web_user_agent = None
        self.gpu_adapter = None
        self._gpu_environment = None
        self.trace_path = None
        self._frontend_detached = False
        self.transport_monitor = TransportMonitor()
        # Launch log lines collected before the log exists.
        self.notes = []
        # A sentinel left over from a quit that outlived the launcher must not
        # end this session before it starts.
        QUIT_SENTINEL.unlink(missing_ok=True)

    def _graphics_environment(self):
        from . import graphics, display, gpus
        renderer = self.settings.get("renderer", "opengl")
        if self._gpu_environment is None:
            self.gpu_adapter = gpus.selected_gpu(self.settings.get("gpu", "auto"))
            self._gpu_environment = gpus.gpu_environment(self.gpu_adapter, renderer)
        metal = graphics.metal_environment(METAL_DIR, CACHE_DIR / "metal-shader-cache",
                                          preload=self.settings.get("metal_shader_preload", True),
                                          preload_key=installed_version() or "unknown-client",
                                          diagnostics=self.settings.get("metal_diagnostics", False),
                                          diagnostics_file=self.metal_diagnostics_path,
                                          tuning=graphics.metal_tuning_environment(self.settings)) \
            if renderer == "metal" else {}
        if metal and self._metal_preload_skipped:
            metal["MACOBLOX_METAL_PRELOAD_IN_PROCESS"] = "0"
        return {
            **graphics.renderer_environment(renderer),
            **metal,
            **self._gpu_environment,
            **graphics.mangohud_environment(renderer, self.settings.get("mangohud", False)),
            **display.window_environment(self.settings, SHIM_DIR / "libquadra-wayland.so"),
            **gpus.host_graphics_paths(),
        }

    def environment(self):
        env = darling_environment(self.settings, getattr(self, "notes", None))
        # Rebuild the allowlisted selectors, including intentional removals
        # (a PCI choice must not compete with an inherited vendor-ID choice).
        for name in GPU_ENVIRONMENT:
            env.pop(name, None)
        env.update(self._graphics_environment())
        if env["QUADRA_WAYLAND"] == "1":
            env.pop("DISPLAY", None)
        return env

    def shim_variables(self):
        variables = guest_variables(DARLING_RUNTIME["metadata"]) + [
            f"QUADRA_SESSION_DIRECTORY=Library/{SESSION_DIR.name}",
            f"QUADRA_MOUSE_SENSITIVITY={self.settings['mouse_sensitivity']:.2f}",
            f"QUADRA_SCROLL_SENSITIVITY={self.settings.get('scroll_sensitivity', 1.5):.2f}",
            # Mesa is the host's library and sees the host's file system,
            # not the prefix: with HOME=/Users/<name> it could not create
            # its shader cache ("Failed to create /Users for shader cache
            # -- disabling") and every launch recompiled every shader. So
            # the cache directory is given as the host path, without the
            # /Volumes/SystemRoot the guest's paths carry (with it Mesa
            # failed the same way on /Volumes). NVIDIA's driver ignores it.
            f"MESA_SHADER_CACHE_DIR={CACHE_DIR / 'mesa-shader-cache'}",
            f"MESA_GLSL_CACHE_DIR={CACHE_DIR / 'mesa-shader-cache'}",
            f"__GL_SHADER_DISK_CACHE_PATH={CACHE_DIR / 'nvidia-shader-cache'}",
            # Roblox keeps its own caches (flag cache, thumbnail temp files)
            # under the prefix's /private/tmp, which does not survive a
            # Darling restart: every launch re-downloaded 23k flags and every
            # menu return re-fetched every thumbnail (429 rate limits, blank
            # place tiles). A host directory makes those caches persistent.
            f"TMPDIR=/Volumes/SystemRoot{CACHE_DIR / 'roblox-tmp'}",
        ]
        from . import display
        variables.append(f"QUADRA_DPI_SCALE={display.validated_dpi_scale(self.settings.get('dpi_scale', 1.0)):.3f}")
        if self.settings.get("renderer", "opengl") == "metal":
            # The launch script makes it DYLD_FRAMEWORK_PATH just before exec:
            # Quadra's Metal.framework in place of Darling's.
            variables.append(f"MACOBLOX_METAL_FRAMEWORKS=/Volumes/SystemRoot{METAL_DIR}")
        # Host graphics libraries see the guest environment after exec.
        variables.extend(f"{name}={value}" for name, value in
                         self._graphics_environment().items())
        vram = host_vram_bytes(getattr(self, "renderer_name", None), self.gpu_adapter)
        if self.settings.get("renderer") == "metal":
            from . import graphics
            vram = graphics.metal_vram_cap(self.settings, vram)
        if vram:
            variables.append(f"QUADRA_VRAM_BYTES={vram}")
        if self.settings.get("hide_menu_bar"):
            variables.append("QUADRA_HIDE_MENU_BAR=1")
        from . import vr
        variables.extend(vr.shim_variables(self.settings)[0])
        if not self.settings.get("raw_mouse", True):
            variables.append("QUADRA_RAW_MOUSE=0")
        if self.settings.get("framerate_cap", 0) > 0:
            variables.append(f"QUADRA_FRAMERATE_CAP={int(self.settings['framerate_cap'])}")
        if self.web_socket:
            variables.append(f"QUADRA_WEB_SOCKET={self.web_socket}")
            if self.web_user_agent:
                variables.append(f"QUADRA_WEB_USER_AGENT={self.web_user_agent}")
        if self.dns:
            variables.append(f"QUADRA_DNS={self.dns.address}")
        if self.audio:
            variables.append(f"QUADRA_AUDIO={os.environ.get('QUADRA_AUDIO', '1')}")
            variables.append(f"QUADRA_AUDIO_FIFO=/Volumes/SystemRoot{self.audio.fifo}")
            variables.append(f"QUADRA_AUDIO_INPUT_FIFO=/Volumes/SystemRoot{self.audio.input_fifo}")
        else:
            # Darling's own audio path crashes the game (see HostAudio).
            variables.append("QUADRA_AUDIO=0")
        for key, name in TRACE_ENV.items():
            if self.settings.get(key) or (key in TRACE_ENV_INHERITED and
                                         os.environ.get(name) == "1"):
                variables.append(f"{name}=1")
        poll = self.settings.get("kevent_poll_ms", 0)
        if isinstance(poll, int) and not isinstance(poll, bool) and poll > 0:
            variables.append(f"QUADRA_KEVENT_POLL_MS={min(poll, 1000)}")
        variables.extend(self.ciderdarling_variables())
        # Selection diagnostics record lengths/ranges only and are enabled
        # explicitly for a reported typing issue, without changing settings.
        if self.settings.get('trace_text_input', False) or os.environ.get("QUADRA_TRACE_TEXT_INPUT") == "1":
            variables.append("QUADRA_TRACE_TEXT_INPUT=1")
        # Cocoa URL delivery diagnostics are opt-in and stay outside URI
        # handling. They are copied verbatim into the Darling process so a
        # live run can compare selector order and launch timing.
        for name in ("QUADRA_URI_DELAY_MS", "QUADRA_URI_SELECTOR_ORDER"):
            value = os.environ.get(name)
            if value:
                variables.append(f"{name}={value}")
        # The shim normally receives the exact launch value above.  Keep the
        # host-side pending file available as a fallback for launches that did
        # not carry the value as an argument (for example a retry after the
        # launcher was already open).
        variables.append(f"QUADRA_PENDING_URI_FILE=/Volumes/SystemRoot{CACHE_DIR / 'pending-uri'}")
        variables.append(f"QUADRA_QUIT_SENTINEL=/Volumes/SystemRoot{QUIT_SENTINEL}")
        try:
            variables.append(f"QUADRA_ICON_ARGB=/Volumes/SystemRoot{icon_argb_file()}")
        except Exception:
            pass
        return variables

    def ciderdarling_variables(self):
        """Guest settings from Settings -> CiderDarling, for that runtime only.
        Watchdog kicks are a shim feature: QUADRA_KICK/QUADRA_NO_KICK from
        the launcher's environment also reach the game with regular Darling."""
        variables = [f"{name}=1" for name in ("QUADRA_KICK", "QUADRA_NO_KICK")
                     if os.environ.get(name) == "1"]
        if DARLING_RUNTIME["runtime"] != "ciderdarling":
            return variables
        if self.settings.get("cider_thread_kicks") and "QUADRA_KICK=1" not in variables:
            variables.append("QUADRA_KICK=1")
        trace = getattr(self, "trace_path", None)
        if trace:
            # A guest path: CiderDarling opens it inside Darling.
            variables.append(f"CIDER_TRACE_FILE=/Volumes/SystemRoot{trace}")
        return variables

    def _create_trace_file(self, log_path):
        """CiderDarling writes traces only to a private regular file."""
        if not (self.settings.get("cider_trace") and DARLING_RUNTIME["runtime"] == "ciderdarling"):
            return None
        path = log_path.with_name(log_path.name.replace("launch-", "ciderdarling-trace-", 1)
                                  .removesuffix(".log") + ".jsonl")
        try:
            os.close(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                             | os.O_CLOEXEC, 0o600))
            os.chmod(path, 0o600)
        except OSError as error:
            self.notes.append(f"CiderDarling trace unavailable: {error}")
            return None
        return path

    def start(self):
        """Start the client; on failure nothing started is left running."""
        try:
            self._start()
        except BaseException:
            self.finish("startup_failure")
            raise

    def _validated_metal(self, env):
        """The environment and renderer name once the Metal host has opened a device and run a
        test copy. Where it cannot and `metal_fallback` allows, this launch (and only this one: the
        saved renderer is untouched) uses OpenGL, and the reason is kept for the log and the UI."""
        from . import graphics
        try:
            return env, "Quadra M2VK (" + graphics.validate_metal(env, METAL_HOST_LIBRARY) + ")"
        except RuntimeError as error:
            if not self.settings.get("metal_fallback", True):
                raise
            reason = str(error).strip()
        self.metal_fallback_reason = reason
        self.notes.append("Quadra M2VK could not start, so this launch uses OpenGL: " + reason)
        self.settings = dict(self.settings, renderer="opengl")
        self._gpu_environment = None
        return self.environment(), "OpenGL (Quadra M2VK could not start)"

    def _start(self):
        missing = missing_tools()
        if missing:
            raise RuntimeError(_("Install these first: {programs}", programs=", ".join(missing)))
        if not shim_built():
            ok, output = build_shim()
            if not ok:
                raise RuntimeError(_("Could not build the shim:\n{output}", output=output))
        if self.settings.get("renderer", "opengl") == "vulkan":
            from . import graphics
            graphics.ensure_vulkan_dependencies()
        if self.settings.get("renderer", "opengl") == "metal":
            from . import graphics
            missing = graphics.missing_metal_dependencies()
            if missing:
                raise RuntimeError(_("Quadra M2VK needs: {items}. Install them or select another renderer.",
                                     items=", ".join(missing)))
            if not metal_built():
                self.notes.append("Building Quadra M2VK (prototype/metal-vulkan/build.sh)")
                ok, output = build_metal()
                if not ok:
                    raise RuntimeError(_("Could not build Quadra M2VK:\n{output}", output=output))
            try:
                (CACHE_DIR / "metal-shader-cache").mkdir(parents=True, exist_ok=True)
            except OSError as error:
                self.notes.append(f"Metal shader cache unavailable; using bounded memory caching: {error}")
        env = self.environment()
        if env.get("QUADRA_WAYLAND") != "1":
            ensure_x11(env)
        renderer_name = "OpenGL"
        if self.settings.get("renderer", "opengl") == "vulkan":
            from . import graphics
            renderer_name = graphics.validate_vulkan(env)
        elif self.settings.get("renderer", "opengl") == "metal":
            env, renderer_name = self._validated_metal(env)
        self.renderer_name = renderer_name
        # A game closed a moment ago may still be shutting down. A new one next
        # to it shared its darlingserver, and when that went both died. Give it
        # time, then end it; crash handlers of earlier games are just ended.
        deadline = time.monotonic() + 20
        while roblox_pids(("RobloxPlayer",)) and time.monotonic() < deadline:
            time.sleep(0.25)
        leftover = roblox_pids()
        if leftover:
            _terminate_roblox(leftover, wait=3)
        orphans = clear_orphaned_darling()
        if _foreign_darlingservers():
            restart_darling()
            self.notes.append("Restarted Darling: its server came from another runtime installation")
        if self.settings.get("renderer", "opengl") == "metal":
            from . import metal_preload
            try:
                result = metal_preload.run(METAL_HOST_LIBRARY, env,
                                          progress=self.shader_preload_progress,
                                          cancel=self.shader_preload_cancel,
                                          library_pack=(APP_BUNDLE / "Contents/Resources/shaders/shaders_metal_osx.pack"
                                                        if self.settings.get("metal_library_preload", True) else None),
                                          resource_root=(APP_BUNDLE / "Contents/Resources"
                                                         if self.settings.get("metal_resource_preload", True) else None),
                                          stage_progress=self.preload_stage_progress)
                self.notes.append("Shader preloading: {status}, {completed}/{total} pipelines, {failed} skipped".format(**result))
                for phase, counts in result.get("stages", {}).items():
                    self.notes.append(f"Preload {phase}: " + json.dumps(counts, sort_keys=True))
                if result["status"] in ("skipped", "timeout", "failed", "disabled", "memory-limited"):
                    self._metal_preload_skipped = True
                    env["MACOBLOX_METAL_PRELOAD_IN_PROCESS"] = "0"
            except (OSError, subprocess.SubprocessError) as error:
                self._metal_preload_skipped = True
                env["MACOBLOX_METAL_PRELOAD_IN_PROCESS"] = "0"
                self.notes.append(f"Shader preloading unavailable; starting Roblox: {error}")
        self.notes.extend(prepare_prefix(env) or [])
        # The shim reads the pending file as a fallback: never an old click.
        from . import uri
        uri.expire_pending()
        try:
            from . import mods
            mods.apply_mods(self.settings)
        except Exception as e:
            logging.getLogger("quadra").warning("Failed to apply mods: %s", e)
        apply_throttle_patch()
        transport_status = ensure_raknet_transport()
        shader_status = ensure_shader_compatibility()
        provider = self.settings.get("dns", "system")
        if provider != "system" and (provider != "custom" or self.settings.get("dns_custom")):
            from .dns import DnsForwarder
            self.dns = DnsForwarder(provider, self.settings.get("dns_custom", ""))
        self.audio = HostAudio.start()
        clear_stale_darling()
        if rotate_dserver_log():
            self.notes.append("Rotated dserver.log (over 32 MB) to dserver.log.old")
        LOGS.mkdir(parents=True, exist_ok=True)
        # The Mesa shader cache dir must exist before the game opens it.
        (CACHE_DIR / "mesa-shader-cache").mkdir(parents=True, exist_ok=True)
        (CACHE_DIR / "nvidia-shader-cache").mkdir(parents=True, exist_ok=True)
        # The guest TMPDIR (Roblox's flag and thumbnail caches) likewise.
        (CACHE_DIR / "roblox-tmp").mkdir(parents=True, exist_ok=True)
        self.log_path = LOGS / time.strftime("launch-%Y%m%d-%H%M%S.log")
        cleanup_logs(int(self.settings.get("keep_logs", 30)) - 1, current=self.log_path)
        self.trace_path = self._create_trace_file(self.log_path)
        if self.audio:
            self.audio.log_path = self.log_path
        # Truncate for this launch, but keep O_APPEND on the inherited file
        # description: guest output must not overwrite a host lifecycle record.
        with open(self.log_path, "wb", opener=lambda path, flags:
                  os.open(path, flags | os.O_APPEND)) as log:
            log.write(f"Quadra {__version__}\n".encode())
            log.write(f"Darling: {darling_version(env)}\n".encode())
            log.write(f"Darling selection: {DARLING_RUNTIME['runtime']}; {DARLING_EXECUTABLE}; root {DARLING_SYSROOT}\n".encode())
            log.write(f"Renderer requested: {renderer_name}\n".encode())
            log.write(f"MangoHud requested: {'Enabled' if self.settings.get('mangohud', False) else 'Disabled'}\n".encode())
            from . import vr
            log.write(f"{vr.shim_variables(self.settings)[1]}\n".encode())
            log.write(f"Window backend: {'Wayland' if env.get('QUADRA_WAYLAND') == '1' else 'X11 / Xwayland'}\n".encode())
            if self.gpu_adapter:
                name = self.gpu_adapter["name"].replace("\n", " ").replace("\r", " ")[:200]
                log.write(f"Graphics card requested: {name}; PCI {self.gpu_adapter['pci']}\n".encode())
            else:
                log.write(b"Graphics card requested: Automatic (desktop/terminal selection)\n")
            packaging = "Flatpak" if os.environ.get("FLATPAK_ID") else (
                "prebuilt" if PREBUILT_SHIM else "source")
            version = re.sub(r"[^A-Za-z0-9._+-]", "?", (installed_version() or "unknown")[:80])
            log.write(f"Packaging: {packaging}; Roblox version: {version}\n".encode())
            log.write(f"RakNet compatibility: {transport_status}\n".encode())
            log.write(f"GLSL compatibility: {shader_status}\n".encode())
            channel = self.settings.get("roblox_channel", "")
            channel = re.sub(r"[^A-Za-z0-9_-]", "?", channel[:64]) if isinstance(channel, str) else "invalid"
            log.write(f"Last client channel: {channel or 'Release (default)'}\n".encode())
            if self.audio:
                command = self.audio._player_command(self.audio.fifo)
                log.write(f"Audio playback helper: {command[0] if command else 'unavailable'}\n".encode())
            else:
                log.write(b"Audio unavailable: install pacat (pulseaudio-utils on Mint/Ubuntu), or pw-cat with --raw support.\n")
            if leftover:
                log.write(f"Requested cleanup of {len(leftover)} selected-prefix Roblox process(es) of an earlier game\n".encode())
            if orphans:
                log.write(f"Requested cleanup of {orphans} selected-prefix Darling process(es) left without their darlingserver\n".encode())
            if self.trace_path:
                log.write(f"CiderDarling trace: {self.trace_path}\n".encode())
            if self.settings.get("renderer") == "metal" and self.settings.get("metal_diagnostics", False):
                log.write(f"Metal performance trace: {self.metal_diagnostics_path}\n".encode())
            for note in self.notes:
                log.write(f"[Quadra Startup] {note}\n".encode(errors="replace"))
            _prepare_darling_server(env, log)
            changed = raise_darling_priority()
            if changed:
                log.write(f"Priority: {changed} Darling processes raised to nice {_nice_target(SERVER_NICE)}\n".encode())
            log.flush()
            command = [DARLING_EXECUTABLE, "shell", "/bin/bash", "-c", LAUNCH_SCRIPT, "quadra",
                       f"/Volumes/SystemRoot{DATA_DIR}", f"/Volumes/SystemRoot{SHIM.parent}",
                       self.launch_uri if self.launch_uri is not None else "",
                       *self.shim_variables()]
            self.process = subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL,
                                            stdout=log, stderr=subprocess.STDOUT,
                                            start_new_session=True)
        self.started_at = time.monotonic()
        if not self.settings.get('allow_debugger', False):
            threading.Thread(target=self._suppress_crash_handler, daemon=True).start()

    def _suppress_crash_handler(self):
        """Terminate RobloxCrashHandler after initial handshake to prevent exit hangs and slow crash logs."""
        if self.settings.get('allow_debugger', False):
            return
        for _ in range(20):
            time.sleep(1)
            if not self.process or self.process.poll() is not None:
                return
            crash_pids = roblox_pids(("RobloxCrashHandler",))
            if crash_pids:
                time.sleep(2)
                _kill_crash_handlers()
                break

    def poll(self):
        """None while running, otherwise the exit status (or -1 if unknown)."""
        self.transport_monitor.poll(self.log_path)
        status = self.process.poll() if self.process else -1
        if status is not None:
            # darling shell can disconnect while the guest it launched is
            # alive. Treating that status as Roblox's exit killed the game
            # during startup (issue #27: status=1 with a live prefix player).
            players = roblox_pids(("RobloxPlayer",))
            players = [pid for pid in players if _process_state(pid) not in (None, 'Z')]
            if not players and not self._frontend_detached:
                self.finish("frontend_exit", frontend_status=status)
                return status
            if players:
                self.game_pids = players
                self.seen_roblox = True
                if not self._frontend_detached:
                    self._frontend_detached = True
                    if self.log_path:
                        try:
                            with open(self.log_path, 'ab', buffering=0) as log:
                                log.write(f'\n[Quadra Lifecycle] frontend_detached status={status} live_players={len(players)}; monitoring guest\n'.encode())
                        except OSError:
                            pass
        if self.audio:
            self.audio.keep_playing()
        # The shim touches the sentinel when Roblox starts terminating
        # (Cmd+Q, Quit in the menu). Roblox's own teardown takes seconds, and
        # the session can end for the user as soon as quitting began.
        # seen_roblox keeps a sentinel left from a dead session irrelevant.
        if self.seen_roblox and QUIT_SENTINEL.exists():
            self.finish("quit_sentinel")
            return -1
        # Suppress any crash handler to prevent slow dumps and exit blockage
        if (not self.settings.get('allow_debugger', False) and self.seen_roblox
                and time.monotonic() - self.started_at > 3):
            _kill_crash_handlers()

        # darling shell can outlive a Roblox that was killed; watch the game
        # processes themselves as well. Known ones are checked each second,
        # the whole of /proc only when they are gone or every few seconds.
        now = time.monotonic()
        namespaces = _prefix_namespaces()
        self.game_pids = [pid for pid in self.game_pids if _process_state(pid) not in (None, "Z")
                          and _roblox_process_in_prefix(pid, namespaces, ("RobloxPlayer",))]
        if not self.game_pids or now - self.scanned_at > 1:
            self.game_pids = roblox_pids(("RobloxPlayer",))
            self.scanned_at = now
        if self.game_pids:
            self.seen_roblox = True
            self.gone_since = None
        elif self.seen_roblox:
            self.gone_since = self.gone_since or time.monotonic()
            if time.monotonic() - self.gone_since > 0.5:
                self.finish("roblox_disappeared")
                return -1
        return None

    def _record_lifecycle(self, reason, frontend_status=None):
        """Record the observed state once, before cleanup can alter it."""
        with self._lifecycle_lock:
            if self._lifecycle_logged or not self.log_path:
                return
            self._lifecycle_logged = True
            try:
                frontend = "not_started"
                if self.process:
                    status = frontend_status if frontend_status is not None else self.process.poll()
                    frontend = "running" if status is None else str(status)
                try:
                    game_count = str(len(roblox_pids(("RobloxPlayer",))))
                except Exception:
                    game_count = "unknown"
                # Reasons and field values are local observations only; no
                # command line, URI, typed text or authenticated session data.
                if reason not in ("frontend_exit", "roblox_disappeared", "quit_sentinel",
                                  "startup_failure", "explicit_cleanup"):
                    reason = "explicit_cleanup"
                stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                record = (f"\n[Quadra Lifecycle] time={stamp} reason={reason} "
                          f"frontend_status={frontend} selected_prefix_games={game_count} "
                          "guest_exit=unknown before_cleanup=1\n")
                with open(self.log_path, "ab", buffering=0) as log:
                    log.write(record.encode())
            except Exception:
                # Failure to collect or append diagnostics cannot stop cleanup.
                pass

    def finish(self, reason="explicit_cleanup", frontend_status=None):
        leftover = roblox_pids()
        self._record_lifecycle(reason, frontend_status)
        if leftover and reason == "quit_sentinel":
            # Roblox is quitting by itself and saves GlobalBasicSettings while
            # it does; a signal now would lose them. Audio and DNS stay up too.
            deadline = time.monotonic() + QUIT_GRACE_SECONDS
            while roblox_pids(("RobloxPlayer",)) and time.monotonic() < deadline:
                time.sleep(0.2)
            leftover = roblox_pids()
        if leftover:
            _terminate_roblox(leftover, wait=1)
        if self.process and self.process.poll() is None:
            _terminate_frontend(self.process)
        if self.dns:
            self.dns.stop()
            self.dns = None
        if self.audio:
            self.audio.stop()
            self.audio = None


SERVER_IP_PATTERN = re.compile(
    r'Connection accepted from\s+(\d{1,3}(?:\.\d{1,3}){3})'
)
# The connection line comes from the current game; its log grows for hours.
SERVER_LOG_TAIL = 256 * 1024
# Failed lookups are not repeated for this long (successes are kept).
SERVER_LOCATION_RETRY = 300

_server_location_cache = {}
_server_location_lock = threading.Lock()


def _latest_roblox_log():
    """Return the newest Roblox Player log file inside the selected Darling
    prefix, or in the launcher's logs folder."""
    candidates_dirs = [
        DARLING_HOME / "Library" / "Logs" / "Roblox",
        LOGS,
    ]
    for log_dir in candidates_dirs:
        newest, newest_time = None, None
        try:
            for path in log_dir.glob("*_Player_*.log"):
                if "CrashHandler" in path.name:
                    continue
                try:
                    modified = path.stat().st_mtime
                except OSError:
                    continue
                if newest_time is None or modified > newest_time:
                    newest, newest_time = path, modified
        except OSError:
            continue
        if newest:
            return newest
    return None


def extract_server_ip(log_path=None):
    """Read the end of the latest Roblox log and extract the connected server IP."""
    if log_path is None:
        log_path = _latest_roblox_log()
    if not log_path or not Path(log_path).is_file():
        return None
    matches = SERVER_IP_PATTERN.findall(_log_tail(log_path, SERVER_LOG_TAIL))
    return matches[-1] if matches else None


def query_server_location(ip_address):
    """Query the RoValra API for the geolocation of a server IP. Blocks for
    up to a few seconds: call it off the GTK thread."""
    import ipaddress
    try:
        address = ipaddress.IPv4Address(ip_address)
    except ValueError:
        return None
    if not address.is_global:
        return None  # nothing to look up, and nothing to send to anyone
    with _server_location_lock:
        cached = _server_location_cache.get(str(address))
    if cached and (cached[0] is not None or time.monotonic() - cached[1] < SERVER_LOCATION_RETRY):
        return cached[0]
    url = f"https://apis.rovalra.com/v1/geolocation?ip={address}"
    result = None
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Quadra"})
        with urllib.request.urlopen(request, timeout=5) as response:
            data = json.loads(response.read(65536).decode())
        location = data.get("location", {}) if isinstance(data, dict) else {}
        location = location if isinstance(location, dict) else {}
        parts = [location.get("city"), location.get("region"), location.get("country")]
        parts = [str(part)[:64] for part in parts if part]
        result = ", ".join(parts) if parts else None
    except Exception as e:
        logging.getLogger("quadra").warning("RoValra query failed: %s", e)
    with _server_location_lock:
        _server_location_cache[str(address)] = (result, time.monotonic())
    return result


def detect_server_location():
    """Extract the current server IP and query its geolocation (blocking)."""
    ip = extract_server_ip()
    if not ip:
        return None, None
    return ip, query_server_location(ip)
