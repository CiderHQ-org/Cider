"""Roblox Studio through Wine. No GTK here.

Studio has no macOS-only parts worth keeping, so the Windows version runs
through Kombucha, the Wine build Vinegar patches for Studio (64-bit only,
which needs no 32-bit system libraries). Direct3D 11 goes through DXVK (or
Wine's own OpenGL or a Vulkan layer, Settings -> Studio) and Studio's sign-in
and web panels through Microsoft's WebView2. Wine and Studio follow their
newest release unless Settings pins them. Everything lives in DATA_DIR/studio:
the Wine build, its prefix and Studio itself, downloaded package by package
from Roblox's own deployment like the Windows installer does.

The ideas and some details (renderer flags, the sign-in backup, GPU and theme
handling, the Vulkan layer) follow Vinegar, https://github.com/vinegarhq/vinegar
(GPL-3.0)."""

import fcntl
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import core, gpus, studio_deploy, studio_gamemode, studio_registry, studio_webview
from .i18n import _

log = logging.getLogger(__name__)

ROOT = core.DATA_DIR / "studio"
WINE = ROOT / "wine"
PREFIX = ROOT / "prefix"
APP = PREFIX / "drive_c" / "Program Files" / "Roblox Studio"
EXECUTABLE = APP / "RobloxStudioBeta.exe"
STATE = ROOT / "state.json"
# Studio's saved sign-in and settings, kept outside the prefix so that deleting
# or recreating the prefix does not sign you out.
BACKUPS = ROOT / "backup"
# Studio's local data, shared by every prefix made here.
APPDATA = ROOT / "appdata"
SUPERVISOR_LOCK = ROOT / "supervisor.lock"
# Files copied over Studio's folder at every start.
OVERLAY = core.CONFIG_DIR / "studio-overlay"

WINE_RELEASES = "https://github.com/vinegarhq/kombucha"
DXVK_RELEASES = "https://github.com/doitsujin/dxvk"
# DXVK-Sarek runs on GPUs and drivers without Vulkan 1.3; Vinegar's tested build.
SAREK_VERSION = "1.11.0"
SAREK_URL = (f"https://github.com/pythonlover02/DXVK-Sarek/releases/download/v{SAREK_VERSION}/"
             f"dxvk-sarek-async-v{SAREK_VERSION}.tar.gz")
DXVK_DLLS = ("d3d8.dll", "d3d9.dll", "d3d10core.dll", "d3d11.dll", "dxgi.dll")

# renderer: (the graphics API Studio is told to use, DXVK variant, backend of Wine's
# Direct3D and of WebView2's GPU process)
RENDERERS = {
    "dxvk": ("D3D11", "dxvk", "vulkan"),
    "dxvk-sarek": ("D3D11", "sarek", "vulkan"),
    "d3d11": ("D3D11", None, "gl"),
    "d3d11fl10": ("D3D11FL10", None, "gl"),
    "vulkan": ("Vulkan", None, "vulkan"),
}
GRAPHICS_APIS = ("D3D11", "Vulkan", "D3D11FL10", "OpenGL")
# Keys of the registry that make up the sign-in and settings backup.
BACKUP_KEYS = {"studio": r"HKCU\Software\Roblox\RobloxStudio",
               "credentials": r"HKCU\Software\Wine\Credential Manager"}
CHANNEL_KEY = r"HKCU\Software\ROBLOX Corporation\Environments\RobloxStudio\Channel"
VERSION_PATTERN = re.compile(r"version-[0-9a-f]{8,32}")
CHANNEL_PATTERN = re.compile(r"[A-Za-z0-9_.-]{1,64}")

