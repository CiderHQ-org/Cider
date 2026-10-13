/* Exact production hook with a mocked runtime: sret bytes, publication order,
 * default/unsupported gates, concurrent installation and original exceptions. */
#include <assert.h>
#include <float.h>
#include <math.h>
#include <pthread.h>
#include <setjmp.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef struct objc_class *Class;
typedef struct objc_object *id;
typedef struct objc_selector *SEL;
typedef struct objc_method *Method;
typedef void (*IMP)(void);
static Class objc_getClass(const char *);
static SEL sel_registerName(const char *);
static const char *method_getTypeEncoding(Method);
static IMP method_getImplementation(Method);
static IMP method_setImplementation(Method, IMP);
static void write_str(const char *);
static int input_allowed = 1, input_hooks = 1;
static double input_factor = 1;
static int macoblox_input_scale_allowed(void) { return input_allowed; }
static void macoblox_input_scale_set(double scale) { input_factor = scale; }
static int macoblox_install_input_scale_hooks(void) { return input_hooks; }
#include "../ui_scale_hook.h"

static const char *encoding = "{Settings=^vfiiiB^vBII}16@0:8";
static double requested = 2;
static int present = 1, own = 1, installs, calls, logs, throws;
static id expected_object = (id)(uintptr_t)0x1234;
static SEL expected_selector = (SEL)(uintptr_t)0x5678;
static Method expected_method = (Method)(uintptr_t)0x100;
static MacOBloxSurfaceSettings baseline;
static IMP installed;
static jmp_buf exception;

static MacOBloxSurfaceSettings original_getter(id object, SEL selector) {
    assert(object == expected_object && selector == expected_selector);
    __atomic_add_fetch(&calls, 1, __ATOMIC_RELAXED);
    if (throws) longjmp(exception, 1); /* the wrapper must not consume this */
    return baseline;
}
static Class objc_getClass(const char *name) {
    assert(!strcmp(name, "RobloxPlayerAppDelegate"));
    return present ? (Class)(uintptr_t)0x200 : 0;
}
static SEL sel_registerName(const char *name) {
    assert(!strcmp(name, "getSurfaceSettings"));
    return expected_selector;
}
Method *class_copyMethodList(Class cls, unsigned int *count) {
    assert(cls == (Class)(uintptr_t)0x200);
    *count = own ? 1 : 0;
    Method *methods = malloc(sizeof *methods);
    assert(methods);
    methods[0] = expected_method;
    return methods;
}
SEL method_getName(Method method) {
    assert(method == expected_method); return expected_selector;
}
static const char *method_getTypeEncoding(Method method) {
    assert(method == expected_method); return encoding;
}
static IMP method_getImplementation(Method method) {
    assert(method == expected_method); return (IMP)original_getter;
}
static IMP method_setImplementation(Method method, IMP replacement) {
    assert(method == expected_method && replacement == (IMP)macoblox_scaled_surface_settings);
    /* Simulate another caller entering the method immediately on publication.
     * Its original pointer and requested multiplier must already be visible. */
    MacOBloxSurfaceSettings result =
        ((MacOBloxSurfaceSettings (*)(id, SEL))replacement)(expected_object, expected_selector);
    assert(result.scale == baseline.scale * requested);
    installed = replacement;
    __atomic_add_fetch(&installs, 1, __ATOMIC_RELAXED);
    macoblox_install_surface_scale_hook(); /* recursive installation is refused */
    return (IMP)original_getter;
}
static void write_str(const char *message) {
    assert(message && strlen(message) < 120);
    __atomic_add_fetch(&logs, 1, __ATOMIC_RELAXED);
}
double macoblox_dpi_scale(void) { return requested; }

