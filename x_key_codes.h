#ifndef QUADRA_X_KEY_CODES_H
#define QUADRA_X_KEY_CODES_H

/* Darling's X11 backend turns an X keycode into an Apple virtual key code with
 * a table that stops at the keys of an Apple keyboard. Every other key came
 * out as code 0, which is the A key: Right Alt/AltGr, Insert, Menu, F16-F20
 * and the ISO key next to Left Shift all pressed "A" in the game. These are
 * the keys that table lacks, as X keycodes (evdev code + 8) and the code a
 * Mac sends for the same physical key (SDL's Cocoa backend uses the same).
 * Returns -1 when Darling's own mapping should stand.
 * Right Alt follows Darling's placement of Left Alt on Command. */
static inline int quadra_x_extra_carbon_key(unsigned x_keycode) {
    switch (x_keycode) {
    case 94:  return 10;   /* the < > | key beside Left Shift: ISO Section */
    case 108: return 54;   /* Right Alt / AltGr: Right Command */
    case 118: return 114;  /* Insert: Help, where Apple keyboards have it */
    case 125: return 81;   /* keypad = */
    case 135: return 110;  /* Menu */
    case 191: return 105;  /* F13 */
    case 192: return 107;  /* F14 */
    case 193: return 113;  /* F15 */
    case 194: return 106;  /* F16 */
    case 195: return 64;   /* F17 */
    case 196: return 79;   /* F18 */
    case 197: return 80;   /* F19 */
    case 198: return 90;   /* F20 */
    default:  return -1;
    }
}

#endif
