#ifndef QUADRA_POINTER_MOTION_H
#define QUADRA_POINTER_MOTION_H

/* X event serials identify when the server has processed our warp request.
 * Events queued before it still use the old baseline. The first event after
 * it uses the warp destination, including when the server merges motion. */
typedef struct {
    int x, y, warp_x, warp_y;
    unsigned long warp_serial;
    int warp_pending;
} QuadraPointerMotion;

static inline void quadra_pointer_motion_warp(QuadraPointerMotion *state,
                                                unsigned long serial, int x, int y) {
    state->warp_serial = serial;
    state->warp_x = x;
    state->warp_y = y;
    state->warp_pending = 1;
}

static inline void quadra_pointer_motion_delta(QuadraPointerMotion *state,
                                                 unsigned long serial, int x, int y,
                                                 double *dx, double *dy) {
    if (state->warp_pending && serial >= state->warp_serial) {
        state->x = state->warp_x;
        state->y = state->warp_y;
        state->warp_pending = 0;
    }
    *dx = (double)x - state->x;
    *dy = (double)y - state->y;
    state->x = x;
    state->y = y;
}
#endif
