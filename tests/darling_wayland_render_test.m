/* Optional no-auth AppKit regression, run by run_darling_wayland_render.py.
 * Uses only its own window in a fresh prefix. An invalid Vulkan ICD control
 * catches initialization twice to verify that failure releases the display
 * lock and permits retry. No Roblox client, credentials, or network calls.
 */
extern int printf(const char *, ...), fflush(void *);
extern unsigned int alarm(unsigned int);
extern char *strstr(const char *, const char *);
extern int strcmp(const char *, const char *);
static int require_zink = 1;
typedef struct { double x, y; } Point;
typedef struct { double width, height; } Size;
typedef struct { Point origin; Size size; } Rect;
@interface NSObject
+ (id)alloc;
- (id)init;
@end
@interface NSAutoreleasePool : NSObject @end
@interface NSApplication : NSObject
+ (id)sharedApplication;
- (void)finishLaunching;
- (id)windowWithWindowNumber:(long)number;
@end
@interface NSWindow : NSObject
- (id)initWithContentRect:(Rect)rect styleMask:(unsigned long)style backing:(unsigned long)backing defer:(unsigned char)defer;
- (void)setContentView:(id)view;
- (void)makeKeyAndOrderFront:(id)sender;
- (long)windowNumber;
- (id)platformWindow;
- (Rect)frame;
- (Point)mouseLocationOutsideOfEventStream;
@end
@interface NSDisplay : NSObject
+ (id)currentDisplay;
- (void)postEvent:(id)event atStart:(unsigned char)start;
- (id)nextEventMatchingMask:(unsigned long long)mask untilDate:(id)date inMode:(id)mode dequeue:(unsigned char)dequeue;
@end
@interface CGWindow : NSObject
+ (id)windowWithWindowNumber:(long)number;
- (void)setStyleMask:(unsigned long)style;
@end
@interface NSDate : NSObject
+ (id)date;
+ (id)dateWithTimeIntervalSinceNow:(double)seconds;
@end
@interface NSEvent : NSObject
+ (Point)mouseLocation;
+ (id)keyEventWithType:(unsigned long)type location:(Point)point modifierFlags:(unsigned long)flags timestamp:(double)timestamp windowNumber:(long)number context:(id)context characters:(id)text charactersIgnoringModifiers:(id)plain isARepeat:(unsigned char)repeat keyCode:(unsigned short)key;
- (unsigned long)type;
- (long)windowNumber;
- (id)window;
@end
@interface NSView : NSObject
- (id)initWithFrame:(Rect)rect;
- (void)setFrame:(Rect)rect;
- (void)setAutoresizingMask:(unsigned long)mask;
@end
@interface NSOpenGLPixelFormat : NSObject
- (id)initWithAttributes:(const unsigned int *)attributes;
@end
@interface NSOpenGLContext : NSObject
- (id)initWithFormat:(id)format shareContext:(id)other;
- (void)setView:(id)view;
- (void)makeCurrentContext;
- (void)flushBuffer;
- (void)update;
@end
@interface NSString : NSObject
- (const char *)UTF8String;
@end
@interface NSException : NSObject
- (id)reason;
@end
extern const unsigned char *glGetString(unsigned int);
extern void glClearColor(float, float, float, float), glClear(unsigned int);
extern void glReadPixels(int, int, int, int, unsigned int, unsigned int, void *);
extern unsigned int glGetError(void);
extern void *IOHIDManagerCreate(const void *, unsigned int);
extern void IOHIDManagerSetDeviceMatching(void *, const void *);
extern void IOHIDManagerSetDeviceMatchingMultiple(void *, const void *);
extern int IOHIDManagerOpen(void *, unsigned int), IOHIDManagerClose(void *, unsigned int);
extern const void *IOHIDManagerCopyDevices(void *);
extern const void *IOServiceMatching(const char *);
extern int IOServiceGetMatchingServices(unsigned int, const void *, unsigned int *);
extern unsigned int IOServiceGetMatchingService(unsigned int, const void *);
extern unsigned int IOIteratorNext(unsigned int);
extern long CFSetGetCount(const void *);
extern void CFRelease(const void *);

