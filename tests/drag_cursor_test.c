#include <assert.h>
#include <stdio.h>
#include "../drag_cursor.h"
int main(void) {
    QuadraDragCursor state={0};
    quadra_drag_cursor_buttons(&state,QUADRA_RIGHT_BUTTON);
    assert(!quadra_drag_cursor_visible(&state));
    quadra_drag_cursor_capture(&state,1);
    assert(quadra_drag_cursor_visible(&state));
    assert(state.button_capture);
    quadra_drag_cursor_capture(&state,1); // repeated per-frame request
    quadra_drag_cursor_buttons(&state,QUADRA_RIGHT_BUTTON|(1u<<1));
    assert(quadra_drag_cursor_visible(&state));
    quadra_drag_cursor_buttons(&state,QUADRA_RIGHT_BUTTON); // left released first
    assert(quadra_drag_cursor_visible(&state));
    quadra_drag_cursor_buttons(&state,1u<<1); // right released first
    assert(!quadra_drag_cursor_visible(&state));
    assert(state.button_capture); // a lost-focus drag must not be restored
    quadra_drag_cursor_buttons(&state,QUADRA_RIGHT_BUTTON); // existing capture stays classified
    assert(!quadra_drag_cursor_visible(&state));
    quadra_drag_cursor_capture(&state,0);
    assert(!quadra_drag_cursor_visible(&state));
    quadra_drag_cursor_capture(&state,1);
    assert(quadra_drag_cursor_visible(&state));
    quadra_drag_cursor_buttons(&state,0); // focus loss / no pressed buttons
    quadra_drag_cursor_capture(&state,0);
    quadra_drag_cursor_capture(&state,1); // resumed capture without held RMB
    assert(!quadra_drag_cursor_visible(&state));
    assert(!state.button_capture);
    quadra_drag_cursor_buttons(&state,QUADRA_RIGHT_BUTTON);
    assert(!quadra_drag_cursor_visible(&state)); // Shift Lock / first-person already active
    quadra_drag_cursor_capture(&state,0);
    quadra_drag_cursor_buttons(&state,1u<<1);
    quadra_drag_cursor_capture(&state,1);
    assert(!quadra_drag_cursor_visible(&state)); // left-only capture
    assert(quadra_drag_cursor_arrow(0,0)>>24);
    assert(!quadra_drag_cursor_arrow(11,0));
    assert(!quadra_drag_cursor_arrow(1,17));
    puts("PASS: right-drag visibility, both release orders, repeated capture, focus reset and existing capture policy");
}
