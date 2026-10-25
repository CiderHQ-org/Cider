/* Mock the blocking IOKit calls: stand-in display services must stay local. */
#include <assert.h>
#include <limits.h>
#include <float.h>
#include <locale.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define DYLD_INTERPOSE(replacement, replacee) \
    static const void *test_reference_##replacee __attribute__((used)) = (const void *)(unsigned long)&replacement;
#include "../gpu_info.c"

static int service_calls, property_calls, dictionary_calls, parent_calls, release_calls, releases;
static int dictionary_failure, number_failure, key_failure;
static long long created_number, dictionary_number;
static int dictionary;
static unsigned long longest_write;
static int strtod_calls;
static quadra_rect display_bounds = {0,0,960,540};
const char kCFTypeDictionaryKeyCallBacks[] = "keys";
const char kCFTypeDictionaryValueCallBacks[] = "values";
/* Model a comma numeric locale: a dot fraction is left unconsumed. The DPI
 * wire parser must never call this locale-sensitive conversion routine. */
double strtod(const char *text, char **end) {
    ++strtod_calls;
    if (end) *end = (char*)text + (*text ? 1 : 0);
    return *text >= '0' && *text <= '9' ? *text - '0' : 0;
}
unsigned char CFStringGetCString(CFStringRef key, char *out, long capacity, unsigned int encoding) {
    (void)encoding;
    if (!key || (long)strlen(key) >= capacity) return 0;
    memcpy(out, key, strlen(key) + 1); return 1;
}
CFTypeRef CFNumberCreate(CFAllocatorRef allocator, long type, const void *value) {
    (void)allocator; assert(type == 4);
    if (number_failure) return 0;
    created_number = *(const long long *)value; return &created_number;
}
CFMutableDictionaryRef CFDictionaryCreateMutable(CFAllocatorRef allocator, long count, const void *keys, const void *values) {
    (void)allocator; (void)count; assert(keys && values);
    return dictionary_failure ? 0 : &dictionary;
}
void CFDictionarySetValue(CFMutableDictionaryRef output, const void *key, const void *value) {
    assert(output == &dictionary && !strcmp(key, "IOFBMemorySize"));
    dictionary_number = *(const long long *)value;
}
CFStringRef CFStringCreateWithCString(CFAllocatorRef allocator, const char *text, unsigned int encoding) {
    (void)allocator; (void)encoding; return key_failure ? 0 : text;
}
void CFRelease(CFTypeRef object) { assert(object); releases++; }
long write(int fd, const void *data, unsigned long length) {
    (void)fd; (void)data; if (length > longest_write) longest_write = length; return (long)length;
}
unsigned int CGDisplayIOServicePort(unsigned int display) { (void)display; service_calls++; return 99; }
CFTypeRef IORegistryEntryCreateCFProperty(io_registry_entry_t entry, CFStringRef key, CFAllocatorRef allocator, IOOptionBits options) {
    (void)key; (void)allocator; (void)options; assert(entry != FAKE_DISPLAY_SERVICE);
    property_calls++; return (CFTypeRef)7;
}
int IORegistryEntryCreateCFProperties(io_registry_entry_t entry, CFMutableDictionaryRef *out, CFAllocatorRef allocator, IOOptionBits options) {
    (void)out; (void)allocator; (void)options; assert(entry != FAKE_DISPLAY_SERVICE);
    dictionary_calls++; return 21;
}
int IORegistryEntryGetParentEntry(io_registry_entry_t entry, const char *plane, io_registry_entry_t *parent) {
    (void)plane; (void)parent; assert(entry != FAKE_DISPLAY_SERVICE); parent_calls++; return 22;
}
int IOObjectRelease(unsigned int object) { assert(object != FAKE_DISPLAY_SERVICE); release_calls++; return 23; }
const void *IOServiceMatching(const char *name) { (void)name; return (void *)24; }
quadra_rect CGDisplayBounds(unsigned int display) {
    return display == 42 ? display_bounds : (quadra_rect){0,0,0,0};
}
quadra_size CGDisplayScreenSize(unsigned int display) { (void)display; return (quadra_size){0,0}; }
unsigned int CGMainDisplayID(void) { return 42; }
void glRenderbufferStorageMultisample(unsigned int target, int samples, unsigned int format, int width, int height) {
    (void)target; (void)samples; (void)format; (void)width; (void)height;
}
quadra_id objc_msgSend(quadra_id self, void *cmd, ...) { (void)self; (void)cmd; return 0; }
void *sel_registerName(const char *text) { return (void *)text; }
void *objc_getClass(const char *text) { return (void *)text; }
quadra_id MTLCreateSystemDefaultDevice(void) { return 0; }
quadra_id MTLCopyAllDevices(void) { return 0; }

