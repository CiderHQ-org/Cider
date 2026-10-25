#ifndef QUADRA_X_MODIFIER_STATE_H
#define QUADRA_X_MODIFIER_STATE_H

/* XKeyEvent.state precedes the transition. Keep raw motion in event order;
 * asking the server here could observe later keys already waiting in Xlib. */
static unsigned int quadra_x_modifier_transition(unsigned int state,
        unsigned int keycode, int pressed, const unsigned char key_masks[256],
        unsigned char key_down[256]) {
    if (keycode >= 256) return state;
    unsigned int mask = key_masks[keycode];
    int repeated = key_down[keycode];
    key_down[keycode] = pressed != 0;
    if (!mask) return state;
    if ((mask & 2u /* LockMask */) && pressed && !repeated)
        state ^= 2u;
    unsigned int momentary = mask & ~2u;
    if (pressed) {
        state |= momentary;
    } else {
        unsigned int held = 0;
        for (unsigned int key = 0; key < 256; key++)
            if (key_down[key]) held |= key_masks[key];
        state &= ~(momentary & ~held);
    }
    return state;
}

#endif
