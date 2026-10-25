"""Window backend selection for X11/Xwayland and native Wayland."""
import ctypes
import math
import os
from pathlib import Path


def validated_dpi_scale(value):
    """Roblox UI scale; invalid stored/direct values use the 100% default."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return 1.0
    try:
        scale = float(value)
    except (OverflowError, ValueError):
        return 1.0
    return scale if math.isfinite(scale) and 1.0 <= scale <= 4.0 else 1.0


def window_environment(settings, helper):
    backend = settings.get("display_backend", "x11")
    if os.environ.get("QUADRA_WAYLAND") == "1":
        backend = "wayland"
    if backend == "x11":
        return {"QUADRA_WAYLAND": "0", "EGL_PLATFORM": "x11"}
    if backend != "wayland":
        raise ValueError(f"Unknown window backend: {backend}")
    if not os.environ.get("WAYLAND_DISPLAY"):
        raise RuntimeError("Wayland requires a Wayland desktop session. Select X11 in Settings.")
    if not Path(helper).is_file():
        raise RuntimeError("The Wayland helper is missing. Install SDL2/Wayland development libraries and rebuild, or select X11.")
    values = {"QUADRA_WAYLAND": "1", "EGL_PLATFORM": "wayland",
              "QUADRA_WAYLAND_HELPER": str(helper)}
    if settings.get("renderer", "opengl") in ("vulkan", "metal"):
        from .graphics import wayland_vulkan_environment
        values.update(wayland_vulkan_environment())
    return values


class WaylandProbeWindow:
    """The same Linux helper and EGL surface used by the Wayland client."""
    def __init__(self):
        pointer, uint, integer = ctypes.c_void_p, ctypes.c_uint, ctypes.c_int
        display = ctypes.CFUNCTYPE(pointer)
        create = ctypes.CFUNCTYPE(uint, integer, integer)
        surface = ctypes.CFUNCTYPE(pointer, uint)
        action = ctypes.CFUNCTYPE(None, uint, integer, ctypes.c_double, ctypes.c_double, ctypes.c_char_p)
        error = ctypes.CFUNCTYPE(ctypes.c_char_p)
        create_subwindow = ctypes.CFUNCTYPE(uint, uint, integer, integer, integer, integer)
        subwindow_frame = ctypes.CFUNCTYPE(None, uint, integer, integer, integer, integer)
        subwindow_visible = ctypes.CFUNCTYPE(None, uint, integer)
        destroy_subwindow = ctypes.CFUNCTYPE(None, uint)

        class API(ctypes.Structure):
            _fields_ = [("version", uint), ("display", display), ("create", create),
                        ("surface", surface), ("action", action), ("poll", pointer),
                        ("screen", pointer), ("cursor", pointer), ("clipboard", pointer),
                        ("error", error), ("create_subwindow", create_subwindow),
                        ("subwindow_surface", surface), ("subwindow_frame", subwindow_frame),
                        ("subwindow_visible", subwindow_visible), ("destroy_subwindow", destroy_subwindow),
                        ("subwindow_wl_surface", surface)]

        self.library = ctypes.CDLL(os.environ["QUADRA_WAYLAND_HELPER"])
        get_api = self.library.quadra_wayland_host_api
        get_api.restype = ctypes.POINTER(API)
        value = get_api()
        # Check only the ABI header before reading newly added function slots.
        if not value or ctypes.cast(value, ctypes.POINTER(uint)).contents.value != 4:
            raise RuntimeError("Wayland helper failed to initialize or is outdated. Rebuild Quadra before using Wayland.")
        self.api = value.contents
        self.native = self.api.display()
        self.children = set()
        self.handle = self.api.create(16, 16)
        try:
            self.drawable = self.create_drawable(0, 0, 16, 16) if self.handle else 0
        except Exception:
            self.close()
            raise
        self.surface = self.api.subwindow_surface(self.drawable) if self.drawable else None
        if not self.native or not self.surface:
            self.close()
            raise RuntimeError((self.api.error() or b"Wayland test window failed").decode(errors="replace"))

    def create_drawable(self, x, y, width, height):
        handle = self.api.create_subwindow(self.handle, x, y, width, height)
        if not handle:
            raise RuntimeError((self.api.error() or b"Wayland test view failed").decode(errors="replace"))
        self.children.add(handle)
        return handle

    def destroy_drawable(self, handle):
        if handle in self.children:
            self.api.destroy_subwindow(handle)
            self.children.remove(handle)

    def close(self):
        for handle in tuple(self.children):
            self.destroy_drawable(handle)
        if self.handle:
            self.api.action(self.handle, 10, 0, 0, None)  # MW_DESTROY
            self.handle = 0