# Where each package is unpacked, relative to the Studio folder. From
# Bloxstrap (MIT), which reads it out of Roblox's own bootstrapper.
PACKAGE_DIRS = {
    "RobloxStudio.zip": "",
    "Libraries.zip": "",
    "LibrariesQt5.zip": "",
    "redist.zip": "",
    "WebView2.zip": "",
    "shaders.zip": "shaders/",
    "ssl.zip": "ssl/",
    "content-avatar.zip": "content/avatar/",
    "content-configs.zip": "content/configs/",
    "content-fonts.zip": "content/fonts/",
    "content-sky.zip": "content/sky/",
    "content-sounds.zip": "content/sounds/",
    "content-textures2.zip": "content/textures/",
    "content-models.zip": "content/models/",
    "content-studio_svg_textures.zip": "content/studio_svg_textures/",
    "content-qt_translations.zip": "content/qt_translations/",
    "content-api-docs.zip": "content/api_docs/",
    "content-textures3.zip": "PlatformContent/pc/textures/",
    "content-terrain.zip": "PlatformContent/pc/terrain/",
    "content-platform-fonts.zip": "PlatformContent/pc/fonts/",
    "content-platform-dictionaries.zip": "PlatformContent/pc/shared_compression_dictionaries/",
    "extracontent-luapackages.zip": "ExtraContent/LuaPackages/",
    "extracontent-translations.zip": "ExtraContent/translations/",
    "extracontent-models.zip": "ExtraContent/models/",
    "extracontent-textures.zip": "ExtraContent/textures/",
    "extracontent-places.zip": "ExtraContent/places/",
    "extracontent-scripts.zip": "ExtraContent/scripts/",
    "studiocontent-models.zip": "StudioContent/models/",
    "studiocontent-textures.zip": "StudioContent/textures/",
    "BuiltInPlugins.zip": "BuiltInPlugins/",
    "BuiltInStandalonePlugins.zip": "BuiltInStandalonePlugins/",
    "ApplicationConfig.zip": "ApplicationConfig/",
    "Plugins.zip": "Plugins/",
    "Qml.zip": "Qml/",
    "StudioFonts.zip": "StudioFonts/",
    "RibbonConfig.zip": "RibbonConfig/",
}
# Installs the Edge WebView2 runtime on Windows; not used under Wine.
SKIPPED_PACKAGES = {"WebView2RuntimeInstaller.zip"}

APP_SETTINGS = """<?xml version="1.0" encoding="UTF-8"?>
<Settings>
\t<ContentFolder>content</ContentFolder>
\t<BaseUrl>http://www.roblox.com</BaseUrl>
</Settings>
"""




class Options:
    """The Studio settings, checked: a hand-edited or damaged value falls back
    to its default instead of breaking a launch."""

    def __init__(self, settings=None):
        settings = core.DEFAULT_SETTINGS if settings is None else settings

        def get(key, kind):
            value = settings.get(key, core.DEFAULT_SETTINGS[key])
            return value if isinstance(value, kind) else core.DEFAULT_SETTINGS[key]

        renderer = get("studio_renderer", str)
        self.renderer = renderer if renderer in RENDERERS else "dxvk"
        self.gpu = get("studio_gpu", str)
        self.gamemode = get("studio_gamemode", bool)
        self.webview = get("studio_webview", bool)
        self.discord = get("studio_discord", bool)
        self.theme = get("studio_theme", bool)
        self.backup = get("studio_backup", bool)
        self.wine = get("studio_wine", str).strip()
        self.wine_root = get("studio_wine_root", str).strip()
        version = get("studio_version", str).strip()
        self.version = version if VERSION_PATTERN.fullmatch(version) else ""
        channel = get("studio_channel", str).strip()
        self.channel = channel if CHANNEL_PATTERN.fullmatch(channel) else ""
        flags = get("studio_fflags", dict)
        self.fflags = {name: value for name, value in flags.items() if isinstance(name, str) and name}

    @property
    def dxvk(self):
        return RENDERERS[self.renderer][1]


class ChannelError(RuntimeError):
    """The chosen Studio channel cannot be used: shown, not skipped."""


def _state():
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def _private_root():
    """ROOT holds Studio's saved sign-in (in the Wine prefix): only for this user."""
    ROOT.mkdir(parents=True, exist_ok=True)
    ROOT.chmod(0o700)


def _save_state(state):
    _private_root()
    STATE.write_text(json.dumps(state, indent=2))


