#include <assert.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include "../cursor_selection.h"
#include "../shim_lock.h"

static unsigned long child_ids[] = {11, 12};
static unsigned long cleared[2];
static int clear_count, free_count, sync_count, query_success = 1;
static int undefine(void *display, unsigned long window) {
    assert(display == (void *)1 && clear_count < 2);
    cleared[clear_count++] = window;
    return 1;
}
static int query(void *display, unsigned long window, unsigned long *root,
                 unsigned long *parent, unsigned long **children, unsigned int *count) {
    assert(display == (void *)1 && window == 10);
    *root = 1; *parent = 2; *children = child_ids; *count = 2;
    return query_success;
}
static int release_data(void *data) { assert(data == child_ids); free_count++; return 1; }
static int sync_display(void *display, int discard) {
    assert(display == (void *)1 && discard == 0); sync_count++; return 1;
}

static QuadraCursorSelection concurrent;
static volatile unsigned int mailbox_lock;
static volatile int producer_done;
static void *produce(void *unused) {
    (void)unused;
    for (unsigned long index = 1; index <= 10000; index++) {
        quadra_lock(&mailbox_lock);
        assert(quadra_cursor_selection_set(&concurrent, index * 2, index, (void *)(index * 3)));
        quadra_unlock(&mailbox_lock);
    }
    __atomic_store_n(&producer_done, 1, __ATOMIC_RELEASE);
    return 0;
}

int main(void) {
    alarm(3);
    QuadraCursorSelection state = {0}, snapshot = {0};
    assert(!quadra_cursor_selection_take(&state, &snapshot));
    assert(!quadra_cursor_selection_set(&state, 0, 5, (void *)1));
    assert(quadra_cursor_selection_set(&state, 10, 5, (void *)1));
    assert(!quadra_cursor_selection_set(&state, 10, 5, (void *)1));
    /* Coalesce queued changes to the most recent applied cursor. */
    assert(quadra_cursor_selection_set(&state, 10, 6, (void *)2));
    assert(quadra_cursor_selection_take(&state, &snapshot));
    assert(snapshot.window == 10 && snapshot.cursor == 6 && snapshot.owner == (void *)2);
    assert(!quadra_cursor_selection_take(&state, &snapshot));
    assert(!quadra_cursor_selection_set(&state, 10, 6, (void *)2));
    /* Another window, a recycled XID owner, and None are real changes. */
    assert(quadra_cursor_selection_set(&state, 20, 6, (void *)2));
    assert(quadra_cursor_selection_set(&state, 20, 6, (void *)3));
    assert(quadra_cursor_selection_set(&state, 20, 0, 0));
    assert(quadra_cursor_selection_take(&state, &snapshot) && !snapshot.cursor && !snapshot.owner);

    QuadraCursorApplyAPI api = {undefine, query, release_data, sync_display};
    assert(quadra_cursor_selection_apply(&api, (void *)1, 10));
    assert(clear_count == 2 && cleared[0] == 11 && cleared[1] == 12);
    assert(free_count == 1 && sync_count == 1);
    query_success = 0; clear_count = 0;
    assert(quadra_cursor_selection_apply(&api, (void *)1, 10));
    assert(!clear_count && free_count == 2 && sync_count == 2);
    api.sync = 0;
    assert(!quadra_cursor_selection_apply(&api, (void *)1, 10));
    assert(free_count == 2 && sync_count == 2);

    pthread_t producer;
    assert(!pthread_create(&producer, 0, produce, 0));
    int seen = 0;
    for (;;) {
        quadra_lock(&mailbox_lock);
        int ready = quadra_cursor_selection_take(&concurrent, &snapshot);
        quadra_unlock(&mailbox_lock);
        if (ready) {
            assert(snapshot.window == snapshot.cursor * 2);
            assert(snapshot.owner == (void *)(snapshot.cursor * 3));
            seen++;
        } else if (__atomic_load_n(&producer_done, __ATOMIC_ACQUIRE)) break;
    }
    assert(!pthread_join(producer, 0) && seen > 0);
    puts("PASS: selected cursor coalescing, None/window/owner changes, child inheritance, resource cleanup and concurrent snapshots");
}
