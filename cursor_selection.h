/* Cursor selection mailbox. Callers hold their lock and retain owner while
 * stored. Snapshots carry opaque identity only: the worker uses the window
 * XID and never dereferences or owns the cursor. Creating one does not set it. */
#ifndef QUADRA_CURSOR_SELECTION_H
#define QUADRA_CURSOR_SELECTION_H
typedef struct {
    unsigned long window, cursor;
    void *owner;
    int dirty;
} QuadraCursorSelection;

static inline int quadra_cursor_selection_set(QuadraCursorSelection *state,
                                               unsigned long window,
                                               unsigned long cursor, void *owner) {
    if (!window || (state->window == window && state->cursor == cursor && state->owner == owner))
        return 0;
    *state = (QuadraCursorSelection){window, cursor, owner, 1};
    return 1;
}

static inline int quadra_cursor_selection_take(QuadraCursorSelection *state,
                                                QuadraCursorSelection *snapshot) {
    if (!state->dirty)
        return 0;
    *snapshot = *state;
    state->dirty = 0;
    return 1;
}

/* Children should inherit the current parent cursor. Giving each child an
 * explicit cursor leaves it stuck when AppKit updates only the parent. */
typedef struct {
    int (*undefine)(void *, unsigned long);
    int (*query)(void *, unsigned long, unsigned long *, unsigned long *,
                 unsigned long **, unsigned int *);
    int (*free_data)(void *);
    int (*sync)(void *, int);
} QuadraCursorApplyAPI;

static inline int quadra_cursor_selection_apply(const QuadraCursorApplyAPI *api,
                                                 void *display, unsigned long window) {
    if (!display || !window || !api->undefine || !api->query ||
        !api->free_data || !api->sync)
        return 0;
    /* AppKit's original setter has already applied the parent. Never replay
     * a queued parent XID: a newer set/hide may have happened in between. */
    unsigned long root = 0, parent = 0, *children = 0;
    unsigned int count = 0;
    if (api->query(display, window, &root, &parent, &children, &count) && children)
        for (unsigned int index = 0; index < count; index++)
            api->undefine(display, children[index]);
    if (children)
        api->free_data(children);
    /* The overlay snapshots through another connection; apply first. */
    api->sync(display, 0);
    return 1;
}
#endif
