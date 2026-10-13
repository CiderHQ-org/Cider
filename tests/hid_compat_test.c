#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

static int wayland, services, single, multiple, released_matching, fail_strings;
static int platform_services;
static const char *provider;
static const int matching_dictionary;
int macoblox_wayland_enabled(void) { return wayland; }
void IOHIDManagerSetDeviceMatching(void *m, const void *d) {
    assert(m == (void *)1 && d == &matching_dictionary); single++;
}
void IOHIDManagerSetDeviceMatchingMultiple(void *m, const void *d) {
    assert(m == (void *)1 && d == &matching_dictionary); multiple++;
}
int IOServiceGetMatchingServices(unsigned master, const void *d, unsigned *iterator) {
    assert(master == 17); services++;
    if (d) released_matching++;
    if (iterator) *iterator = 77;
    return -9;
}
unsigned IOServiceGetMatchingService(unsigned master, const void *d) {
    assert(master == 17 && d == &matching_dictionary); platform_services++;
    released_matching++;
    return 91;
}
const void *CFStringCreateWithCString(const void *a, const char *s, unsigned encoding) {
    assert(!a && encoding == 0x08000100); return fail_strings ? 0 : s;
}
const void *CFDictionaryGetValue(const void *d, const void *k) {
    assert(d == &matching_dictionary && !strcmp(k, "IOProviderClass")); return provider;
}
unsigned long CFGetTypeID(const void *v) { return v == &matching_dictionary ? 7 : 8; }
unsigned long CFDictionaryGetTypeID(void) { return 7; }
unsigned char CFEqual(const void *a, const void *b) { return !strcmp(a, b); }
void CFRelease(const void *v) { if (v == &matching_dictionary) released_matching++; }
#include "../hid_compat.c"

int main(void) {
    unsigned iterator = 123;
    provider = "IOHIDDevice";
    assert(native_hid_inventory(17, &matching_dictionary, &iterator) == -9);
    assert(services == 1 && iterator == 77 && released_matching == 1);
    native_hid_matching((void *)1, &matching_dictionary);
    native_hid_matching_multiple((void *)1, &matching_dictionary);
    assert(single == 1 && multiple == 1 && released_matching == 1);

    wayland = 1;
    iterator = 123;
    assert(native_hid_inventory(17, &matching_dictionary, &iterator) == 0);
    assert(services == 1 && iterator == 0 && released_matching == 2);
    native_hid_matching((void *)1, &matching_dictionary);
    native_hid_matching_multiple((void *)1, &matching_dictionary);
    assert(single == 1 && multiple == 1 && released_matching == 2);

    provider = "IODisplayConnect";
    assert(native_hid_inventory(17, &matching_dictionary, &iterator) == -9);
    assert(services == 2 && iterator == 77 && released_matching == 3);
    provider = "IOHIDDeviceExtra";
    assert(native_hid_inventory(17, &matching_dictionary, &iterator) == -9);
    assert(services == 3 && released_matching == 4);
    assert(native_hid_inventory(17, 0, &iterator) == -9 && services == 4);
    provider = "IOHIDDevice";
    assert(native_hid_inventory(17, &matching_dictionary, 0) == (int)0xe00002c2);
    assert(services == 4 && released_matching == 5);
    fail_strings = 1;
    assert(native_hid_inventory(17, &matching_dictionary, &iterator) == -9);
    assert(services == 5 && released_matching == 6);
    fail_strings = 0;
    provider = "IOPlatformExpertDevice";
    assert(native_platform_service(17, &matching_dictionary) == 0);
    assert(platform_services == 0 && released_matching == 7);
    provider = "IODisplayConnect";
    assert(native_platform_service(17, &matching_dictionary) == 91);
    assert(platform_services == 1 && released_matching == 8);
    provider = "IOPlatformExpertDevice";
    wayland = 0;
    assert(native_platform_service(17, &matching_dictionary) == 91);
    assert(platform_services == 2 && released_matching == 9);
    puts("PASS: HID-only inventory, matching ownership, borrowed manager arguments and X11 delegation");
}
