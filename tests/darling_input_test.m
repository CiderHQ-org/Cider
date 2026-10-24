/* Optional AppKit/Xvfb integration regression. Compile as in
 * darling_cursor_lock_test.m and inject the built shim in a disposable prefix.
 * Run once with MACOBLOX_RAW_MOUSE=0 and once with it enabled. */
extern int printf(const char *, ...);
extern int fflush(void *);
extern void *dlsym(void *, const char *);
extern char *getenv(const char *);
extern int CGAssociateMouseAndMouseCursorPosition(unsigned int);
typedef struct { double x, y; } Point;
typedef struct { double width, height; } Size;
typedef struct { Point origin; Size size; } Rect;
typedef struct objc_class *Class;
typedef struct objc_ivar *Ivar;
extern Class objc_getClass(const char *);
extern Class object_getClass(id);
extern Ivar class_getInstanceVariable(Class, const char *);
extern long ivar_getOffset(Ivar);
extern SEL sel_registerName(const char *);
extern void *class_getInstanceMethod(Class, SEL);
extern void *class_getClassMethod(Class, SEL);
extern void *method_getImplementation(void *);
extern void *method_setImplementation(void *, void *);
@interface NSObject
+ (id)alloc;
+ (id)new;
- (id)init;
@end
@interface NSAutoreleasePool : NSObject @end
@interface NSApplication : NSObject
+ (id)sharedApplication;
- (void)finishLaunching;
- (void)_setKeyWindow:(id)window;
@end
@interface NSView : NSObject
- (id)initWithFrame:(Rect)frame;
@end
@interface NSWindow : NSObject
- (id)initWithContentRect:(Rect)rect styleMask:(unsigned long)style backing:(unsigned long)backing defer:(unsigned char)defer;
- (void)makeKeyAndOrderFront:(id)sender;
- (void)setAcceptsMouseMovedEvents:(signed char)accepts;
- (void)setContentView:(id)view;
- (void)sendEvent:(id)event;
- (id)platformWindow;
@end
@interface NSDisplay : NSObject
+ (id)currentDisplay;
- (void *)display;
- (void)postXEvent:(void *)event;
- (void)processPendingEvents;
- (void)postEvent:(id)event atStart:(signed char)start;
@end
@interface NSArray : NSObject
- (unsigned long)count;
- (id)objectAtIndex:(unsigned long)index;
- (void)removeAllObjects;
@end
@interface NSEvent : NSObject
+ (Point)mouseLocation;
+ (unsigned long)modifierFlags;
+ (id)mouseEventWithType:(unsigned long)type location:(Point)location modifierFlags:(unsigned long)flags
                 window:(id)window clickCount:(long)clickCount deltaX:(double)dx deltaY:(double)dy;
