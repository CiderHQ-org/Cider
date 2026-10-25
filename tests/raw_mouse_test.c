/* Native unit regression for XI2 negotiation and cookie ownership. */
#include <assert.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#if __has_include(<X11/Xlib.h>) && __has_include(<X11/extensions/XInput2.h>)
#include <X11/Xlib.h>
#include <X11/extensions/XInput2.h>
#define CHECK_HOST_XI_ABI 1
#endif
#define dlsym mock_dlsym
#define write mock_write
#include "../raw_mouse.c"
#undef dlsym
#undef write

#ifdef CHECK_HOST_XI_ABI
_Static_assert(sizeof(struct generic_cookie) == sizeof(XGenericEventCookie), "cookie ABI");
_Static_assert(offsetof(struct generic_cookie, data) == offsetof(XGenericEventCookie, data), "cookie data ABI");
_Static_assert(sizeof(struct raw_event) == sizeof(XIRawEvent), "raw event ABI");
_Static_assert(offsetof(struct raw_event, raw_values) == offsetof(XIRawEvent, raw_values), "raw values ABI");
#endif
static int server_major, server_minor, selected, fetched, freed;
static struct raw_event raw;
void *mock_dlsym(void *handle, const char *name) { (void)handle; (void)name; return 0; }
int mock_write(int fd, const void *data, unsigned long n) { (void)fd; (void)data; return (int)n; }
static int version(void *display, int *major, int *minor) {
    (void)display; *major = server_major; *minor = server_minor; return 0;
}
static int extension(void *display, const char *name, int *opcode, int *event, int *error) {
    (void)display; (void)name; *opcode = 131; *event = *error = 0; return 1;
}
static unsigned long root(void *display) { (void)display; return 42; }
static int select_events(void *display, unsigned long window, struct xi_event_mask *mask, int n) {
    (void)display; assert(window == 42 && n == 1 && mask->deviceid == XI_ALL_MASTER_DEVICES);
    selected = !!(mask->mask[XI_RAW_MOTION / 8] & (1u << (XI_RAW_MOTION % 8))); return 0;
}
static int get_data(void *display, struct generic_cookie *cookie) {
    (void)display; assert(!cookie->data); cookie->data = &raw; fetched++; return 1;
}
static void free_data(void *display, struct generic_cookie *cookie) {
    (void)display; assert(cookie->data == &raw); cookie->data = 0; freed++;
}
static void configure(int major, int minor) {
    server_major = major; server_minor = minor; selected = 0; resolved = 1; xi_opcode = -1;
    xi_query_version = version; xi_select_events = select_events;
    x_query_extension = extension; x_default_root_window = root;
    x_get_event_data = get_data; x_free_event_data = free_data;
}
int main(void) {
    configure(2, 0);
    assert(!quadra_raw_mouse_select((void *)1, 1) && !selected);
    configure(2, 1);
    assert(quadra_raw_mouse_select((void *)1, 1) && selected);
    double values[] = {3.5, -2.25, 999}, accelerated[] = {50, 60};
    unsigned char bits = 7;
    raw.valuators.mask = &bits; raw.valuators.mask_len = 1;
    raw.raw_values = values; raw.valuators.values = accelerated;
    struct generic_cookie cookie = {.type = GENERIC_EVENT, .extension = 131, .evtype = XI_RAW_MOTION};
    double dx, dy;
    assert(quadra_raw_mouse_event((void *)1, &cookie, &dx, &dy));
    assert(dx == 3.5 && dy == -2.25 && fetched == 1 && freed == 1 && !cookie.data);
    bits = 2;
    assert(quadra_raw_mouse_event((void *)1, &cookie, &dx, &dy));
    assert(dx == 0 && dy == 3.5 && fetched == 2 && freed == 2);
    bits = 1; raw.raw_values = 0;
    assert(quadra_raw_mouse_event((void *)1, &cookie, &dx, &dy));
    assert(dx == 50 && dy == 0 && fetched == 3 && freed == 3);
    cookie.extension = 132;
    assert(!quadra_raw_mouse_event((void *)1, &cookie, &dx, &dy));
    assert(fetched == 3 && freed == 3);
    assert(!quadra_raw_mouse_select((void *)1, 0) && !selected);
    puts("PASS: XI2.1 required, host ABI, packed axes, raw deltas, cookie ownership, deselection");
}