static int render(NSOpenGLContext *context, const char *label) {
    [context makeCurrentContext];
    const char *renderer = (const char *)glGetString(0x1F01);
    const char *version = (const char *)glGetString(0x1F02);
    printf("%s_RENDERER %s; GL %s\n", label, renderer ? renderer : "none", version ? version : "none");
    fflush(0);
    if (!renderer || (require_zink && !strstr(renderer, "zink")) || strstr(renderer, "llvmpipe") ||
        strstr(renderer, "lavapipe") || strstr(renderer, "softpipe")) return 0;
    glClearColor(.25f, .5f, .75f, 1);
    glClear(0x4000);
    unsigned char pixel[4] = {0};
    glReadPixels(0, 0, 1, 1, 0x1908, 0x1401, pixel);
    const int expected[] = {64, 128, 191, 255};
    for (int i = 0; i < 4; i++)
        if ((int)pixel[i] < expected[i] - 2 || (int)pixel[i] > expected[i] + 2) return 0;
    [context flushBuffer];
    return glGetError() == 0;
}

static void pump(NSDisplay *display) {
    for (int i = 0; i < 12; i++)
        [display nextEventMatchingMask:~0ULL untilDate:[NSDate dateWithTimeIntervalSinceNow:.02]
                                inMode:@"NSDefaultRunLoopMode" dequeue:1];
}

