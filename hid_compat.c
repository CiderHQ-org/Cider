/* Native Wayland supplies keyboard/mouse input through SDL. Darling's HID
 * matching service is incomplete; calling it from IOHIDManager can strand
 * the client's startup worker. Interpose the public manager entry points:
 * the existing IOService hook cannot replace direct calls inside IOKit.
 * Keep the manager usable as an empty manager until native HID discovery
 * is implemented. The matching dictionaries/arrays are borrowed here.
 */
extern int macoblox_wayland_enabled(void);
extern long write(int, const void *, unsigned long);
extern void IOHIDManagerSetDeviceMatching(void *, const void *);
extern void IOHIDManagerSetDeviceMatchingMultiple(void *, const void *);
extern int IOServiceGetMatchingServices(unsigned int, const void *, unsigned int *);
extern const void *CFStringCreateWithCString(const void *, const char *, unsigned int);
extern const void *CFDictionaryGetValue(const void *, const void *);
extern unsigned long CFGetTypeID(const void *), CFDictionaryGetTypeID(void);
extern unsigned char CFEqual(const void *, const void *);
extern void CFRelease(const void *);

static int native_hid_services(const void *matching) {
    if (!macoblox_wayland_enabled() || !matching ||
        CFGetTypeID(matching) != CFDictionaryGetTypeID()) return 0;
    const void *key = CFStringCreateWithCString(0, "IOProviderClass", 0x08000100);
    const void *hid = CFStringCreateWithCString(0, "IOHIDDevice", 0x08000100);
    const void *provider = key ? CFDictionaryGetValue(matching, key) : 0;
    int result = provider && hid && CFEqual(provider, hid);
    if (key) CFRelease(key);
    if (hid) CFRelease(hid);
    return result;
}

static int native_hid_inventory(unsigned int master, const void *matching, unsigned int *iterator) {
    if (!native_hid_services(matching))
        return IOServiceGetMatchingServices(master, matching, iterator);
    /* IOService matching consumes its dictionary, unlike the manager APIs.
     * Keep unrelated display/IOSurface and future service queries intact. */
    CFRelease(matching);
    if (!iterator) return (int)0xe00002c2; /* kIOReturnBadArgument */
    *iterator = 0;
    static unsigned reported;
    if (!__atomic_exchange_n(&reported, 1, __ATOMIC_RELAXED)) {
        static const char message[] = "[Cider Wayland] Unsupported IOHIDDevice inventory is empty\n";
        write(2, message, sizeof message - 1);
    }
    return 0;
}

static int native_input(void) {
    if (!macoblox_wayland_enabled()) return 0;
    static unsigned reported;
    if (!__atomic_exchange_n(&reported, 1, __ATOMIC_RELAXED)) {
        static const char message[] = "[Cider Wayland] Using SDL input; unsupported IOKit HID discovery skipped\n";
        write(2, message, sizeof message - 1);
    }
    return 1;
}

static void native_hid_matching(void *manager, const void *matching) {
    if (!native_input()) IOHIDManagerSetDeviceMatching(manager, matching);
}

static void native_hid_matching_multiple(void *manager, const void *matching) {
    if (!native_input()) IOHIDManagerSetDeviceMatchingMultiple(manager, matching);
}

#define INTERPOSE(replacement, original) \
    __attribute__((used, section("__DATA,__interpose"))) \
    static const struct { const void *replace, *replacee; } interpose_##original = \
        { (const void *)&replacement, (const void *)&original }
INTERPOSE(native_hid_matching, IOHIDManagerSetDeviceMatching);
INTERPOSE(native_hid_matching_multiple, IOHIDManagerSetDeviceMatchingMultiple);
INTERPOSE(native_hid_inventory, IOServiceGetMatchingServices);