def installed_version():
    return _state().get("studio") if EXECUTABLE.exists() else None


def _open(url, timeout=30):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Quadra"}),
                                  timeout=timeout)


def _latest_tag(releases):
    """Newest release tag, from the redirect of /releases/latest (the API
    has a low anonymous rate limit)."""
    with _open(f"{releases}/releases/latest") as response:
        return urllib.parse.unquote(response.url.rstrip("/").rsplit("/", 1)[1])


def wine_releases():
    """Kombucha's release tags, newest first, for the choice in Settings. The
    "unstable" ones are Wine's latest commit: they may break Studio."""
    request = urllib.request.Request("https://api.github.com/repos/vinegarhq/kombucha/releases?per_page=30",
                                     headers={"User-Agent": "Quadra", "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(request, timeout=15) as response:
        releases = json.load(response)
    return [release["tag_name"] for release in releases
            if any(asset["name"] == f"kombucha-{release['tag_name']}.tar.xz" for asset in release["assets"])]


def _download(url, target, progress=None, label="", digest=None):
    """Download `url` (or the first of several addresses that answers) to
    `target`, feeding `digest` (a hashlib object) as it goes. A connection
    that ends early raises instead of leaving a short file."""
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.name + ".part")
    source = studio_deploy.open_first(url) if isinstance(url, (list, tuple)) else _open(url, timeout=60)
    with source as response, open(partial, "wb") as out:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        while chunk := response.read(1 << 16):
            out.write(chunk)
            if digest:
                digest.update(chunk)
            done += len(chunk)
            if progress and total:
                progress(done / total, _("{label}: {done} of {total} MB", label=label,
                                         done=done >> 20, total=total >> 20))
    if total and done != total:
        partial.unlink(missing_ok=True)
        raise OSError(f"{url}: got {done} of {total} bytes")
    partial.replace(target)
    return target


def wine_root(options=None):
    """The Wine in use: the folder chosen in Settings, or the managed Kombucha."""
    custom = options.wine_root if options else ""
    if custom and (Path(custom) / "bin" / "wine").is_file():
        return Path(custom)
    return WINE


def _wine_env(options=None, launching=False):
    options = options or Options()
    env = dict(os.environ)
    overrides = "mscoree,mshtml,dxdiagn,winemenubuilder.exe="
    if options.dxvk:
        overrides += ";d3d9,d3d10core,d3d11,dxgi=n,b"
    api, _dxvk, backend = RENDERERS[options.renderer]
    env.update({
        "WINEPREFIX": str(PREFIX),
        # Studio's own log arrives as Wine's "seh" warnings (OutputDebugString); the rest is quiet.
        "WINEDEBUG": "err-kerberos,err-ntlm,err-combase,fixme-all,warn+seh" if launching else "-all",
        "WINEDLLOVERRIDES": overrides,
        "XR_LOADER_DEBUG": "none",
        "WINE_D3D_CONFIG": f"renderer={backend}",
        "DXVK_LOG_LEVEL": "warn" if launching else "none",
        "DXVK_LOG_PATH": "none",
        "DXVK_STATE_CACHE_PATH": str(core.CACHE_DIR),
    })
    if options.webview:
        env["WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS"] = studio_webview.browser_arguments(options.renderer)
    if options.renderer == "vulkan":
        env.update(_vulkan_layer_environment())
    if launching:
        env.update(_gpu_environment(options))
    return env


def _gpu_environment(options):
    """The variables that put Studio on the GPU chosen in Settings."""
    if options.gpu in ("", "auto"):
        return {}
    try:
        adapter = gpus.selected_gpu(options.gpu)
        return gpus.gpu_environment(adapter, "opengl" if RENDERERS[options.renderer][2] == "gl" else "vulkan")
    except RuntimeError as error:
        log.warning("Studio keeps the default GPU: %s", error)
        return {}


def vulkan_layer_built():
    """Whether the shim build produced the Vulkan layer (it needs the Vulkan headers)."""
    return (Path(core.SHIM_DIR) / "libquadra-studio-layer.so").is_file()


def _vulkan_layer_environment():
    """Vinegar's fix for Studio's Vulkan renderer, which loses its swapchain
    ("out of date") under Wine: a Vulkan layer that recreates it. It is built
    with the shim; without it Studio runs unfixed."""
    if not vulkan_layer_built():
        return {}
    library = Path(core.SHIM_DIR) / "libquadra-studio-layer.so"
    directory = core.CACHE_DIR / "studio-layer"
    directory.mkdir(parents=True, exist_ok=True)
    manifest = directory / "VkLayer_QUADRA_studio.json"
    text = json.dumps({"file_format_version": "1.0.0", "layer": {
        "name": "VK_LAYER_QUADRA_studio", "type": "GLOBAL", "library_path": str(library),
        "api_version": "1.0.0", "implementation_version": "1", "description": "Quadra Studio layer",
        "functions": {"vkGetInstanceProcAddr": "QuadraStudioLayer_GetInstanceProcAddr",
                      "vkGetDeviceProcAddr": "QuadraStudioLayer_GetDeviceProcAddr"}}}, indent=2)
    if not manifest.exists() or manifest.read_text() != text:
        manifest.write_text(text)
    return {"VK_LAYER_PATH": str(directory), "VK_ADD_LAYER_PATH": str(directory),
            "VK_INSTANCE_LAYERS": "VK_LAYER_QUADRA_studio", "VK_LOADER_LAYERS_ENABLE": "VK_LAYER_QUADRA_studio"}


def _wine(*args, options=None, **kwargs):
    root = wine_root(options)
    return subprocess.run([str(root / "bin" / "wine"), *map(str, args)], env=_wine_env(options),
                          stdin=subprocess.DEVNULL, **kwargs)


def _wineserver(*args, options=None, **kwargs):
    root = wine_root(options)
    return subprocess.run([str(root / "bin" / "wineserver"), *args], env=_wine_env(options),
                          stdin=subprocess.DEVNULL, **kwargs)


def _quiet_wine(options, *args):
    """A Wine command run to completion, with everything it started."""
    result = _wine(*args, options=options, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _wineserver("--wait", options=options)
    return result


def _wine_identity(state, options):
    return f"custom:{wine_root(options)}" if wine_root(options) != WINE else state.get("wine")


def _ensure_wine(state, progress, options=None):
    """Installs the Kombucha release chosen in Settings, or the newest stable
    one (tags look like stable+20261018103513). Replacing the Wine build makes
    _ensure_prefix update the prefix."""
    pinned = options.wine if options else ""
    installed = state.get("wine") if (WINE / "bin" / "wine").exists() else None
    try:
        tag = pinned or _latest_tag(WINE_RELEASES)
    except OSError:
        if installed:
            return  # offline: keep the Wine we have
        raise
    if tag == installed:
        return
    name = f"kombucha-{tag}.tar.xz"
    archive = _download(f"{WINE_RELEASES}/releases/download/{urllib.parse.quote(tag)}/"
                        f"{urllib.parse.quote(name)}", core.DOWNLOADS / name, progress, "Wine")
    progress(1, _("Unpacking Wine"))
    if installed:
        # A wineserver of the old build would refuse the new one.
        _wineserver("-k", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    shutil.rmtree(WINE, ignore_errors=True)
    WINE.mkdir(parents=True)
    subprocess.run(["tar", "-xJf", str(archive), "-C", str(WINE), "--strip-components=1"], check=True)
    archive.unlink()
    state["wine"] = tag
    _save_state(state)


def _user_directory(name, fallback):
    """XDG user directory (DOCUMENTS, PICTURES) without a GTK dependency."""
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "user-dirs.dirs"
    try:
        for line in config.read_text().splitlines():
            match = re.fullmatch(rf'XDG_{name}_DIR="(.*)"', line.strip())
            if match:
                return Path(match[1].replace("$HOME", str(Path.home())))
    except OSError:
        pass
    return Path.home() / fallback


def _import_registry(options, text):
    ROOT.mkdir(parents=True, exist_ok=True)
    path = ROOT / "import.reg"
    path.write_text(text)
    try:
        _quiet_wine(options, "regedit", "/S", "Z:" + str(path).replace("/", "\\"))
    finally:
        path.unlink(missing_ok=True)


def _is_dxvk(path):
    try:
        return b"DXVK" in path.read_bytes()
    except OSError:
        return False


def _remove_prefix_dxvk(options):
    """Earlier versions put DXVK into the prefix's system32. It now lives next
    to Studio (so that the renderer can change); restore Wine's own DLLs."""
    windows = PREFIX / "drive_c" / "windows"
    if not _is_dxvk(windows / "system32" / "d3d11.dll"):
        return
    for folder in ("system32", "syswow64"):
        for name in DXVK_DLLS:
            (windows / folder / name).unlink(missing_ok=True)
    _quiet_wine(options, "wineboot", "-u")


def _ensure_prefix(state, progress, options=None):
    options = options or Options()
    identity = _wine_identity(state, options)
    fresh = not (PREFIX / "system.reg").exists()
    # A "dxvk" entry in the state is from before DXVK moved next to Studio.
    if state.get("prefix") == identity and not fresh and "dxvk" not in state:
        return
    if fresh or state.get("prefix") != identity:
        progress(0, _("Preparing Wine"))
        _quiet_wine(options, "wineboot", "--init" if fresh else "-u")
    if fresh:
        # Studio's folders belong to the user, not to a prefix that may be recreated.
        APPDATA.mkdir(parents=True, exist_ok=True)
        _import_registry(options, studio_registry.folders_reg(
            APPDATA, _user_directory("DOCUMENTS", "Documents"), _user_directory("PICTURES", "Pictures")))
        restore_settings(options)
        # Wine reads the shell folders when it starts.
        _wineserver("-k", options=options)
        _wineserver("--wait", options=options)
        state.pop("theme", None)
    _remove_prefix_dxvk(options)
    state["prefix"] = identity
    state.pop("dxvk", None)
    state.pop("dxvk_applied", None)
    _save_state(state)


def _ensure_webview(state, progress, options):
    wine = lambda *arguments: _quiet_wine(options, *arguments)
    studio_webview.ensure(PREFIX, wine, _download, core.DOWNLOADS, studio_webview.VERSION, progress)
    state["webview"] = studio_webview.VERSION
    _save_state(state)


def _ensure_graphics(state, progress, options):
    """DXVK's DLLs next to Studio, for the renderer chosen in Settings."""
    variant = options.dxvk
    present = [name for name in DXVK_DLLS if (APP / name).exists()]
    if variant is None:
        for name in present:
            (APP / name).unlink()
        if state.pop("dxvk_applied", None):
            _save_state(state)
        return
    if variant == "sarek":
        wanted, url, name = f"sarek-{SAREK_VERSION}", SAREK_URL, SAREK_URL.rsplit("/", 1)[1]
    else:
        try:
            tag = _latest_tag(DXVK_RELEASES)
        except OSError:
            if present and str(state.get("dxvk_applied", "")).startswith("dxvk-"):
                return  # offline: keep the DXVK we have
            raise
        wanted, name = f"dxvk-{tag}", f"dxvk-{tag.lstrip('v')}.tar.gz"
        url = f"{DXVK_RELEASES}/releases/download/{tag}/{name}"
    if state.get("dxvk_applied") == wanted and present:
        return
    archive = core.DOWNLOADS / name
    if not archive.exists():
        _download(url, archive, progress, "DXVK")
    for stale in present:
        (APP / stale).unlink()
    with tarfile.open(archive) as bundle:
        for member in bundle.getmembers():
            path = Path(member.name)
            if member.isfile() and path.suffix == ".dll" and path.parent.name == "x64":
                with bundle.extractfile(member) as source, open(APP / path.name, "wb") as out:
                    shutil.copyfileobj(source, out)
    state["dxvk_applied"] = wanted
    _save_state(state)


def latest_version():
    """The newest Studio deployment on Roblox's public channel."""
    return studio_deploy.newest()


def _cookie():
    try:
        return studio_registry.roblosecurity((PREFIX / "user.reg").read_text(errors="replace"))
    except OSError:
        return None


def deployment(options):
    """(version, channel) of the Studio to run: pinned in Settings, or the
    newest on the chosen channel (the signed-in account's by default)."""
    return studio_deploy.resolve(options.version, options.channel, _cookie)


def _manifest(version, channel=""):
    """[(name, md5, packed size)] from rbxPkgManifest.txt."""
    with studio_deploy.open_first(studio_deploy.package_urls(version, channel, "rbxPkgManifest.txt"),
                                  timeout=30) as response:
        lines = response.read().decode().split()
    if not lines or lines[0] != "v0":
        raise RuntimeError(_("Unknown Studio package manifest format"))
    return [(lines[i], lines[i + 1], int(lines[i + 2])) for i in range(1, len(lines) - 3, 4)]


def _extract(archive, target):
    with zipfile.ZipFile(archive) as bundle:
        for entry in bundle.infolist():
            name = entry.filename.replace("\\", "/").lstrip("/")
            if not name or name.endswith("/") or ".." in Path(name).parts:
                continue
            path = target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(entry) as source, open(path, "wb") as out:
                shutil.copyfileobj(source, out, 1 << 20)


def _install_studio(state, version, channel, progress, options):
    packages = [p for p in _manifest(version, channel) if p[0] not in SKIPPED_PACKAGES]
    unknown = [name for name, _md5, _size in packages if name not in PACKAGE_DIRS]
    if unknown:
        # A new package: Roblox's bootstrapper knows its folder, we do not yet.
        core.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (core.CACHE_DIR / "studio-unknown-packages.txt").write_text("\n".join(unknown) + "\n")
    total = sum(size for _name, _md5, size in packages) or 1
    done = 0
    staging = APP.with_name(APP.name + ".new")
    shutil.rmtree(staging, ignore_errors=True)
    folder = core.DOWNLOADS / f"studio-{version}"

    def fetch(package):
        name, md5, _size = package
        archive = folder / name
        for _attempt in range(3):
            digest = hashlib.md5()  # hashed while downloading: no second read
            try:
                _download(studio_deploy.package_urls(version, channel, name), archive, digest=digest)
            except OSError:
                continue
            if digest.hexdigest() == md5:
                return package, archive
        raise RuntimeError(_("{name} failed its checksum", name=name))

    with ThreadPoolExecutor(max_workers=4) as pool:
        for (name, _md5, size), archive in pool.map(fetch, packages):
            done += size
            progress(done / total, _("Roblox Studio: {done} of {total} MB",
                                     done=done >> 20, total=total >> 20))
            _extract(archive, staging / PACKAGE_DIRS.get(name, ""))
            archive.unlink()
    (staging / "AppSettings.xml").write_text(APP_SETTINGS)
    shutil.rmtree(folder, ignore_errors=True)
    shutil.rmtree(APP, ignore_errors=True)
    staging.rename(APP)
    # Studio reads its channel from the registry (the public one is the absence of a value).
    if studio_deploy.is_live(channel):
        _quiet_wine(options, "reg", "delete", CHANNEL_KEY, "/v", "www.roblox.com", "/f")
    else:
        _quiet_wine(options, "reg", "add", CHANNEL_KEY, "/v", "www.roblox.com", "/d", channel, "/f")
    state["studio"], state["channel"] = version, channel
    state.pop("dxvk_applied", None)  # the folder was replaced, DXVK's DLLs with it
    _save_state(state)


def install(progress=lambda fraction, text: None, settings=None):
    """Installs or updates everything Studio needs. progress(fraction, text)
    gets the fraction of the whole job."""
    options = Options(core.load_settings() if settings is None else settings)
    state = _state()
    _private_root()
    steps = []
    if wine_root(options) == WINE:
        steps.append((0.00, 0.15, lambda p: _ensure_wine(state, p, options)))
    steps.append((0.15, 0.20, lambda p: _ensure_prefix(state, p, options)))
    if options.webview:
        steps.append((0.20, 0.35, lambda p: _ensure_webview(state, p, options)))
    try:
        version, channel = deployment(options)
    except studio_deploy.BadChannel as error:
        raise ChannelError(_("The Studio channel {channel} does not exist or is not open to this account",
                             channel=str(error))) from None
    except OSError:
        if not installed_version():
            raise
        version = None  # offline: the installed Studio is started as it is
    if version and (version != installed_version() or channel != state.get("channel", "")):
        steps.append((0.35, 0.95, lambda p: _install_studio(state, version, channel, p, options)))
    steps.append((0.95, 1.00, lambda p: _ensure_graphics(state, p, options)))
    for start, end, step in steps:
        step(lambda fraction, text, s=start, e=end: progress(s + (e - s) * min(fraction, 1), text))
    progress(1, _("Done"))


def needs_install():
    state = _state()
    return not (installed_version() and (state.get("wine") or wine_root(Options(core.load_settings())) != WINE))


def running():
    return any(re.search(r"RobloxStudioBeta\.exe", args) for _pid, args in core._user_processes())


def _wine_argument(argument):
    """A place file as Studio under Wine must get it (Z: is the Linux root),
    also when a file manager passes a file:// URL; links stay as they are."""
    if argument.startswith("file://"):
        argument = urllib.parse.unquote(urllib.parse.urlsplit(argument).path)
    if argument.startswith("/") and os.path.isfile(argument):
        return "Z:" + argument.replace("/", "\\")
    return argument


def system_prefers_dark():
    """The desktop's light/dark preference; light when it cannot be read."""
    try:
        result = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                                capture_output=True, text=True, timeout=3)
        return "dark" in result.stdout
    except (OSError, subprocess.SubprocessError):
        return False


def _apply_theme(state, options, dark=None):
    if not options.theme:
        return
    dark = system_prefers_dark() if dark is None else dark
    wanted = "dark" if dark else "light"
    if state.get("theme") == wanted:
        return
    _import_registry(options, studio_registry.theme_reg(dark))
    state["theme"] = wanted
    _save_state(state)


def _apply_files(options):
    """What Studio reads from its own folder: the overlay, then the flags."""
    if OVERLAY.is_dir():
        shutil.copytree(OVERLAY, APP, dirs_exist_ok=True)
    flags = dict(options.fflags)
    api = RENDERERS[options.renderer][0]
    for name in GRAPHICS_APIS:
        flags[f"FFlagDebugGraphicsPrefer{name}"] = name == api
        flags[f"FFlagDebugGraphicsDisable{name}"] = name != api
    folder = APP / "ClientSettings"
    folder.mkdir(exist_ok=True)
    (folder / "ClientAppSettings.json").write_text(json.dumps(flags, indent=2))


def backup_settings(options=None):
    """Saves Studio's sign-in and settings outside the prefix."""
    options = options or Options()
    if not (PREFIX / "system.reg").exists():
        return False
    BACKUPS.mkdir(parents=True, exist_ok=True)
    BACKUPS.chmod(0o700)
    saved = False
    for name, key in BACKUP_KEYS.items():
        target = BACKUPS / f"{name}.reg"
        partial = BACKUPS / f"{name}.reg.part"
        result = _wine(  # a missing key makes reg fail: nothing to save then
            "reg", "export", key, "Z:" + str(partial).replace("/", "\\"), "/y", options=options,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode == 0 and partial.exists():
            partial.chmod(0o600)
            partial.replace(target)
            saved = True
        partial.unlink(missing_ok=True)
    _wineserver("--wait", options=options)
    return saved


def restore_settings(options=None):
    """Puts a saved sign-in and settings back into a new prefix."""
    options = options or Options()
    restored = False
    for name in BACKUP_KEYS:
        path = BACKUPS / f"{name}.reg"
        if path.is_file():
            result = _wine("reg", "import", "Z:" + str(path).replace("/", "\\"), options=options,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            restored = restored or result.returncode == 0
    _wineserver("--wait", options=options)
    return restored


def _prepare(options):
    """Everything a start needs that can change without a download."""
    state = _state()
    _apply_theme(state, options)
    _apply_files(options)


def launch(arguments=(), settings=None):
    """Starts Studio; arguments are roblox-studio: or roblox-studio-auth:
    links and place files, passed on like the Windows protocol handler. The
    process has a `log_path`: Studio's output, Wine's debug channel."""
    options = Options(core.load_settings() if settings is None else settings)
    arguments = [_wine_argument(argument) for argument in arguments]
    _prepare(options)
    core.LOGS.mkdir(parents=True, exist_ok=True)
    old = sorted(core.LOGS.glob("studio-*.log"), key=lambda path: path.stat().st_mtime)
    for path in old[:-9]:
        path.unlink(missing_ok=True)
    log_path = core.LOGS / time.strftime("studio-%Y%m%d-%H%M%S.log")
    out = open(log_path, "wb")
    process = subprocess.Popen([str(wine_root(options) / "bin" / "wine"), str(EXECUTABLE), *arguments],
                               cwd=str(APP), env=_wine_env(options, launching=True), stdin=subprocess.DEVNULL,
                               stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
    out.close()
    process.log_path = log_path
    return process


def _follow(path, feed, stop):
    """Hands each new line of a growing log to `feed` until `stop` is set."""
    with open(path, "rb") as source:
        pending = b""
        while True:
            chunk = source.read(1 << 16)
            if chunk:
                *lines, pending = (pending + chunk).split(b"\n")
                for line in lines:
                    if b"FLog::" in line:
                        feed(line.decode("utf-8", "replace"))
            elif stop.wait(0.3):
                return


def _supervisor_lock():
    """Only one process looks after a running Studio (presence, GameMode,
    the backup): the first. Later starts, such as the browser handing over a
    sign-in, only launch."""
    _private_root()
    handle = open(SUPERVISOR_LOCK, "a")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def supervise(process, options):
    """Looks after a started Studio until it and everything it started have
    ended: GameMode, Discord presence from its log, then the settings backup."""
    stop = threading.Event()
    presence = follower = None
    if options.gamemode:
        threading.Thread(target=studio_gamemode.register, args=(process.pid,), daemon=True).start()
    if options.discord:
        from . import discord, studio_presence
        try:
            presence = studio_presence.StudioPresence(discord.DiscordRPC())
        except RuntimeError as error:
            log.info("Discord presence is not available: %s", error)
    if presence:
        follower = threading.Thread(target=_follow, args=(process.log_path, presence.feed, stop), daemon=True)
        follower.start()
    process.wait()
    try:
        _wineserver("--wait", options=options, timeout=120)
    except subprocess.TimeoutExpired:
        log.warning("Studio's Wine did not end; leaving it running")
    stop.set()
    if follower:
        follower.join(2)
    if options.backup:
        try:
            backup_settings(options)
        except (OSError, subprocess.SubprocessError) as error:
            log.warning("Could not back up Studio's settings: %s", error)
    if presence:
        presence.close()


def run(arguments=(), settings=None, update=True):
    """Starts Studio and stays until it closes (the caller is a process of its
    own: the `quadrahq --studio` that links and place files open). With
    `update`, a Studio that is not running yet is brought up to date first."""
    settings = core.load_settings() if settings is None else settings
    options = Options(settings)
    if update and not running():
        try:
            install(settings=settings)
        except (OSError, RuntimeError) as error:
            if needs_install():
                raise
            log.warning("Studio update skipped: %s", error)
    lock = _supervisor_lock()
    process = launch(arguments, settings)
    if lock is None:
        return 0
    try:
        supervise(process, options)
    finally:
        lock.close()
    return 0


def spawn(arguments=()):
    """Starts `quadrahq --studio` as a process of its own, so that Studio's
    GameMode, presence and settings backup outlive the launcher window."""
    entry = Path(__file__).resolve().parents[1] / "quadrahq-launcher"
    return subprocess.Popen([sys.executable, str(entry), "--studio", "--no-update", *arguments],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True)