- (unsigned long)type;
- (long)buttonNumber;
- (double)deltaX;
- (double)deltaY;
- (unsigned long)modifierFlags;
@end
extern id objc_msgSend(id, SEL, ...);
/* Records the NSEvent type of every mouse event that reaches the view. */
static int view_log[16], view_count;
static void record(id event) { view_log[view_count++ & 15] = (int)[(NSEvent *)event type]; }
@interface RecordingView : NSView @end
@implementation RecordingView
- (void)mouseDown:(id)event { record(event); }
- (void)mouseUp:(id)event { record(event); }
- (void)mouseDragged:(id)event { record(event); }
- (void)rightMouseDown:(id)event { record(event); }
- (void)rightMouseUp:(id)event { record(event); }
- (void)rightMouseDragged:(id)event { record(event); }
@end
static void send_button(NSWindow *window, unsigned long type) {
    [window sendEvent:[NSEvent mouseEventWithType:type location:(Point){100,100} modifierFlags:0
                                          window:window clickCount:1 deltaX:0 deltaY:0]];
}
static int delivered(const int *expected, int count) {
    int same = view_count == count;
    for (int index = 0; same && index < count; index++)
        same = view_log[index] == expected[index];
    if (!same) {
        printf("view received %d events:", view_count);
        for (int index = 0; index < view_count && index < 16; index++) printf(" %d", view_log[index]);
        printf("\n");
    }
    return same;
}
#define CHECK(condition) do { if (!(condition)) { printf("FAIL line %d: %s\n", __LINE__, #condition); fflush(0); return 1; } } while (0)
struct ElfHead { void *(*open)(const char *); int (*close)(void *); void *(*symbol)(void *, const char *); };
struct Motion {
    int type; unsigned long serial; int sent; void *display;
    unsigned long window, root, subwindow, time;
    int x, y, xroot, yroot; unsigned int state; char hint; int same_screen;
};
struct Focus { int type; unsigned long serial; int sent; void *display; unsigned long window; int mode, detail; };
struct Cookie {
    int type; unsigned long serial; int sent; void *display;
    int extension, event_type; unsigned int cookie; void *data;
};
struct Raw {
    int type; unsigned long serial; int sent; void *display; int extension, event_type;
    unsigned long time; int device, source, detail, flags;
    struct { int length; unsigned char *mask; double *values; } valuators;
    double *raw_values;
};
union Event { unsigned long words[24]; struct Motion motion; struct Focus focus; struct Cookie cookie; };
static struct Raw raw;
static unsigned char raw_mask = 3;
static double raw_values[2] = {1.25, -0.5};
static int raw_opcode, raw_mode, flooded, reports, modifier_queries, cookies_fetched, cookies_freed;
static void (*original_post)(id, SEL, void *);
static int (*put_back)(void *, void *);
static int (*real_get_data)(void *, void *);
static void (*real_free_data)(void *, void *);

/* Only the synthetic cookie is stubbed; selection/version negotiation and
 * the bounded Xlib drain run against the real Xvfb server. */
