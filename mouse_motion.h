#ifndef QUADRA_MOUSE_MOTION_H
#define QUADRA_MOUSE_MOTION_H

/* Keep a captured right-drag camera stream classified as right-drag motion
 * when a second button is pressed. Button down/up events remain independent.
 * Outside capture, retain the normal left-first drag behavior. */
static inline unsigned long quadra_mouse_motion_event(unsigned buttons, int captured,
                                                         unsigned *button) {
    if (captured && (buttons & (1u << 3))) { *button = 3; return 7; }
    if (buttons & (1u << 1)) { *button = 1; return 6; }
    if (buttons & (1u << 3)) { *button = 3; return 7; }
    for (unsigned index = 2; index < 32; index++)
        if (buttons & (1u << index)) { *button = index; return 27; }
    *button = 0;
    return 5;
}
#endif