static void reset(void) {
    assert(!__atomic_load_n(&macoblox_surface_scale_install_state, __ATOMIC_RELAXED) ||
           __atomic_load_n(&macoblox_surface_scale_install_state, __ATOMIC_RELAXED) == 2);
    macoblox_surface_scale_install_state = macoblox_surface_scale_invalid_warned = 0;
    macoblox_surface_scale_applied_logged = macoblox_surface_scale_override_warned = 0;
    macoblox_original_surface_settings = 0;
    macoblox_requested_surface_scale = 0;
    requested = 2; present = own = 1; installs = calls = logs = throws = 0;
    encoding = "{Settings=^vfiiiB^vBII}16@0:8";
    installed = 0;
    input_allowed = input_hooks = 1; input_factor = 1;
    memset(&baseline, 0xa5, sizeof baseline);
    baseline.scale = 1;
    baseline.enabled = 1; baseline.other_enabled = 0;
}
static void verify_bytes(float before, double multiplier, int result, float expected) {
    baseline.scale = before;
    struct {
        uint64_t first;
        MacOBloxSurfaceSettings value;
        uint64_t last;
    } output;
    output.first = UINT64_C(0x0123456789abcdef);
    output.last = UINT64_C(0xfedcba9876543210);
    memcpy(&output.value, &baseline, sizeof baseline);
    assert(macoblox_surface_settings_scale(&output.value, multiplier) == result);
    if (result == 1) assert(output.value.scale == expected);
    for (size_t index = 0; index < sizeof baseline; ++index) {
        if (result == 1 && index >= offsetof(MacOBloxSurfaceSettings, scale) &&
            index < offsetof(MacOBloxSurfaceSettings, scale) + sizeof(float)) continue;
        assert(((unsigned char *)&output.value)[index] == ((unsigned char *)&baseline)[index]);
    }
    assert(output.first == UINT64_C(0x0123456789abcdef));
    assert(output.last == UINT64_C(0xfedcba9876543210));
}
static void *install_thread(void *unused) {
    (void)unused; macoblox_install_surface_scale_hook(); return 0;
}
int main(void) {
    reset();
    assert(macoblox_surface_settings_abi_matches(encoding));
    assert(!macoblox_surface_settings_abi_matches(0));
    assert(!macoblox_surface_settings_abi_matches("{Other=^vfiiiB^vBII}16@0:8"));
    assert(!macoblox_surface_settings_abi_matches("{Settings=^vdiiiB^vBII}16@0:8"));
    assert(!macoblox_surface_settings_abi_matches("{Settings=^vfiiiB^vBII}16@0:8extra"));
    verify_bytes(1, 2, 1, 2); verify_bytes(1.5f, 1.25, 1, 1.875f);
    verify_bytes(1, 4, 1, 4); verify_bytes(FLT_MAX / 4, 4, 1, FLT_MAX);
    verify_bytes(FLT_TRUE_MIN, 4, 1, FLT_TRUE_MIN * 4);
    verify_bytes(FLT_MAX, 1, 0, FLT_MAX);
    verify_bytes(NAN, 1, 0, NAN);
    const float invalid_originals[] = {0, -1, NAN, INFINITY, -INFINITY, FLT_MAX};
    for (size_t i = 0; i < sizeof invalid_originals / sizeof *invalid_originals; ++i)
        verify_bytes(invalid_originals[i], 2, -1, 0);
    const double invalid_requests[] = {0, -1, NAN, INFINITY, -INFINITY, 0.99, 4.001};
    for (size_t i = 0; i < sizeof invalid_requests / sizeof *invalid_requests; ++i)
        verify_bytes(1, invalid_requests[i], -1, 0);

    reset(); requested = 1;
    macoblox_install_surface_scale_hook(); macoblox_install_surface_scale_hook();
    assert(installs == 0 && calls == 0 && logs == 0);
    reset(); present = 0;
    macoblox_install_surface_scale_hook(); assert(installs == 0 && logs == 0);
    present = 1; macoblox_install_surface_scale_hook(); assert(installs == 1);
    reset(); own = 0; /* even an identically encoded inherited method is refused */
    macoblox_install_surface_scale_hook(); macoblox_install_surface_scale_hook();
    assert(!installs && logs == 1);
    reset(); encoding = "{Settings=^vdiiiB^vBII}16@0:8";
    macoblox_install_surface_scale_hook(); macoblox_install_surface_scale_hook();
    assert(!installs && logs == 1);

    reset();
    pthread_t threads[24];
    for (size_t i = 0; i < 24; ++i) assert(!pthread_create(&threads[i], 0, install_thread, 0));
    for (size_t i = 0; i < 24; ++i) assert(!pthread_join(threads[i], 0));
    assert(installs == 1 && calls == 1 && logs == 2 && installed);
    struct { uint64_t first; MacOBloxSurfaceSettings value; uint64_t last; } returned =
        {.first = UINT64_C(0x1122334455667788), .last = UINT64_C(0x8877665544332211)};
    returned.value = ((MacOBloxSurfaceSettings (*)(id, SEL))installed)(expected_object, expected_selector);
    assert(returned.value.scale == 2);
    baseline.scale = 2;
    assert(!memcmp(&returned.value, &baseline, sizeof baseline));
    assert(returned.first == UINT64_C(0x1122334455667788));
    assert(returned.last == UINT64_C(0x8877665544332211));
    /* Repeated calls derive from the original result, never the prior scaled result. */
    baseline.scale = 1;
    for (int i = 0; i < 3; ++i)
        assert(macoblox_scaled_surface_settings(expected_object, expected_selector).scale == 2);
    assert(input_factor == 2);
    input_allowed = 0;
    assert(macoblox_scaled_surface_settings(expected_object, expected_selector).scale == 1);
    assert(input_factor == 1);
    input_allowed = 1;
    int previous_logs = logs;
    baseline.scale = NAN;
    for (int i = 0; i < 3; ++i)
        assert(isnan(macoblox_scaled_surface_settings(expected_object, expected_selector).scale));
    assert(logs == previous_logs + 1);
    throws = 1;
    if (!setjmp(exception)) {
        (void)macoblox_scaled_surface_settings(expected_object, expected_selector);
        assert(!"original exception was swallowed");
    }
    puts("PASS UI scale: exact ABI, bytes/canaries, overflow, own-method gates, atomic publication and original control flow");
}