int main(int argc, char **argv) {
    alarm(10);
    [[NSAutoreleasePool alloc] init];
    int expect_failure = argc == 2 && !strcmp(argv[1], "--expect-init-failure");
    require_zink = !(argc == 2 && !strcmp(argv[1], "--opengl"));
    int failures = 0;
    for (int attempt = 0; attempt < 2; attempt++) {
        @try { [NSDisplay currentDisplay]; }
        @catch (NSException *error) {
            printf("INIT_FAILURE attempt=%d %s\n", attempt + 1, [[error reason] UTF8String]);
            fflush(0);
            failures++;
        }
    }
    if (expect_failure) {
        printf("RETRY_%s failures=%d; failed initialization did not strand display lock\n",
               failures == 2 ? "PASS" : "FAIL", failures);
        fflush(0);
        return failures != 2;
    }
    if (failures) return 1;
    /* This exact call blocked a Roblox startup worker after its first frame.
     * An empty native HID manager must still support open/copy/close. SDL
     * provides the Wayland keyboard and mouse independently of IOKit. */
    void *manager = IOHIDManagerCreate(0, 0);
    if (!manager) return 1;
    IOHIDManagerSetDeviceMatching(manager, 0);
    IOHIDManagerSetDeviceMatchingMultiple(manager, 0);
    if (IOHIDManagerOpen(manager, 0)) return 1;
    const void *devices = IOHIDManagerCopyDevices(manager);
    long count = devices ? CFSetGetCount(devices) : 0;
    if (devices) CFRelease(devices);
    int close = IOHIDManagerClose(manager, 0);
    CFRelease(manager);
    if (count || close) return 1;
    const void *matching = IOServiceMatching("IOHIDDevice");
    unsigned int iterator = 123;
    if (!matching || IOServiceGetMatchingServices(0, matching, &iterator) || iterator ||
        IOIteratorNext(iterator)) return 1;
    matching = IOServiceMatching("IOPlatformExpertDevice");
    if (!matching || IOServiceGetMatchingService(0, matching)) return 1;
    printf("HID_PASS: native SDL input does not wait for unsupported IOKit discovery\n");
    fflush(0);
    @try {
        [[NSApplication sharedApplication] finishLaunching];
        Rect rect = {{37, 91}, {320, 240}};
        NSWindow *window = [[NSWindow alloc] initWithContentRect:rect styleMask:0 backing:2 defer:0];
        NSView *view = [[NSView alloc] initWithFrame:(Rect){{0,0},rect.size}];
        [view setAutoresizingMask:18]; // width and height follow the client area
        [window setContentView:view];
        [window makeKeyAndOrderFront:0];
        long number = [window windowNumber];
        id platform = [window platformWindow];
        if (!number || [CGWindow windowWithWindowNumber:number] != platform ||
            [[NSApplication sharedApplication] windowWithWindowNumber:number] != window) return 1;
        printf("IDENTITY_PASS: Cocoa window number roundtrips through its platform window\n");
        fflush(0);
        NSDisplay *display = [NSDisplay currentDisplay];
        NSEvent *event = [NSEvent keyEventWithType:10 location:(Point){0, 0} modifierFlags:0
                             timestamp:0 windowNumber:number context:0 characters:@"x"
                             charactersIgnoringModifiers:@"x" isARepeat:0 keyCode:7];
        [display postEvent:event atStart:1];
        NSEvent *received = [display nextEventMatchingMask:1ULL << 10 untilDate:[NSDate date]
                                                   inMode:@"NSDefaultRunLoopMode" dequeue:1];
        if ([received type] != 10 || [received windowNumber] != number || [received window] != window) return 1;
        for (int i = 0; i < 4; i++)
            [display nextEventMatchingMask:~0ULL untilDate:[NSDate dateWithTimeIntervalSinceNow:.02]
                                    inMode:@"NSDefaultRunLoopMode" dequeue:1];
        printf("PUMP_PASS: Native AppKit event pump preserves Cocoa window identity\n");
        fflush(0);
        Rect frame = [window frame];
        Point local = [window mouseLocationOutsideOfEventStream], global = [NSEvent mouseLocation];
        if (local.x != global.x-frame.origin.x || local.y != global.y-frame.origin.y) return 1;
        printf("POINTER_PASS: Cocoa global and window pointer locations agree\n");
        fflush(0);
        unsigned int core[] = {99, 0x3200, 8, 24, 5, 0}, compat[] = {8, 24, 5, 0};
        id format = [[NSOpenGLPixelFormat alloc] initWithAttributes:core];
        NSOpenGLContext *first = [[NSOpenGLContext alloc] initWithFormat:format shareContext:0];
        if (!format || !first) return 1;
        [first setView:view];
        if (!render(first, "CORE")) return 1;
        format = [[NSOpenGLPixelFormat alloc] initWithAttributes:compat];
        NSOpenGLContext *second = [[NSOpenGLContext alloc] initWithFormat:format shareContext:0];
        if (!format || !second) return 1;
        [second setView:view];
        if (!render(second, "COMPAT") || !render(first, "CORE_AGAIN")) return 1;
        /* Fullscreen is compositor-driven even on tiling desktops, where a
         * client-requested width may be constrained. Use only this fixture's
         * window, then restore it. The runner checks actual parent-buffer
         * attachments and commits in the no-auth Wayland protocol trace. */
        Rect normal = [window frame];
        for (int fullscreen = 1; fullscreen >= 0; fullscreen--) {
            [platform setStyleMask:fullscreen ? 1UL << 14 : 0];
            pump(display);
            Rect resized = [window frame];
            if (fullscreen && resized.size.width == normal.size.width &&
                resized.size.height == normal.size.height) return 1;
            printf("RESIZE_EXPECT %d %d %d\n", fullscreen,
                   (int)resized.size.width, (int)resized.size.height);
            fflush(0);
            [view setFrame:(Rect){{0,0},resized.size}];
            [first update];
            if (!render(first, fullscreen ? "FULLSCREEN" : "RESTORED")) return 1;
            Point point = [window mouseLocationOutsideOfEventStream], screen = [NSEvent mouseLocation];
            if (point.x != screen.x-resized.origin.x || point.y != screen.y-resized.origin.y) return 1;
        }
        printf("RESIZE_PASS: compositor resize and restore keep rendering and pointer coordinates valid\n");
        fflush(0);
        printf("PASS: Native Wayland AppKit concurrent core/compat views and pixel readback\n");
        fflush(0);
        return 0;
    } @catch (NSException *error) {
        printf("FAIL: %s\n", [[error reason] UTF8String]);
        fflush(0);
        return 1;
    }
}
