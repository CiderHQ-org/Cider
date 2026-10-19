"""Renderers other than OpenGL: Mesa Zink, and Metal on Vulkan.

- "vulkan": Roblox keeps its macOS OpenGL renderer; Mesa Zink runs it on
  Vulkan.
- "metal": Roblox runs its Metal renderer. Quadra's Metal.framework
  (prototype/metal-vulkan/framework) replaces Darling's and runs each call on the host's
  Vulkan driver through metal2vulkan (prototype/metal-vulkan/host). Roblox's macOS client has
  no Vulkan backend of its own (its device factory makes OpenGL and Metal
  devices only), so this is the native Vulkan route.
"""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import threading

RENDERERS = ("opengl", "vulkan", "metal")
_dependency_lock = threading.Lock()


def mesa_egl_manifest():
    # Inside Flatpak, Mesa comes from the GL extension (GL/default), not /usr/share.
    roots = ["/usr/share", "/usr/local/share", "/etc", "/app/share"]
    roots += [str(path) for path in sorted(Path("/usr/lib/x86_64-linux-gnu/GL").glob("*/share"))]
    return next((Path(root) / "glvnd/egl_vendor.d/50_mesa.json" for root in roots
                 if (Path(root) / "glvnd/egl_vendor.d/50_mesa.json").is_file()), None)


def missing_vulkan_dependencies():
    missing = []
    if mesa_egl_manifest() is None:
        missing.append("Mesa EGL")
    roots = ("/usr/lib", "/usr/lib64", "/usr/lib/x86_64-linux-gnu", "/usr/local/lib",
             "/usr/local/lib64", "/app/lib", "/app/lib/x86_64-linux-gnu",
             "/usr/lib/x86_64-linux-gnu/GL/default/lib", "/usr/lib/GL/default/lib")
    extra = os.environ.get("LIBGL_DRIVERS_PATH", "").split(":")
    paths = [Path(root) / "dri/zink_dri.so" for root in roots]
    paths.extend(Path(root) / "zink_dri.so" for root in extra if root)
    if not any(path.is_file() for path in paths):
        missing.append("Zink")
    return missing


def _system_program(name):
    # Package managers execute as root: use system directories rather than a
    # launcher process's possibly customized PATH.
    return next((str(Path(root) / name) for root in ("/usr/bin", "/bin", "/usr/sbin", "/sbin")
                 if (Path(root) / name).is_file() and os.access(Path(root) / name, os.X_OK)), None)


def _askpass_program():
    configured = os.environ.get("SUDO_ASKPASS", "")
    if os.path.isabs(configured) and Path(configured).is_file() and os.access(configured, os.X_OK):
        return configured
    for name in ("ksshaskpass", "ssh-askpass"):
        executable = _system_program(name)
        if executable:
            return executable
    return next((path for path in ("/usr/lib/ssh/ssh-askpass", "/usr/libexec/openssh/ssh-askpass",
                                  "/usr/lib/openssh/gnome-ssh-askpass", "/usr/lib/gcr-ssh-askpass",
                                  "/usr/lib/gcr4-ssh-askpass", "/usr/lib/git-core/git-gui--askpass")
                 if Path(path).is_file() and os.access(path, os.X_OK)), None)


def _authenticated_install_command(command):
    """Choose one available prompt. Never retry after denied authentication."""
    run0 = _system_program("run0")
    if run0:
        # Default interactive polkit authentication enables the desktop prompt.
        return [run0, "--description=Install Quadra Vulkan dependencies", "--", *command], {}
    pkexec = _system_program("pkexec")
    if pkexec:
        return [pkexec, *command], {}
    sudo = _system_program("sudo")
    if sudo:
        askpass = _askpass_program()
        if askpass:
            # sudo reads the helper's output directly; the launcher never sees
            # or stores the password.
            return [sudo, "-A", "--", *command], {"SUDO_ASKPASS": askpass}
        terminals = (("gnome-terminal", ["--wait", "--"]),
                     ("konsole", ["--separate", "-e"]),
                     ("xfce4-terminal", ["--disable-server", "--execute"]),
                     ("kitty", ["--"]), ("alacritty", ["-e"]),
                     ("foot", ["--"]), ("xterm", ["-e"]))
        for name, arguments in terminals:
            terminal = _system_program(name)
            if terminal:
                return [terminal, *arguments, sudo, "--", *command], {}
    raise RuntimeError("No administrator prompt is available. Install run0 or pkexec, or sudo with a graphical askpass helper or terminal, then select Vulkan again. You can also install Mesa EGL and Zink manually.")