int XGetEventData(void *display, void *event) {
    struct Cookie *cookie = event;
    if (cookie->cookie == 0xfeed1234) {
        cookie->data = &raw; cookies_fetched++; return 1;
    }
    return real_get_data(display, event);
}
void XFreeEventData(void *display, void *event) {
    struct Cookie *cookie = event;
    if (cookie->cookie == 0xfeed1234) {
        cookie->data = 0; cookies_freed++; return;
    }
    real_free_data(display, event);
}
static unsigned long counted_modifiers(id cls, SEL cmd) { (void)cls; (void)cmd; modifier_queries++; return 0; }
static void observe_post(id display, SEL cmd, void *incoming) {
    if (flooded && *(int *)incoming == 6) {
        reports++;
        if (raw_mode) {
            union Event event = {0};
            event.cookie.type = 35; event.cookie.extension = raw_opcode;
            event.cookie.event_type = 17; event.cookie.cookie = 0xfeed1234;
            event.cookie.display = [display display];
            original_post(display, cmd, &event);
        } else original_post(display, cmd, incoming);
        /* Replenish after every event: the old unbounded implementation
         * could never finish this batch. The alarm in the runner catches it. */
        put_back([display display], incoming);
    } else original_post(display, cmd, incoming);
}
static NSArray *queue_for(NSDisplay *display) {
    Ivar ivar = class_getInstanceVariable(objc_getClass("NSDisplay"), "_eventQueue");
    return *(id *)((char *)display + ivar_getOffset(ivar));
}
static unsigned long long now_ns(void) {
    struct { long seconds, nanoseconds; } now;
    long result;
    __asm__ volatile("syscall" : "=a"(result)
        : "a"(228L), "D"(1L), "S"(&now) : "rcx", "r11", "memory");
    return result ? 0 : now.seconds * 1000000000ULL + now.nanoseconds;
}
int main(void) {
    [[NSAutoreleasePool alloc] init];
    NSApplication *app = [NSApplication sharedApplication];
    [app finishLaunching];
    NSWindow *window = [[NSWindow alloc] initWithContentRect:(Rect){{50,50},{640,480}}
                                                styleMask:3 backing:2 defer:0];
    [window makeKeyAndOrderFront:0]; [app _setKeyWindow:window];
    [window setAcceptsMouseMovedEvents:1];

    /* One button going up must not hide the other from the game. Clicking left
     * during a right-button camera drag used to lose the right-button release:
     * the camera kept turning until the menu was opened. Types: 1/2 left
     * down/up, 3/4 right down/up, 6/7 left/right dragged. */
    id view = [[RecordingView alloc] initWithFrame:(Rect){{0,0},{640,480}}];
    [window setContentView:view];
    send_button(window, 3); send_button(window, 1); send_button(window, 2);
    send_button(window, 7); send_button(window, 4);
    const int right_first[] = {3, 1, 2, 7, 4};
    CHECK(delivered(right_first, 5));
    view_count = 0;
    send_button(window, 1); send_button(window, 3); send_button(window, 4);
    send_button(window, 6); send_button(window, 2);
    const int left_first[] = {1, 3, 4, 6, 2};
    CHECK(delivered(left_first, 5));
    /* With every button up, a stray drag still reaches nobody. */
    view_count = 0;
    send_button(window, 1); send_button(window, 2);
    send_button(window, 3); send_button(window, 4);
    send_button(window, 7); send_button(window, 6);
    const int clicks[] = {1, 2, 3, 4};
    CHECK(delivered(clicks, 4));
    view_count = 0;

    NSDisplay *display = [NSDisplay currentDisplay];
    void *connection = [display display];
    unsigned long xid = ((unsigned long (*)(id, SEL))objc_msgSend)([window platformWindow], sel_registerName("windowHandle"));
    struct ElfHead **table = dlsym((void *)-2, "_elfcalls");
    CHECK(table && *table && connection && xid);
    void *x11 = (*table)->open("libX11.so.6");
    CHECK(x11);
    put_back = (*table)->symbol(x11, "XPutBackEvent");
    real_get_data = (*table)->symbol(x11, "XGetEventData");
    real_free_data = (*table)->symbol(x11, "XFreeEventData");
    int (*pending)(void *) = (*table)->symbol(x11, "XPending");
    int (*next)(void *, void *) = (*table)->symbol(x11, "XNextEvent");
    int (*sync)(void *, int) = (*table)->symbol(x11, "XSync");
    int (*warp)(void *, unsigned long, unsigned long, int, int, unsigned int, unsigned int, int, int) =
        (*table)->symbol(x11, "XWarpPointer");
    int (*extension)(void *, const char *, int *, int *, int *) = (*table)->symbol(x11, "XQueryExtension");
    int event_base, error_base;
    CHECK(extension(connection, "XInputExtension", &raw_opcode, &event_base, &error_base));
    [display processPendingEvents]; [app _setKeyWindow:window];
    /* Xvfb has no window manager to deliver the activation. Apply the
     * asynchronous lock request before asserting captured-event behavior. */
    union Event focus = {0};
    focus.focus = (struct Focus){.type=9, .display=connection, .window=xid, .mode=0, .detail=3};
    [display postXEvent:&focus];
    CHECK(!CGAssociateMouseAndMouseCursorPosition(0));
    [display processPendingEvents];
    NSArray *queue = queue_for(display);
    [queue removeAllObjects];

    /* Different windows/modifiers and button transitions remain independent. */
    NSWindow *other = [[NSWindow alloc] initWithContentRect:(Rect){{60,60},{100,100}}
                                               styleMask:3 backing:2 defer:0];
    id first = [NSEvent mouseEventWithType:7 location:(Point){10,10} modifierFlags:0 window:window clickCount:1 deltaX:2 deltaY:3];
    [display postEvent:first atStart:0];
    [display postEvent:[NSEvent mouseEventWithType:7 location:(Point){10,10} modifierFlags:0 window:other clickCount:1 deltaX:4 deltaY:5] atStart:0];
    [display postEvent:[NSEvent mouseEventWithType:7 location:(Point){10,10} modifierFlags:(1UL<<17) window:other clickCount:1 deltaX:6 deltaY:7] atStart:0];
    CHECK([queue count] == 3);
    NSEvent *old_motion = [queue objectAtIndex:2];
    [display postEvent:[NSEvent mouseEventWithType:7 location:(Point){10,10} modifierFlags:(1UL<<17) window:other clickCount:1 deltaX:8 deltaY:9] atStart:0];
    CHECK([queue count] == 3 && [(NSEvent *)[queue objectAtIndex:2] deltaX] == 14);
    CHECK([(NSEvent *)first deltaX] == 2 && [old_motion deltaX] == 6);
    [queue removeAllObjects];

    /* Focus loss suspends capture; activation restores it without menu calls. */
    focus.focus.type=10;
    [display postXEvent:&focus];
    warp(connection, 0, xid, 0, 0, 0, 0, 100, 100); sync(connection, 0);
    focus.focus.type = 9; [display postXEvent:&focus];
    Point captured = [NSEvent mouseLocation];
    warp(connection, 0, xid, 0, 0, 0, 0, 130, 120); sync(connection, 0);
    Point frozen = [NSEvent mouseLocation];
    CHECK(captured.x == frozen.x && captured.y == frozen.y);
    focus.focus.type = 10; [display postXEvent:&focus];
    CHECK(!CGAssociateMouseAndMouseCursorPosition(1));
    focus.focus.type = 9; [display postXEvent:&focus];
    Point unlocked = [NSEvent mouseLocation];
    warp(connection, 0, xid, 0, 0, 0, 0, 160, 150); sync(connection, 0);
    Point moved = [NSEvent mouseLocation];
    CHECK(unlocked.x != moved.x || unlocked.y != moved.y);
    CHECK(!CGAssociateMouseAndMouseCursorPosition(0));
    [display processPendingEvents]; [queue removeAllObjects];

    const char *focus_only=getenv("MACOBLOX_TEST_FOCUS_ONLY");
    if(focus_only && focus_only[0]=='1') {
        /* A drag interrupted by switching windows cannot be resurrected by
         * FocusIn or a late background request from the render thread. */
        CHECK(!CGAssociateMouseAndMouseCursorPosition(1));
        [display processPendingEvents];[queue removeAllObjects];
        union Event button={0};
        button.motion=(struct Motion){.type=4,.display=connection,.window=xid,.x=160,.y=150,.same_screen=1};
        *(unsigned int *)((char *)&button+84)=3;[display postXEvent:&button];
        CHECK(!CGAssociateMouseAndMouseCursorPosition(0));
        [display processPendingEvents];[queue removeAllObjects];
        focus.focus.type=10;[display postXEvent:&focus];
        CHECK(!CGAssociateMouseAndMouseCursorPosition(0)); // stale background request
        focus.focus.type=9;[display postXEvent:&focus];
        Point after_focus=[NSEvent mouseLocation];
        warp(connection,0,xid,0,0,0,0,230,210);sync(connection,0);
        Point after_warp=[NSEvent mouseLocation];
        CHECK(after_focus.x!=after_warp.x || after_focus.y!=after_warp.y);
        printf("PASS: X11 persistent capture resumes, explicit unlock cancels, interrupted drag and background lock stay released\n");
        fflush(0);return 0;
    }

    char *setting = getenv("MACOBLOX_RAW_MOUSE");
    raw_mode = !(setting && setting[0] == '0');
    union Event motion = {0};
    motion.motion = (struct Motion){.type=6, .display=connection, .window=xid, .x=160, .y=150,
                                    .state=1u<<10, .same_screen=1};
    if (!raw_mode) {
        /* A pending EnterNotify intentionally discards the first motion. */
        for (int index = 0; index < 3; index++) [display postXEvent:&motion];
        CHECK([queue count] == 1 && [(NSEvent *)[queue objectAtIndex:0] type] == 7);
        [queue removeAllObjects]; motion.motion.state = 1u<<9;
        [display postXEvent:&motion];
        CHECK([queue count] == 1 && [(NSEvent *)[queue objectAtIndex:0] type] == 27 &&
              [(NSEvent *)[queue objectAtIndex:0] buttonNumber] == 2);
    }
    [queue removeAllObjects];
    /* Seed the actual core button/modifier cache before synthesizing raw data. */
    union Event button = motion;
    button.motion.type = 4; button.motion.state = 1u<<10;
    *(unsigned int *)((char *)&button + 84) = 3;
    [display postXEvent:&button]; [queue removeAllObjects];
    raw.valuators.length = 1; raw.valuators.mask = &raw_mask; raw.raw_values = raw_values;
    if (raw_mode) {
        unsigned char (*keycode_for_symbol)(void *, unsigned long) = (*table)->symbol(x11, "XKeysymToKeycode");
        CHECK(keycode_for_symbol);
        unsigned int left_shift = keycode_for_symbol(connection, 0xffe1);
        unsigned int right_shift = keycode_for_symbol(connection, 0xffe2);
        CHECK(left_shift && right_shift);
        union Event key = motion, sample = {0};
        sample.cookie = (struct Cookie){.type=35, .display=connection, .extension=raw_opcode,
                                      .event_type=17, .cookie=0xfeed1234};
        /* No core motion is delivered between a modifier and its raw sample. */
        const unsigned int keys[] = {left_shift, right_shift, left_shift, right_shift};
        const int types[] = {2,2,3,3};
        const unsigned int before[] = {0,1,1,1};
        const unsigned long expected[] = {1UL<<17,1UL<<17,1UL<<17,0};
        for (int index = 0; index < 4; index++) {
            key.motion.type = types[index]; key.motion.state = before[index] | (1u<<10);
            *(unsigned int *)((char *)&key + 84) = keys[index];
            [display postXEvent:&key]; [display postXEvent:&sample];
            CHECK([queue count] >= 2);
            NSEvent *last = [queue objectAtIndex:[queue count]-1];
            CHECK([last type] == 7 && [last modifierFlags] == expected[index]);
            [queue removeAllObjects];
        }
        cookies_fetched = cookies_freed = 0;
    }
    void *method = class_getInstanceMethod(object_getClass(display), sel_registerName("postXEvent:"));
    original_post = method_getImplementation(method);
    method_setImplementation(method, observe_post);
    void *modifiers = class_getClassMethod(objc_getClass("NSEvent"), sel_registerName("modifierFlags"));
    void *original_modifiers = method_getImplementation(modifiers);
    method_setImplementation(modifiers, counted_modifiers);
    motion.motion.state = 1u<<10;
    sync(connection, 0);
    union Event discard;
    while (pending(connection)) next(connection, &discard);
    for (int index = 0; index < 256; index++) put_back(connection, &motion);
    flooded = 1;
    unsigned long long start = now_ns();
    [display processPendingEvents];
    unsigned long long duration = now_ns() - start;
    flooded = 0;
    method_setImplementation(method, original_post);
    method_setImplementation(modifiers, original_modifiers);
    CHECK(reports > 0 && reports <= 128 && duration < 500000000ULL);
    CHECK(modifier_queries == 0);
    CHECK([queue count] == 1);
    NSEvent *motion_event = [queue objectAtIndex:0];
    CHECK([motion_event type] == 7 && [motion_event buttonNumber] == 1);
    if (raw_mode) {
        CHECK(reports > 1);
        CHECK(cookies_fetched == reports && cookies_freed == reports);
        CHECK([motion_event deltaX] == reports * 1.25 && [motion_event deltaY] == reports * -0.5);
        /* Raw delivery can stop after a healthy first batch. Pointer fallback
         * must recover, with its baseline kept current instead of jumping. */
        [queue removeAllObjects];
        while (pending(connection)) next(connection, &discard);
        for (int index = 0; index < 26; index++) {
            motion.motion.x = 161 + index;
            [display postXEvent:&motion];
        }
        CHECK([queue count] == 1);
        motion_event = [queue objectAtIndex:0];
        CHECK([motion_event type] == 7 && [motion_event deltaX] == 1);
    }
    printf("PASS: %s input, focus restore/cancellation, drag buttons, coalescing, modifier transitions, continuous flood returned after %d reports (%llu ns), modifier queries=%d\n",
           raw_mode ? "raw" : "fallback", reports, duration, modifier_queries);
    fflush(0);
    return 0;
}
