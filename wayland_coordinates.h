#ifndef QUADRA_WAYLAND_COORDINATES_H
#define QUADRA_WAYLAND_COORDINATES_H
typedef struct { double x, y; } QuadraWaylandPoint;
typedef struct { double width, height; } QuadraWaylandSize;
typedef struct { QuadraWaylandPoint origin; QuadraWaylandSize size; } QuadraWaylandRect;

/* Wayland exposes logical coordinates within the client surface. Preserve
 * Cocoa's virtual window origin: compositor placement is not discoverable. */
static inline QuadraWaylandPoint quadra_wayland_cocoa_point(
        QuadraWaylandPoint local, QuadraWaylandRect window) {
    return (QuadraWaylandPoint){window.origin.x + local.x,
                                 window.origin.y + window.size.height - local.y};
}
static inline int quadra_wayland_local_warp(QuadraWaylandPoint quartz,
        QuadraWaylandRect window, double screen_height, QuadraWaylandPoint *local) {
    double x = quartz.x - window.origin.x;
    double y = quartz.y - (screen_height - window.origin.y - window.size.height);
    if (!__builtin_isfinite(x) || !__builtin_isfinite(y) || x < 0 || y < 0 ||
        x >= window.size.width || y >= window.size.height) return 0;
    *local = (QuadraWaylandPoint){x, y};
    return 1;
}
#endif
