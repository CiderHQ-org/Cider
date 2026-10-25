/* Optional genuine Objective-C return/exception regression. Use only a fresh
 * no-auth Darling prefix, a disposable X server and the built shim. No Roblox
 * client, network, credentials or desktop input is used.
 * Compile:
 * clang -target x86_64-apple-darwin -fuse-ld=lld -isysroot /usr/libexec/darling \
 *   -mmacosx-version-min=11.0 -fobjc-exceptions tests/darling_ui_scale_test.m \
 *   -framework AppKit -framework Foundation -o /tmp/quadra-ui-scale-native
 * Inject the shim, set QUADRA_DPI_SCALE=1 or 2, and pass the same integer.
 */
#include "../ui_scale.h"
extern int printf(const char *, ...), fflush(void *), memcmp(const void *, const void *, unsigned long);
extern void *memset(void *, int, unsigned long);
extern unsigned int alarm(unsigned int);
typedef struct objc_class *Class;
typedef struct objc_selector *SEL;
typedef struct objc_method *Method;
extern const char *method_getTypeEncoding(Method);
extern Method class_getInstanceMethod(Class, SEL);
extern Class objc_getClass(const char *);
extern SEL sel_registerName(const char *);
@interface NSObject
+ (id)alloc;
- (id)init;
@end
@interface NSAutoreleasePool : NSObject @end
@interface NSApplication : NSObject
+ (id)sharedApplication;
- (void)finishLaunching;
@end
/* The struct tag is part of the method's verified Objective-C encoding. */
typedef struct Settings {
    void *surface;
    float scale;
    int width_mm, height_mm, unused;
    _Bool enabled;
    void *other_surface;
    _Bool other_enabled;
    unsigned int first_flags, second_flags;
} Settings;
_Static_assert(sizeof(Settings) == sizeof(QuadraSurfaceSettings), "fixture return size");
static Settings baseline;
static int original_calls, should_throw;
static id exception_object;
@interface RobloxPlayerAppDelegate : NSObject
- (Settings)getSurfaceSettings;
@end
@implementation RobloxPlayerAppDelegate
- (Settings)getSurfaceSettings {
    ++original_calls;
    if (should_throw) @throw exception_object;
    return baseline;
}
@end
static int preserves_fields(Settings *value, float expected_scale) {
    if (value->scale != expected_scale) return 0;
    for (unsigned long index = 0; index < sizeof baseline; ++index) {
        if (index >= 8 && index < 12) continue;
        if (((unsigned char *)value)[index] != ((unsigned char *)&baseline)[index]) return 0;
    }
    return 1;
}
int main(int argc, char **argv) {
    alarm(10);
    [[NSAutoreleasePool alloc] init];
    if (argc != 2 || !argv[1][0] || argv[1][1] || argv[1][0] < '1' || argv[1][0] > '4') return 2;
    unsigned int requested = (unsigned int)(argv[1][0] - '0');
    Method method = class_getInstanceMethod(objc_getClass("RobloxPlayerAppDelegate"),
                                            sel_registerName("getSurfaceSettings"));
    if (!method || !quadra_surface_settings_abi_matches(method_getTypeEncoding(method))) return 3;
    [[NSApplication sharedApplication] finishLaunching];
    RobloxPlayerAppDelegate *delegate = [[RobloxPlayerAppDelegate alloc] init];
    memset(&baseline, 0xa5, sizeof baseline);
    baseline.scale = 1.5f; baseline.enabled = 1; baseline.other_enabled = 0;
    struct { unsigned long before; Settings value; unsigned long after; } result;
    result.before = 0x1122334455667788UL; result.after = 0x8877665544332211UL;
    for (int index = 0; index < 3; ++index) {
        result.value = [delegate getSurfaceSettings];
        if (!preserves_fields(&result.value, 1.5f * requested)) return 4;
        if (result.before != 0x1122334455667788UL || result.after != 0x8877665544332211UL) return 5;
    }
    baseline.scale = __builtin_nanf("");
    result.value = [delegate getSurfaceSettings];
    if (memcmp(&result.value, &baseline, sizeof baseline)) return 6;
    baseline.scale = __FLT_MAX__;
    result.value = [delegate getSurfaceSettings];
    if (memcmp(&result.value, &baseline, sizeof baseline)) return 7;
    exception_object = [[NSObject alloc] init]; should_throw = 1;
    int caught_original = 0;
    @try { (void)[delegate getSurfaceSettings]; }
    @catch (id caught) { caught_original = caught == exception_object; }
    if (!caught_original || original_calls != 6) return 8;
    printf("PASS genuine Settings return, fields/canaries, scale=%u, invalid preservation and original ObjC exception\n", requested);
    fflush(0);
    return 0;
}