static void check_vram(const char *text, long long expected) {
    int property_calls_before = property_calls;
    if (text) assert(!setenv("QUADRA_VRAM_BYTES", text, 1));
    else assert(!unsetenv("QUADRA_VRAM_BYTES"));
    CFTypeRef value = quadra_IORegistryEntryCreateCFProperty(FAKE_DISPLAY_SERVICE, "IOFBMemorySize", 0, 0);
    assert(value && *(const long long *)value == expected && property_calls == property_calls_before);
}
static void check_physical(quadra_size size, double width, double height) {
    assert(__builtin_isfinite(size.width) && __builtin_isfinite(size.height));
    assert(__builtin_fabs(size.width - width) < 1e-9);
    assert(__builtin_fabs(size.height - height) < 1e-9);
}
int main(void) {
    const long long fallback = 512LL << 20;
    assert(quadra_CGDisplayIOServicePort(1) == FAKE_DISPLAY_SERVICE);
    assert(quadra_CGDisplayIOServicePort(999) == FAKE_DISPLAY_SERVICE && !service_calls);
    check_vram(0, fallback); check_vram("", fallback); check_vram("0", fallback);
    check_vram("-1", fallback); check_vram(" 1073741824", fallback);
    check_vram("1073741824garbage", fallback); check_vram("1e12", fallback);
    check_vram("67108863", fallback); check_vram("67108864", 64LL << 20);
    check_vram("1073741824", 1LL << 30);
    check_vram("9223372036854775807", LLONG_MAX);
    check_vram("9223372036854775808", fallback);
    check_vram("18446744073709551616", fallback);
    check_vram("99999999999999999999999999999999999999999999999999", fallback);
    check_vram("00000000000000000000000000000000000000000000000000", fallback);
    assert(!quadra_IORegistryEntryCreateCFProperty(FAKE_DISPLAY_SERVICE, "unknown", 0, 0));
    assert(!quadra_IORegistryEntryCreateCFProperty(FAKE_DISPLAY_SERVICE, 0, 0, 0));
    assert(!property_calls);
    assert(quadra_IORegistryEntryCreateCFProperty(12, "unknown", 0, 0) == (CFTypeRef)7);
    assert(property_calls == 1);
    check_vram("8589934592", 8LL << 30);
    CFMutableDictionaryRef output = 0;
    assert(!quadra_IORegistryEntryCreateCFProperties(FAKE_DISPLAY_SERVICE, &output, 0, 0));
    assert(output == &dictionary && dictionary_number == (8LL << 30) && releases == 2);
    assert(quadra_IORegistryEntryCreateCFProperties(FAKE_DISPLAY_SERVICE, 0, 0, 0) == QUADRA_IO_BAD_ARGUMENT);
    dictionary_failure = 1; output = (void *)1;
    assert(quadra_IORegistryEntryCreateCFProperties(FAKE_DISPLAY_SERVICE, &output, 0, 0) == QUADRA_IO_NO_MEMORY && !output);
    dictionary_failure = 0; number_failure = 1;
    assert(quadra_IORegistryEntryCreateCFProperties(FAKE_DISPLAY_SERVICE, &output, 0, 0) == QUADRA_IO_NO_MEMORY && !output);
    number_failure = 0; key_failure = 1;
    assert(quadra_IORegistryEntryCreateCFProperties(FAKE_DISPLAY_SERVICE, &output, 0, 0) == QUADRA_IO_NO_MEMORY && !output);
    key_failure = 0;
    assert(!dictionary_calls);
    assert(quadra_IORegistryEntryCreateCFProperties(12, &output, 0, 0) == 21 && dictionary_calls == 1);
    io_registry_entry_t parent = 0;
    assert(!quadra_IORegistryEntryGetParentEntry(FAKE_DISPLAY_SERVICE, "IOService", &parent));
    assert(parent == FAKE_DISPLAY_SERVICE && !parent_calls);
    assert(quadra_IORegistryEntryGetParentEntry(FAKE_DISPLAY_SERVICE, "IOService", 0) == QUADRA_IO_BAD_ARGUMENT);
    assert(quadra_IORegistryEntryGetParentEntry(12, "IOService", &parent) == 22 && parent_calls == 1);
    assert(!quadra_IOObjectRelease(FAKE_DISPLAY_SERVICE) && !release_calls);
    assert(quadra_IOObjectRelease(12) == 23 && release_calls == 1);
    quadra_size physical = quadra_CGDisplayScreenSize(999);
    check_physical(physical, 254, 142.875);
    assert(!setenv("QUADRA_DPI_SCALE", "2", 1));
    physical = quadra_CGDisplayScreenSize(42);
    /* UI scaling leaves the rendering pixels and physical monitor size
     * unchanged. This prevents input/display geometry from scaling twice. */
    check_physical(physical, 254, 142.875);
    assert(quadra_CGDisplayBounds(42).width == 960);
    assert(!setenv("QUADRA_DPI_SCALE", "1.25", 1));
    physical = quadra_CGDisplayScreenSize(999);
    check_physical(physical, 254, 142.875);
    const char *bad_scale[] = {"", "nan", "NaN", "inf", "Infinity", "0", "-2", "+2", "0.5",
                              "4.01", "4.000000000000000000000000001", "2garbage", " 2", "2 ",
                              "1,25", "2e0", "0x1p1", "2.", "2..0", "99999999999999999999999999999999999",
                              "000000000000000000000000000000002", "2.0000000000000000000000000000000"};
    for (unsigned i = 0; i < sizeof bad_scale / sizeof bad_scale[0]; i++) {
        assert(!setenv("QUADRA_DPI_SCALE", bad_scale[i], 1));
        physical = quadra_CGDisplayScreenSize(42);
        check_physical(physical, 254, 142.875);
    }
    const char *good_scale[] = {"1", "1.000", "1.25", "1.250", "2", "2.500", "4", "4.000", "0004.000"};
    const double expected_scale[] = {1, 1, 1.25, 1.25, 2, 2.5, 4, 4, 4};
    for (unsigned i = 0; i < sizeof good_scale / sizeof good_scale[0]; i++) {
        assert(!setenv("QUADRA_DPI_SCALE", good_scale[i], 1));
        assert(quadra_dpi_scale() == expected_scale[i]);
    }
    // Exercise a comma locale when one is available. The parser itself has
    // no locale/strtod dependency; plain dot input remains the wire format.
    const char *locales[] = {"de_DE.UTF-8", "fr_FR.UTF-8", "de_DE.utf8", "fr_FR.utf8"};
    for (unsigned i = 0; i < sizeof locales / sizeof locales[0]; i++) {
        if (setlocale(LC_NUMERIC, locales[i])) {
            assert(!setenv("QUADRA_DPI_SCALE", "1.250", 1));
            assert(quadra_dpi_scale() == 1.25);
            break;
        }
    }
    assert(setlocale(LC_NUMERIC, "C"));
    assert(!strtod_calls);
    assert(!unsetenv("QUADRA_DPI_SCALE"));
    display_bounds = (quadra_rect){0,0,__builtin_nan(""),__builtin_inf()};
    physical = quadra_CGDisplayScreenSize(42);
    check_physical(physical, 508, 285.75);
    assert(__builtin_isnan(quadra_CGDisplayBounds(42).width));
    display_bounds = (quadra_rect){0,0,0,-10};
    physical = quadra_CGDisplayScreenSize(42);
    check_physical(physical, 508, 285.75);
    assert(quadra_CGDisplayBounds(42).width == 0);
    display_bounds = (quadra_rect){0,0,DBL_MAX,DBL_MAX};
    physical = quadra_CGDisplayScreenSize(42);
    assert(__builtin_isfinite(physical.width) && physical.width > 0);
    assert(__builtin_isfinite(physical.height) && physical.height > 0);
    assert(quadra_CGDisplayBounds(42).width == DBL_MAX);
    display_bounds = (quadra_rect){0,0,DBL_MIN * DBL_EPSILON,DBL_MIN * DBL_EPSILON};
    physical = quadra_CGDisplayScreenSize(42);
    check_physical(physical, 508, 285.75);
    display_bounds = (quadra_rect){0,0,960,540};
    assert(!setenv("QUADRA_TRACE_IOKIT", "1", 1));
    char detail[1000]; memset(detail, 'x', sizeof detail - 1); detail[sizeof detail - 1] = 0;
    trace("long detail", detail, 1);
    assert(longest_write == 199);
    puts("PASS: local IOKit, bounded VRAM, locale-independent bounded DPI decimals, finite physical size, unchanged frame bounds, trace bounds");
}
