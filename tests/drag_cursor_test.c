#include <assert.h>
#include <stdio.h>
#include "../drag_cursor.h"
int main(void) {
    MacOBloxDragCursor state={0};
    macoblox_drag_cursor_buttons(&state,MACOBLOX_RIGHT_BUTTON);
    assert(!macoblox_drag_cursor_visible(&state));
    macoblox_drag_cursor_capture(&state,1);
    assert(macoblox_drag_cursor_visible(&state));
    assert(state.button_capture);
    macoblox_drag_cursor_capture(&state,1); // repeated per-frame request
    macoblox_drag_cursor_buttons(&state,MACOBLOX_RIGHT_BUTTON|(1u<<1));
    assert(macoblox_drag_cursor_visible(&state));
    macoblox_drag_cursor_buttons(&state,MACOBLOX_RIGHT_BUTTON); // left released first
    assert(macoblox_drag_cursor_visible(&state));
    macoblox_drag_cursor_buttons(&state,1u<<1); // right released first
    assert(!macoblox_drag_cursor_visible(&state));
    assert(state.button_capture); // a lost-focus drag must not be restored
    macoblox_drag_cursor_buttons(&state,MACOBLOX_RIGHT_BUTTON); // existing capture stays classified
    assert(!macoblox_drag_cursor_visible(&state));
    macoblox_drag_cursor_capture(&state,0);
    assert(!macoblox_drag_cursor_visible(&state));
    macoblox_drag_cursor_capture(&state,1);
    assert(macoblox_drag_cursor_visible(&state));
    macoblox_drag_cursor_buttons(&state,0); // focus loss / no pressed buttons
    macoblox_drag_cursor_capture(&state,0);
    macoblox_drag_cursor_capture(&state,1); // resumed capture without held RMB
    assert(!macoblox_drag_cursor_visible(&state));
    assert(!state.button_capture);
    macoblox_drag_cursor_buttons(&state,MACOBLOX_RIGHT_BUTTON);
    assert(!macoblox_drag_cursor_visible(&state)); // Shift Lock / first-person already active
    macoblox_drag_cursor_capture(&state,0);
    macoblox_drag_cursor_buttons(&state,1u<<1);
    macoblox_drag_cursor_capture(&state,1);
    assert(!macoblox_drag_cursor_visible(&state)); // left-only capture
    assert(macoblox_drag_cursor_arrow(0,0)>>24);
    assert(!macoblox_drag_cursor_arrow(11,0));
    assert(!macoblox_drag_cursor_arrow(1,17));
    puts("PASS: right-drag visibility, both release orders, repeated capture, focus reset and existing capture policy");
}
