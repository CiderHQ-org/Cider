#ifndef MACOBLOX_WAYLAND_COORDINATES_H
#define MACOBLOX_WAYLAND_COORDINATES_H
typedef struct { double x, y; } MacOBloxWaylandPoint;
typedef struct { double width, height; } MacOBloxWaylandSize;
typedef struct { MacOBloxWaylandPoint origin; MacOBloxWaylandSize size; } MacOBloxWaylandRect;

/* Wayland exposes logical coordinates within the client surface. Preserve
 * Cocoa's virtual window origin: compositor placement is not discoverable. */
static inline MacOBloxWaylandPoint macoblox_wayland_cocoa_point(
        MacOBloxWaylandPoint local, MacOBloxWaylandRect window) {
    return (MacOBloxWaylandPoint){window.origin.x + local.x,
                                 window.origin.y + window.size.height - local.y};
}
static inline int macoblox_wayland_local_warp(MacOBloxWaylandPoint quartz,
        MacOBloxWaylandRect window, double screen_height, MacOBloxWaylandPoint *local) {
    double x = quartz.x - window.origin.x;
    double y = quartz.y - (screen_height - window.origin.y - window.size.height);
    if (!__builtin_isfinite(x) || !__builtin_isfinite(y) || x < 0 || y < 0 ||
        x >= window.size.width || y >= window.size.height) return 0;
    *local = (MacOBloxWaylandPoint){x, y};
    return 1;
}
#endif
