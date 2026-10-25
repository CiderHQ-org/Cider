/* clang -O2 -Wall -Wextra -pthread tests/graphics_context_test.c graphics_context.c -o /tmp/graphics-context-test */
#include <assert.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../graphics_context.h"

static __thread void *cgl_current;
static __thread void *egl_current;
static __thread unsigned int api;
static __thread int egl_error = 0x3000;
static __thread int fail_bind, fail_context;

unsigned int eglBindAPI(unsigned int selected) {
    if (fail_bind) {
        egl_error = 0x300C;
        return 0;
    }
    api = selected;
    return 1;
}

int eglGetError(void) {
    int result = egl_error;
    egl_error = 0x3000;
    return result;
}

void *CGLGetCurrentContext(void) { return cgl_current; }

/* Model Darling: TLS changes before EGL, and failure still returns success. */
int CGLSetCurrentContext(void *context) {
    cgl_current = context;
    int succeeded = !fail_context;
    fail_context = 0;
    if (succeeded)
        egl_current = context;
    else
        egl_error = 0x3002;
    quadra_record_egl_binding(succeeded, context);
    return 0;
}

static int checked_context(void *context) {
    quadra_context_change change;
    if (!quadra_begin_context_change(&change))
        return 10004;
    return quadra_finish_context_change(&change, CGLSetCurrentContext(context));
}

static void *worker(void *unused) {
    (void)unused;
    assert(!api && !cgl_current && !egl_current);
    assert(!checked_context((void *)3));
    assert(api == 0x30A2 && cgl_current == (void *)3 && egl_current == (void *)3);
    assert(quadra_graphics_first_draw());
    assert(!quadra_graphics_first_draw());
    assert(!checked_context((void *)1));
    assert(!quadra_graphics_first_draw()); /* Already checked on the main thread. */
    assert(!checked_context(NULL));
    return NULL;
}

int main(void) {
    const int attributes[] = {5, 55, 0, 56, 4, 99, 0x3200, 0};
    int *copy = quadra_copy_pixel_attributes(attributes);
    assert(copy && !memcmp(copy, attributes, sizeof attributes));
    free(copy);
    assert(!quadra_copy_pixel_attributes(NULL));

    assert(!checked_context((void *)1));
    assert(api == 0x30A2 && cgl_current == (void *)1 && egl_current == (void *)1);
    assert(quadra_graphics_first_draw());
    assert(!quadra_graphics_first_draw());
    assert(!checked_context((void *)2));
    assert(quadra_graphics_first_draw()); /* Safeguard applies to new browser contexts. */
    assert(!checked_context((void *)1));
    assert(!quadra_graphics_first_draw());

    fail_context = 1;
    assert(checked_context((void *)2) == 10004);
    assert(cgl_current == (void *)1 && egl_current == (void *)1);
    assert(quadra_graphics_get_error() == 0x3002);
    assert(quadra_graphics_get_error() == 0x3000);

    /* Failed attachment must restore the old drawable before context rollback. */
    void *surface = (void *)5;
    quadra_context_change change;
    assert(quadra_begin_context_change(&change));
    change.surface_slot = &surface;
    change.previous_surface = surface;
    surface = (void *)6;
    fail_context = 1;
    assert(quadra_finish_context_change(&change, CGLSetCurrentContext((void *)1)) == 10004);
    assert(surface == (void *)5 && cgl_current == (void *)1 && egl_current == (void *)1);
    assert(quadra_graphics_get_error() == 0x3002);

    assert(!checked_context(NULL));
    fail_context = 1;
    assert(checked_context((void *)2) == 10004);
    assert(!cgl_current && !egl_current);
    assert(quadra_graphics_get_error() == 0x3002);
    fail_bind = 1;
    assert(checked_context((void *)2) == 10004);
    assert(!cgl_current && !egl_current);
    assert(quadra_graphics_get_error() == 0x300C);
    fail_bind = 0;

    unsigned long serial = quadra_egl_swap_serial();
    egl_error = 0x300D;
    quadra_record_egl_swap(0);
    assert(quadra_finish_cgl_swap(serial, 0) == 10005);
    assert(quadra_graphics_get_error() == 0x300D);
    serial = quadra_egl_swap_serial();
    quadra_record_egl_swap(1);
    assert(quadra_finish_cgl_swap(serial, 0) == 0);

    pthread_t thread;
    assert(!pthread_create(&thread, NULL, worker, NULL));
    assert(!pthread_join(thread, NULL));
    assert(!cgl_current && !egl_current); /* Worker TLS never changed ours. */
    quadra_forget_egl_context((void *)1);
    quadra_register_egl_context((void *)1);
    assert(!checked_context((void *)1));
    assert(quadra_graphics_first_draw()); /* A reused driver handle gets a new check. */
    puts("PASS: graphics API binding, CGL rollback, EGL errors and context reuse");
    return 0;
}
