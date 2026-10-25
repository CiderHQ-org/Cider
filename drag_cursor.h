/* A right-button drag may keep its software cursor visible. Latch the cause
 * only when capture starts: pressing RMB during existing Shift Lock or
 * first-person capture must not change that capture's cursor policy. */
#ifndef QUADRA_DRAG_CURSOR_H
#define QUADRA_DRAG_CURSOR_H
typedef struct {
    unsigned buttons;
    int captured, right_drag, button_capture;
} QuadraDragCursor;
#define QUADRA_RIGHT_BUTTON (1u << 3)
static inline int quadra_drag_cursor_visible(const QuadraDragCursor *state) {
    return state->captured && state->right_drag && (state->buttons & QUADRA_RIGHT_BUTTON);
}
static inline void quadra_drag_cursor_buttons(QuadraDragCursor *state,unsigned buttons) {
    state->buttons=buttons;
    if(!(buttons & QUADRA_RIGHT_BUTTON))state->right_drag=0;
}
static inline void quadra_drag_cursor_capture(QuadraDragCursor *state,int captured) {
    if(state->captured==captured)return;
    state->captured=captured;
    state->button_capture=captured && state->buttons;
    state->right_drag=captured && (state->buttons & QUADRA_RIGHT_BUTTON);
}
/* Last resort when no selected bitmap or desktop cursor theme is available. */
static inline unsigned quadra_drag_cursor_arrow(unsigned x,unsigned y) {
    static const char *rows[]={"X", "XX", "XOX", "XOOX", "XOOOX", "XOOOOX",
        "XOOOOOX", "XOOOOOOX", "XOOOOOOOX", "XOOOOOOOOX", "XOOOOXXXXX",
        "XOOXOX", "XOX XOX", "XX  XOX", "X    XOX", "     XOX", "      XX"};
    if(y>=sizeof rows/sizeof rows[0])return 0;
    const char *row=rows[y];
    for(unsigned i=0;i<x;i++)if(!row[i])return 0;
    return row[x]=='X'?0xff000000u:row[x]=='O'?0xffffffffu:0;
}
#endif