def vulkan_install_command():
    """Return (argv, environment overrides), using fixed package arguments."""
    if Path("/.flatpak-info").is_file():
        raise RuntimeError("Mesa EGL and Zink come from the Flatpak graphics runtime. Update the Flatpak runtime and try again.")
    try:
        release = platform.freedesktop_os_release()
    except OSError:
        release = {}
    family = {release.get("ID", ""), *release.get("ID_LIKE", "").split()}
    choices = (({"arch"}, "pacman", ["-S", "--needed", "--noconfirm", "mesa", "vulkan-icd-loader"]),
               ({"debian", "ubuntu"}, "apt-get", ["install", "-y", "--no-install-recommends", "libegl-mesa0", "libgl1-mesa-dri", "libvulkan1"]),
               ({"fedora", "rhel"}, "dnf", ["install", "-y", "mesa-libEGL", "mesa-dri-drivers", "vulkan-loader"]))
    identified = any(family & ids for ids, _manager, _arguments in choices)
    for ids, manager, arguments in choices:
        executable = _system_program(manager)
        if executable and (family & ids or not identified):
            return _authenticated_install_command([executable, *arguments])
    raise RuntimeError("Automatic Vulkan dependency installation supports Arch, Debian/Ubuntu and Fedora. Install Mesa EGL and Zink with your package manager.")


def ensure_vulkan_dependencies():
    """Install only when files are missing; check again after authentication."""
    with _dependency_lock:
        if not missing_vulkan_dependencies():
            return False
        command, auth_environment = vulkan_install_command()
        result = subprocess.run(command, env={**os.environ, **auth_environment},
                                stdin=subprocess.DEVNULL, capture_output=True, text=True)
        if result.returncode:
            detail = "\n".join(part.strip() for part in (result.stderr, result.stdout) if part.strip())[-1500:]
            raise RuntimeError("Vulkan dependencies were not installed. Authentication may have been cancelled.\n" + detail)
        missing = missing_vulkan_dependencies()
        if missing:
            raise RuntimeError("Installation finished, but these dependencies are still missing: " + ", ".join(missing))
        return True


def mangohud_environment(renderer, enabled=False):
    """Enable the Vulkan layer or the shim's direct host EGL overlay hook.

    Avoid OpenGL LD_PRELOAD: Darling strips it from host commands, and
    forwarding MangoHud's dlsym hook to the guest can select software GL.
    The Settings switch controls activation, including when the desktop or a
    running Darling server inherited an overlay enabled by an earlier launch.
    """
    variables = {"MANGOHUD": "1" if enabled else "0", "MACOBLOX_MANGOHUD_OPENGL": ""}
    if not enabled:
        return variables
    variables.update({name: os.environ[name] for name in
                      ("MANGOHUD_CONFIG", "MANGOHUD_CONFIGFILE") if name in os.environ})
    if variables.get("MANGOHUD") == "1" and renderer == "opengl":
        roots = ("/usr/lib/mangohud", "/usr/lib64/mangohud",
                 "/usr/lib/x86_64-linux-gnu/mangohud", "/usr/local/lib/mangohud",
                 "/usr/local/lib64/mangohud", "/app/lib/mangohud",
                 "/app/lib/x86_64-linux-gnu/mangohud",
                 "/usr/lib/extensions/vulkan/MangoHud/lib/mangohud",
                 "/usr/lib/extensions/vulkan/MangoHud/lib/x86_64-linux-gnu",
                 str(Path.home() / ".local/share/MangoHud/usr/lib/mangohud"))
        libraries = [Path(root) / "libMangoHud_opengl.so" for root in roots]
        custom = os.environ.get("MANGOHUD_OPENGL_LIBS")
        if custom:
            libraries[:0] = [Path(path) for path in custom.split(":") if path]
        library = next((path for path in libraries if path.is_file()), None)
        if library is None:
            raise RuntimeError("MangoHud's OpenGL library is missing. Install MangoHud or turn it off in Settings.")
        variables["MACOBLOX_MANGOHUD_OPENGL"] = str(library)
    return variables


