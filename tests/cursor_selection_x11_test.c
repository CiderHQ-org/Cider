/* Optional real X11 regression in a disposable Xvfb server:
 * clang -O2 tests/cursor_selection_x11_test.c -lX11 -lXfixes -o /tmp/cursor-selection-x11
 * DISPLAY=:PRIVATE timeout 5s /tmp/cursor-selection-x11
 */
#include <assert.h>
#include <stdio.h>
#include <unistd.h>
#include <X11/Xlib.h>
#include <X11/cursorfont.h>
#include <X11/extensions/Xfixes.h>
#include "../cursor_selection.h"

static int opaque_pixels(Display *display) {
    XFixesCursorImage *image = XFixesGetCursorImage(display);
    assert(image);
    int count = 0;
    for (unsigned int index = 0; index < image->width * image->height; index++)
        count += (image->pixels[index] >> 24) != 0;
    XFree(image);
    return count;
}

int main(void) {
    alarm(3);
    Display *display = XOpenDisplay(0); assert(display);
    Window game = XCreateSimpleWindow(display, DefaultRootWindow(display), 0, 0, 200, 200, 0, 0, 0);
    Window child = XCreateSimpleWindow(display, game, 0, 0, 200, 200, 0, 0, 0);
    XMapWindow(display, game); XMapWindow(display, child);
    Cursor arrow = XCreateFontCursor(display, XC_left_ptr);
    char empty = 0;
    Pixmap bitmap = XCreateBitmapFromData(display, game, &empty, 1, 1);
    XColor color = {0};
    Cursor blank = XCreatePixmapCursor(display, bitmap, bitmap, &color, &color, 0, 0);
    XDefineCursor(display, game, arrow); XDefineCursor(display, child, blank);
    XWarpPointer(display, None, child, 0, 0, 0, 0, 80, 90); XSync(display, False);
    assert(!opaque_pixels(display)); /* Reproduce the stale child cursor. */

    QuadraCursorApplyAPI api = {(void *)XUndefineCursor, (void *)XQueryTree,
                                 (void *)XFree, (void *)XSync};
    assert(quadra_cursor_selection_apply(&api, display, game));
    assert(opaque_pixels(display) > 0);
    /* A newer hide wins even when an older worker update runs afterward. */
    XDefineCursor(display, game, blank); XSync(display, False);
    assert(quadra_cursor_selection_apply(&api, display, game));
    assert(!opaque_pixels(display));
    XDefineCursor(display, game, arrow); XSync(display, False);
    assert(opaque_pixels(display) > 0); /* Unhide follows the parent immediately. */

    Window newer = XCreateSimpleWindow(display, game, 0, 0, 200, 200, 0, 0, 0);
    XMapWindow(display, newer); XSync(display, False);
    assert(opaque_pixels(display) > 0); /* New drawables inherit without a cursor change. */
    XFreeCursor(display, blank); XFreeCursor(display, arrow); XFreePixmap(display, bitmap);
    XDestroyWindow(display, game); XCloseDisplay(display);
    puts("PASS: stale blank render-child cursor repaired; hide/unhide, newer selections and new drawables retain inheritance");
}
