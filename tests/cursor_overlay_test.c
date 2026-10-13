/* clang -O2 tests/cursor_overlay_test.c -lX11 -lXfixes -lXext -ldl -o /tmp/cursor-test
 * Run with DISPLAY pointing at a disposable Xvfb server. */
#include <assert.h>
#include <stddef.h>
#include <stdio.h>
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <X11/extensions/Xfixes.h>
#include <X11/extensions/shape.h>
#include "../cursor_overlay.c"
_Static_assert(sizeof(CursorVisual) == sizeof(XVisualInfo), "visual ABI");
_Static_assert(sizeof(CursorAttributes) == sizeof(XSetWindowAttributes), "attributes ABI");
_Static_assert(sizeof(CursorImage) == sizeof(XFixesCursorImage), "cursor ABI");

int main(void) {
    Display *d = XOpenDisplay(0);
    assert(d);
    Window root = DefaultRootWindow(d);
    Window game = XCreateSimpleWindow(d, root, 0, 0, 200, 200, 0, 0, 0);
    XMapWindow(d, game);
    static const char bitmap[] = {0x18, 0x18, 0x18, (char)0xff, (char)0xff, 0x18, 0x18, 0x18};
    Pixmap bits = XCreateBitmapFromData(d, game, bitmap, 8, 8);
    XColor white = {.red = 65535, .green = 65535, .blue = 65535}, black = {0};
    Cursor cursor = XCreatePixmapCursor(d, bits, bits, &white, &black, 4, 4);
    XDefineCursor(d, game, cursor);
    XWarpPointer(d, None, game, 0, 0, 0, 0, 80, 90);
    XSync(d, False);
    assert(macoblox_cursor_overlay_update(1, game, 1));
    XSync(display, False);
    XWindowAttributes attrs;
    assert(XGetWindowAttributes(d, overlay, &attrs));
    assert(attrs.map_state == IsViewable && attrs.x == 76 && attrs.y == 86);
    int n, ordering;
    XRectangle *rectangles = XShapeGetRectangles(d, overlay, ShapeInput, &n, &ordering);
    assert(n == 0); XFree(rectangles);
    XImage *image = XGetImage(d, overlay, 0, 0, 8, 8, AllPlanes, ZPixmap);
    assert(image && (XGetPixel(image, 4, 4) & 0xffffff) == 0xffffff);
    XDestroyImage(image);
    /* Camera motion and hardware hiding must not move or hide the overlay. */
    XFixesHideCursor(d, game);
    XWarpPointer(d, None, game, 0, 0, 0, 0, 150, 150);
    XSync(d, False);
    assert(macoblox_cursor_overlay_update(1, game, 1));
    XSync(display, False);
    assert(XGetWindowAttributes(d, overlay, &attrs));
    assert(attrs.map_state == IsViewable && attrs.x == 76 && attrs.y == 86);
    assert(macoblox_cursor_overlay_update(1, game, 0));
    XSync(display, False);
    assert(XGetWindowAttributes(d, overlay, &attrs) && attrs.map_state == IsUnmapped);
    assert(macoblox_cursor_overlay_update(1, game, 1));
    XSync(display, False);
    assert(XGetWindowAttributes(d, overlay, &attrs) && attrs.map_state == IsViewable);
    assert(macoblox_cursor_overlay_update(0, game, 1));
    XSync(display, False);
    assert(XGetWindowAttributes(d, overlay, &attrs) && attrs.map_state == IsUnmapped);
    /* A right drag remains visible even without a theme or selected bitmap. */
    assert(macoblox_cursor_overlay_update_drag(1,game,0,80,90,2,0,1));
    XSync(display,False);
    assert(XGetWindowAttributes(d,overlay,&attrs) && attrs.map_state==IsViewable);
    /* Preserve the last opaque game cursor across a transparent selection. */
    unsigned int solid[64],transparent[64]={0};
    for(unsigned i=0;i<64;i++)solid[i]=0xff00ff00u;
    macoblox_cursor_overlay_select_image(123,solid,8,8,4,4);
    macoblox_cursor_overlay_select_image(124,transparent,8,8,0,0);
    assert(macoblox_cursor_overlay_update_selected(1,game,1,80,90,3,124));
    XSync(display,False);
    assert(XGetWindowAttributes(d,overlay,&attrs) && attrs.map_state==IsUnmapped);
    assert(macoblox_cursor_overlay_update_drag(1,game,0,80,90,3,124,1));
    XSync(display,False);
    assert(XGetWindowAttributes(d,overlay,&attrs) && attrs.map_state==IsViewable && attrs.x==76 && attrs.y==86);
    image=XGetImage(d,overlay,0,0,8,8,AllPlanes,ZPixmap);
    assert(image && (XGetPixel(image,4,4)&0xffffff)==0x00ff00);XDestroyImage(image);
    assert(macoblox_cursor_overlay_update_drag(1,game,0,80,90,3,124,0));
    XSync(display,False);
    assert(XGetWindowAttributes(d,overlay,&attrs) && attrs.map_state==IsUnmapped);
    assert(macoblox_cursor_overlay_update_drag(0,game,0,80,90,3,124,1));
    /* A closed game window must not let Xlib's default handler exit Roblox. */
    XDestroyWindow(d, game); XSync(d, False);
    macoblox_cursor_overlay_update(0, 0, 1); XSync(display, False);
    XCloseDisplay(d);
    puts("PASS: visible pixels, frozen hotspot, empty input shape, hide/unhide, unlock, window destruction");
}