def vulkan_loader():
    """The host's Vulkan loader, or None."""
    roots = ("/usr/lib", "/usr/lib64", "/usr/lib/x86_64-linux-gnu", "/usr/local/lib",
             "/usr/local/lib64", "/app/lib", "/app/lib/x86_64-linux-gnu")
    return next((str(Path(root) / "libvulkan.so.1") for root in roots
                 if (Path(root) / "libvulkan.so.1").exists()), None)


def missing_metal_dependencies():
    return [] if vulkan_loader() else ["Vulkan loader"]


def metal_environment(metal_dir, shader_cache):
    """Host and guest variables of the Metal renderer. metal_dir holds
    Metal.framework and libquadra_metal_host.so (prototype/metal-vulkan/build.sh)."""
    metal_dir = Path(metal_dir)
    return {
        "MACOBLOX_METAL": "1",
        # dlopened by the host side of Darling: a host path.
        "MACOBLOX_METAL_HOST_LIBRARY": str(metal_dir / "libquadra_metal_host.so"),
        # Read by the host library; HOME is /Users/<name> inside Darling.
        "MACOBLOX_METAL_SHADER_CACHE": str(shader_cache),
    }


def validate_metal(environment, host_library):
    """Open the Vulkan device the game will use, in a separate process."""
    probe_environment = {name: value for name, value in environment.items() if name != "LD_PRELOAD"}
    try:
        result = subprocess.run([sys.executable, str(Path(__file__)), "--metal-probe", str(host_library)],
                                env=probe_environment, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError("Metal on Vulkan could not open a Vulkan device. Select OpenGL in Settings.") from error
    try:
        data = json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        data = {}
    name = data.get("device", "")
    if result.returncode or not name:
        reason = data.get("error") or (result.stderr or "").strip()[-600:] or f"probe exited with code {result.returncode}"
        raise RuntimeError(f"Metal on Vulkan is unavailable: {reason}. Select OpenGL in Settings.")
    if any(software in name.lower() for software in ("llvmpipe", "lavapipe", "swiftshader")):
        raise RuntimeError(f"Metal on Vulkan found only a software Vulkan device ({name}). Install your GPU's Vulkan driver or select OpenGL.")
    return name


def _metal_probe(library):
    """quadra_metal.h's device_create and device_info, nothing else."""
    host = ctypes.CDLL(library)
    entry = host.quadra_metal_host_api
    entry.restype, entry.argtypes = ctypes.c_void_p, (ctypes.c_uint32,)
    api = entry(1)
    if not api:
        raise RuntimeError("the Metal host library is from another version of Quadra")
    pointer = ctypes.c_void_p
    words = ctypes.cast(api + 8, ctypes.POINTER(pointer))  # after version and size
    last_error = ctypes.CFUNCTYPE(ctypes.c_char_p)(words[0])
    release = ctypes.CFUNCTYPE(None, pointer)(words[1])
    device_create = ctypes.CFUNCTYPE(pointer, pointer)(words[2])
    device_info = ctypes.CFUNCTYPE(None, pointer, ctypes.c_char_p)(words[3])
    device = device_create(None)
    if not device:
        raise RuntimeError((last_error() or b"no Vulkan device").decode(errors="replace"))
    info = ctypes.create_string_buffer(512)
    device_info(device, info)
    name = info.raw[:256].split(b"\0", 1)[0].decode(errors="replace")
    release(device)
    return {"device": name}


def renderer_environment(renderer):
    if renderer == "opengl":
        return {}
    if renderer == "metal":
        # The paths come from the launcher (metal_environment); Darling's
        # own compositor keeps using EGL as with OpenGL.
        return {"MACOBLOX_METAL": "1"}
    if renderer != "vulkan":
        raise ValueError(f"Unknown renderer: {renderer}")
    # GLVND would otherwise choose NVIDIA's EGL implementation, ignoring
    # Mesa's driver override entirely. These are host paths, also in Flatpak.
    manifest = mesa_egl_manifest()
    if manifest is None:
        raise RuntimeError("Vulkan (Zink) needs Mesa EGL and Zink. Install them or select OpenGL in Settings.")
    return {
        "MESA_LOADER_DRIVER_OVERRIDE": "zink",
        "GALLIUM_DRIVER": "zink",
        "__EGL_VENDOR_LIBRARY_FILENAMES": str(manifest),
        "EGL_PLATFORM": "x11",
        "MACOBLOX_METAL": "0",
    }


def wayland_vulkan_environment():
    """Add NVIDIA's X11-independent ICD without replacing other drivers."""
    filters = {name: os.environ[name] for name in
               ("VK_LOADER_DRIVERS_SELECT", "VK_LOADER_DRIVERS_DISABLE")
               if name in os.environ}
    overrides = {name: os.environ[name] for name in
                 ("VK_DRIVER_FILES", "VK_ICD_FILENAMES", "VK_ADD_DRIVER_FILES")
                 if name in os.environ}
    if overrides:
        return {**filters, **overrides}
    # NVIDIA also exposes Vulkan through its EGL library. Its default GLX
    # ICD can fail without DISPLAY, even when /dev/dri is fully accessible.
    # Use an additional manifest: the loader keeps its ordinary ICD search,
    # including AMD/Intel drivers on machines with more than one GPU.
    roots = [Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))]
    roots.extend(Path(root) for root in os.environ.get("XDG_CONFIG_DIRS", "/etc/xdg").split(":") if root)
    roots.extend(Path(root) for root in ("/usr/local/etc", "/etc"))
    roots.append(Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")))
    roots.extend(Path(root) for root in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":") if root)
    roots.append(Path("/app/share"))
    roots.extend(path / "share" for path in
                 sorted(Path("/usr/lib/x86_64-linux-gnu/GL").glob("*")))
    manifest = None
    for root in roots:
        for path in sorted((root / "vulkan/icd.d").glob("*.json")):
            try:
                candidate = json.loads(path.read_text())
                library = candidate["ICD"]["library_path"]
                if not isinstance(library, str) or Path(library).name != "libGLX_nvidia.so.0":
                    continue
                if candidate["ICD"].get("library_arch") == "32":
                    continue
                replacement = library.replace("libGLX_nvidia.so.0", "libEGL_nvidia.so.0")
                if "/" in replacement:
                    egl = Path(replacement)
                    egl = egl if egl.is_absolute() else path.parent / egl
                else:
                    libraries = [Path(root) for root in os.environ.get("LD_LIBRARY_PATH", "").split(":") if root]
                    libraries.extend(Path(root) for root in
                                     ("/usr/lib", "/usr/lib64", "/usr/lib/x86_64-linux-gnu",
                                      "/usr/lib/x86_64-linux-gnu/nvidia/current", "/usr/lib/nvidia/current",
                                      "/usr/local/lib", "/app/lib", "/app/lib/x86_64-linux-gnu"))
                    libraries.extend(root.parent / "lib" for root in roots if root.name == "share")
                    egl = next((root / replacement for root in libraries
                                if (root / replacement).is_file()), None)
                if egl is None or not egl.is_file():
                    continue
                candidate["ICD"]["library_path"] = str(egl.resolve())
                manifest = candidate
                basename = path.name
                break
            except (OSError, ValueError, KeyError, TypeError):
                continue
        if manifest is not None:
            break
    if manifest is None:
        return filters
    payload = json.dumps(manifest, sort_keys=True, indent=2) + "\n"
    digest = hashlib.sha256(payload.encode()).hexdigest()[:16]
    cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "macoblox/vulkan"
    # Preserve the source basename: Vulkan loader select/disable filters
    # match manifest names, so the extra ICD obeys the same user filters.
    target = (cache / f"nvidia-egl-{digest}" / basename).absolute()
    temporary = None
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file() or target.read_text() != payload:
            with tempfile.NamedTemporaryFile(mode="w", dir=target.parent, prefix=".nvidia-egl-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
            temporary.replace(target)
    except OSError as error:
        raise RuntimeError("Native Wayland Vulkan could not prepare its NVIDIA driver cache. Select X11 in Settings.") from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {**filters, "VK_ADD_DRIVER_FILES": str(target)}


def validate_vulkan(environment):
    """Keep driver initialization (and a possible driver crash) out of GTK."""
    # LD_PRELOAD holds Darling's no-root library (Flatpak). It is meant for
    # darling/darlingserver only and crashes this plain host process once
    # Mesa and the GPU driver load, so the probe runs without it.
    probe_environment = {name: value for name, value in environment.items() if name != "LD_PRELOAD"}
    try:
        result = subprocess.run([sys.executable, str(Path(__file__)), "--probe"],
                                env=probe_environment, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError("Vulkan (Zink) could not initialize. Select OpenGL in Settings.") from error
    try:
        data = json.loads(result.stdout)
    except ValueError:
        data = {}
    renderer = data.get("renderer", "")
    if result.returncode or not hardware_zink(renderer):
        reason = data.get("error") or renderer
        if not reason:
            # Show why the probe died instead of a generic message.
            tail = "\n".join(part.strip() for part in (result.stderr or "", result.stdout or "") if part.strip())[-600:]
            reason = f"probe exited with code {result.returncode} and no usable output" + (f":\n{tail}" if tail else "")
        raise RuntimeError(f"Vulkan (Zink) is unavailable: {reason}. Select OpenGL in Settings.")
    return renderer


def hardware_zink(renderer):
    name = renderer.lower()
    return "zink" in name and not any(software in name for software in
                                      ("llvmpipe", "lavapipe", "softpipe", "software", "swiftshader"))


def _probe():
    """Exercise a real screen-visual window, core/compat and shared threads.

    Pbuffers can succeed when an EGL config cannot present to the X11 visual
    Darling uses. The worker also starts with EGL's default ES API, as a new
    Roblox render thread does; bind desktop GL separately on each thread.
    """
    egl, xlib = ctypes.CDLL("libEGL.so.1"), ctypes.CDLL("libX11.so.6")
    ptr, integer, uint = ctypes.c_void_p, ctypes.c_int, ctypes.c_uint

    def function(library, name, result, *arguments):
        fn = getattr(library, name)
        fn.restype, fn.argtypes = result, arguments
        return fn

    open_display = function(xlib, "XOpenDisplay", ptr, ctypes.c_char_p)
    close_display = function(xlib, "XCloseDisplay", integer, ptr)
    default_screen = function(xlib, "XDefaultScreen", integer, ptr)
    default_visual = function(xlib, "XDefaultVisual", ptr, ptr, integer)
    visual_id = function(xlib, "XVisualIDFromVisual", ctypes.c_ulong, ptr)
    root_window = function(xlib, "XRootWindow", ctypes.c_ulong, ptr, integer)
    create_window = function(xlib, "XCreateSimpleWindow", ctypes.c_ulong,
                             ptr, ctypes.c_ulong, integer, integer, uint, uint,
                             uint, ctypes.c_ulong, ctypes.c_ulong)
    map_window = function(xlib, "XMapWindow", integer, ptr, ctypes.c_ulong)
    destroy_window = function(xlib, "XDestroyWindow", integer, ptr, ctypes.c_ulong)
    sync = function(xlib, "XSync", integer, ptr, integer)
    get_display = function(egl, "eglGetDisplay", ptr, ptr)
    initialize = function(egl, "eglInitialize", integer, ptr, ptr, ptr)
    bind = function(egl, "eglBindAPI", integer, uint)
    choose = function(egl, "eglChooseConfig", integer, ptr, ptr, ptr, integer, ptr)
    config_attr = function(egl, "eglGetConfigAttrib", integer, ptr, ptr, integer, ptr)
    create_surface = function(egl, "eglCreateWindowSurface", ptr, ptr, ptr, ctypes.c_ulong, ptr)
    create_context = function(egl, "eglCreateContext", ptr, ptr, ptr, ptr, ptr)
    make_current = function(egl, "eglMakeCurrent", integer, ptr, ptr, ptr, ptr)
    swap = function(egl, "eglSwapBuffers", integer, ptr, ptr)
    get_proc = function(egl, "eglGetProcAddress", ptr, ctypes.c_char_p)
    destroy_context = function(egl, "eglDestroyContext", integer, ptr, ptr)
    destroy_surface = function(egl, "eglDestroySurface", integer, ptr, ptr)
    query_surface = function(egl, "eglQuerySurface", integer, ptr, ptr, integer, ptr)
    terminate = function(egl, "eglTerminate", integer, ptr)
    wayland_window = None
    if os.environ.get("MACOBLOX_WAYLAND") == "1":
        try:
            from .display import WaylandProbeWindow
        except ImportError:  # this file runs directly in the probe subprocess
            from display import WaylandProbeWindow
        wayland_window = WaylandProbeWindow()
    native = wayland_window.native if wayland_window else open_display(None)
    if not native:
        raise RuntimeError("X11 display is unavailable")
    display = surface = context = secondary_surface = None
    window = 0
    initialized = False
    try:
        display = get_display(native)
        if not display or not initialize(display, None, None):
            raise RuntimeError("EGL could not initialize the selected window backend")
        initialized = True
        if not bind(0x30A2):  # EGL_OPENGL_API
            raise RuntimeError("desktop OpenGL is unavailable")
        # Match the real default visual, which the guest GL subwindow uses.
        screen = default_screen(native) if not wayland_window else 0
        required_visual = visual_id(default_visual(native, screen)) if not wayland_window else None
        attrs = (integer * 9)(0x3033, 5, 0x3040, 8, 0x3024, 8, 0x3025, 0, 0x3038)
        configs, count = (ptr * 256)(), integer()
        if not choose(display, attrs, configs, len(configs), ctypes.byref(count)) or not count.value:
            raise RuntimeError("no desktop OpenGL window EGL configuration")
        config = None
        for candidate in configs[:min(count.value, len(configs))]:
            if wayland_window:
                config = candidate
                break
            value = integer()
            if config_attr(display, candidate, 0x302E, ctypes.byref(value)) and value.value == required_visual:
                config = candidate
                break
        if not config:
            raise RuntimeError("no EGL window config matches the X11 screen visual")
        window = wayland_window.surface if wayland_window else create_window(
            native, root_window(native, screen), 0, 0, 16, 16, 0, 0, 0)
        if not window:
            raise RuntimeError("could not create an X11 test window")
        if not wayland_window:
            map_window(native, window)
            sync(native, 0)
        surface = create_surface(display, config, window, None)
        if not surface:
            raise RuntimeError("could not create an EGL window surface for the screen visual")
        secondary_drawable = None
        if wayland_window:
            # AppKit's main GL view and CALayer renderer own concurrent native
            # drawables. A parent-only probe missed the old shared-window bug.
            secondary_drawable = wayland_window.create_drawable(0, 0, 16, 16)
            secondary_native = wayland_window.api.subwindow_surface(secondary_drawable)
            if not secondary_native or secondary_native == window:
                raise RuntimeError("Native Wayland views must have separate EGL drawables")
            secondary_surface = create_surface(display, config, secondary_native, None)
            if not secondary_surface:
                raise RuntimeError("could not create concurrent Native Wayland EGL view surfaces")

        def gl_function(name, result, *arguments):
            address = get_proc(name.encode())
            if not address:
                raise RuntimeError(f"{name} is unavailable")
            return ctypes.CFUNCTYPE(result, *arguments)(address)

        get_string = gl_function("glGetString", ctypes.c_char_p, uint)
        clear_color = gl_function("glClearColor", None, ctypes.c_float, ctypes.c_float,
                                  ctypes.c_float, ctypes.c_float)
        clear = gl_function("glClear", None, uint)
        read_pixels = gl_function("glReadPixels", None, integer, integer, integer, integer, uint, uint, ptr)
        get_error = gl_function("glGetError", uint)
        gen_textures = gl_function("glGenTextures", None, integer, ptr)
        bind_texture = gl_function("glBindTexture", None, uint, uint)
        is_texture = gl_function("glIsTexture", ctypes.c_ubyte, uint)
        delete_textures = gl_function("glDeleteTextures", None, integer, ptr)
        core_attrs = (integer * 7)(0x3098, 4, 0x30FB, 1, 0x30FD, 1, 0x3038)
        renderer = ""

        def present(drawable=None):
            clear_color(0.25, 0.5, 0.75, 1.0)
            clear(0x4000)  # GL_COLOR_BUFFER_BIT
            pixel = (ctypes.c_ubyte * 4)()
            read_pixels(0, 0, 1, 1, 0x1908, 0x1401, pixel)  # RGBA/UNSIGNED_BYTE
            if get_error() or any(abs(pixel[i] - expected) > 2 for i, expected in enumerate((64, 128, 191))):
                raise RuntimeError("EGL window rendering/readback failed")
            if not swap(display, drawable or surface):
                raise RuntimeError("EGL window presentation failed")

        for attributes in (None, core_attrs):
            context = create_context(display, config, None, attributes)
            if not context or not make_current(display, surface, surface, context):
                raise RuntimeError("Darling needs compatibility and OpenGL 4.1 core window contexts")
            renderer = (get_string(0x1F01) or b"").decode(errors="replace")
            if not hardware_zink(renderer):
                raise RuntimeError(f"expected hardware Zink, got {renderer or 'no renderer'}")
            present()
            if attributes is None:
                make_current(display, None, None, None)
                destroy_context(display, context)
                context = None
        texture = uint()
        gen_textures(1, ctypes.byref(texture))
        bind_texture(0x0DE1, texture.value)
        make_current(display, None, None, None)
        failures = []

        def worker():
            shared = None
            try:
                if not bind(0x30A2):
                    raise RuntimeError("desktop OpenGL API could not be bound on the render thread")
                shared = create_context(display, config, context, core_attrs)
                if not shared or not make_current(display, surface, surface, shared):
                    raise RuntimeError("shared core context could not become current on the render thread")
                if not is_texture(texture.value):
                    raise RuntimeError("OpenGL objects were not shared with the render thread")
                present()
            except Exception as error:
                failures.append(error)
            finally:
                make_current(display, None, None, None)
                if shared:
                    destroy_context(display, shared)

        thread = threading.Thread(target=worker, name="MacOBlox EGL probe")
        thread.start()
        thread.join()  # the parent subprocess timeout covers driver hangs
        if failures:
            raise failures[0]
        if not bind(0x30A2) or not make_current(display, surface, surface, context):
            raise RuntimeError("main-thread core context could not be restored")
        delete_textures(1, ctypes.byref(texture))
        if wayland_window:
            if not make_current(display, secondary_surface, secondary_surface, context):
                raise RuntimeError("core context could not switch to the second Native Wayland view")
            present(secondary_surface)
            wayland_window.api.subwindow_frame(secondary_drawable, 2, 3, 32, 24)
            present(secondary_surface)
            width, height = integer(), integer()
            if (not query_surface(display, secondary_surface, 0x3057, ctypes.byref(width)) or
                    not query_surface(display, secondary_surface, 0x3056, ctypes.byref(height)) or
                    (width.value, height.value) != (32, 24)):
                raise RuntimeError("Native Wayland EGL view resize failed")
            wayland_window.api.subwindow_visible(secondary_drawable, 0)
            wayland_window.api.subwindow_visible(secondary_drawable, 1)
            present(secondary_surface)
            if not make_current(display, surface, surface, context):
                raise RuntimeError("main Native Wayland view could not be restored")
            destroy_surface(display, secondary_surface)
            secondary_surface = None
            wayland_window.destroy_drawable(secondary_drawable)
            secondary_drawable = wayland_window.create_drawable(1, 1, 16, 16)
            secondary_surface = create_surface(display, config, wayland_window.api.subwindow_surface(secondary_drawable), None)
            if not secondary_surface or not make_current(display, secondary_surface, secondary_surface, context):
                raise RuntimeError("Native Wayland EGL view recreation failed")
            present(secondary_surface)
        return {"renderer": renderer, "window_presentation": True, "shared_thread_context": True,
                "separate_view_drawables": bool(wayland_window)}
    finally:
        if initialized:
            make_current(display, None, None, None)
            if context:
                destroy_context(display, context)
            if surface:
                destroy_surface(display, surface)
            if secondary_surface:
                destroy_surface(display, secondary_surface)
            terminate(display)
        if wayland_window:
            wayland_window.close()
        else:
            if window:
                destroy_window(native, window)
            close_display(native)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--metal-probe":
        try:
            print(json.dumps(_metal_probe(sys.argv[2])))
        except Exception as error:
            print(json.dumps({"error": str(error)}))
            sys.exit(1)
        sys.exit(0)
    try:
        print(json.dumps(_probe()))
    except Exception as error:
        print(json.dumps({"error": str(error)}))
        sys.exit(1)
