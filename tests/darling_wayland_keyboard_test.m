/* Real Darling AppKit regression; use the test-only SDL helper, a disposable
 * prefix and a private compositor. No Roblox, account or desktop input. */
#include "../wayland_bridge.h"
extern int printf(const char *,...),puts(const char *),fflush(void *);
extern unsigned alarm(unsigned);
extern void *dlsym(void *,const char *);
extern char *getenv(const char *);
extern unsigned char CGEventSourceKeyState(int,unsigned short);
extern int CGAssociateMouseAndMouseCursorPosition(unsigned);
typedef unsigned long NSUInteger;
typedef signed char BOOL;
typedef struct {double x,y;} Point;
typedef struct {double width,height;} Size;
typedef struct {Point origin;Size size;} Rect;
extern int CGWarpMouseCursorPosition(Point);
typedef struct {NSUInteger location,length;} Range;
@interface NSObject
+ (id)alloc; + (id)new; - (id)init;
@end
@interface NSAutoreleasePool:NSObject
- (void)drain;
@end
@interface NSString:NSObject
- (NSUInteger)length; - (BOOL)isEqual:(id)other;
- (id)dataUsingEncoding:(NSUInteger)encoding;
@end
@interface NSPasteboard:NSObject
+ (id)generalPasteboard; + (id)pasteboardWithName:(id)name;
- (BOOL)setString:(id)text forType:(id)type; - (id)stringForType:(id)type;
- (BOOL)setData:(id)data forType:(id)type; - (id)dataForType:(id)type;
- (long)clearContents;
@end
@interface NSApplication:NSObject
+ (id)sharedApplication; - (void)finishLaunching; - (void)sendEvent:(id)event;
- (void)_setKeyWindow:(id)window;
@end
@interface NSDate:NSObject
+ (id)date; + (id)dateWithTimeIntervalSinceNow:(double)value;
@end
@interface NSRunLoop:NSObject
+ (id)currentRunLoop; - (void)runUntilDate:(id)date;
@end
@interface NSEvent:NSObject
+ (Point)mouseLocation;
+ (NSUInteger)modifierFlags; - (NSUInteger)type; - (unsigned short)keyCode;
- (double)deltaX; - (double)deltaY; - (long)buttonNumber;
+ (id)keyEventWithType:(NSUInteger)type location:(Point)point modifierFlags:(NSUInteger)flags timestamp:(double)time windowNumber:(long)number context:(id)context characters:(id)text charactersIgnoringModifiers:(id)plain isARepeat:(BOOL)repeat keyCode:(unsigned short)key;
@end
@interface NSDisplay:NSObject
+ (id)currentDisplay; - (void)pump:(id)timer;
- (id)nextEventMatchingMask:(unsigned long long)mask untilDate:(id)date inMode:(id)mode dequeue:(BOOL)dequeue;
@end
@interface NSWindow:NSObject
- (void)sendEvent:(id)event;
- (id)initWithContentRect:(Rect)frame styleMask:(NSUInteger)style backing:(NSUInteger)backing defer:(BOOL)defer;
- (void)makeKeyAndOrderFront:(id)sender; - (BOOL)makeFirstResponder:(id)responder;
- (void)setContentView:(id)view; - (id)platformWindow; - (void)close;
- (long)windowNumber;
- (Point)mouseLocationOutsideOfEventStream;
@end
static unsigned motion_kind;
static long motion_button;
static double motion_x,motion_y;
@interface RecordingWindow:NSWindow @end
@implementation RecordingWindow
- (void)sendEvent:(NSEvent *)event {
    unsigned type=[event type];
    if((type>=1 && type<=7) || (type>=25 && type<=27)) {
        if(type==5 || type==6 || type==7 || type==27) {
            motion_kind=type;motion_button=[event buttonNumber];
            motion_x=[event deltaX];motion_y=[event deltaY];
        }
        return;
    }
    [super sendEvent:event];
}
@end
@interface NSObject (HostHandle)
- (NSUInteger)windowHandle;
@end
@interface NSTextView:NSObject
- (id)initWithFrame:(Rect)frame; - (void)keyDown:(id)event; - (void)insertText:(id)text;
- (void)setString:(id)string; - (NSString *)string;
- (void)setRichText:(BOOL)rich;
- (void)setSelectedRange:(Range)range; - (Range)selectedRange;
- (id)window;
@end
static unsigned insertions,physical_downs;
static id next_responder;
@interface RecordingTextView:NSTextView @end
@implementation RecordingTextView
- (void)insertText:(id)text{insertions++;[super insertText:text];}
- (void)keyDown:(NSEvent *)event {
    physical_downs++;
    if([event keyCode]==48 && next_responder){[[self window] makeFirstResponder:next_responder];return;}
    [super keyDown:event];
}
@end
struct ElfHead {void *(*open)(const char *,int);int (*close)(void *);void *(*symbol)(void *,const char *);};
#define CHECK(value) do{if(!(value)){printf("FAIL line %d: %s (insertions=%u, physical=%u)\n",__LINE__,#value,insertions,physical_downs);fflush(0);return 1;}}while(0)
static void pump(NSApplication *app) {
    NSDisplay *display=[NSDisplay currentDisplay];[display pump:0];
    id event;
    for(unsigned i=0;i<512;i++) {
        event=[display nextEventMatchingMask:~0ULL untilDate:[NSDate date] inMode:@"NSDefaultRunLoopMode" dequeue:1];
        if(!event || [event type]==100)return; // Darling's empty-queue marker
        [app sendEvent:event];
    }
}
int main(void) {
    alarm(20);
    NSAutoreleasePool *pool=[NSAutoreleasePool new];
    NSApplication *app=[NSApplication sharedApplication];[app finishLaunching];
    NSWindow *window=[[RecordingWindow alloc] initWithContentRect:(Rect){{0,0},{400,280}} styleMask:11 backing:2 defer:1];
    RecordingTextView *view=[[RecordingTextView alloc] initWithFrame:(Rect){{0,0},{400,280}}];
    [view setRichText:0]; // Roblox chat/search are plain text, not an RTF editor
    [window setContentView:view];[window makeKeyAndOrderFront:0];[app _setKeyWindow:window];
    for(int i=0;i<30;i++){[[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:.01]];pump(app);}
    CHECK([window makeFirstResponder:view]);
    struct ElfHead **elf=dlsym((void *)-2,"_elfcalls");CHECK(elf && *elf);
    void *host=(*elf)->open(getenv("QUADRA_WAYLAND_HELPER"),2);CHECK(host);
    void (*inject)(unsigned,int)=(*elf)->symbol(host,"quadra_wayland_keyboard_fixture");CHECK(inject);
    unsigned handle=[[window platformWindow] windowHandle];CHECK(handle);
    inject(handle,1);pump(app);
    CHECK([[view string] isEqual:@"a"] && insertions==1 && physical_downs==1);
    inject(handle,2);pump(app);
    CHECK([[view string] isEqual:@"aAAA"] && insertions==4 && physical_downs==4);
    inject(handle,3);pump(app);
    CHECK([[view string] isEqual:@"aAAAé🙂"] && insertions==5);
    inject(handle,4);pump(app);
    CHECK([[view string] isEqual:@"x"] && insertions==6);
    puts("CHECK: single text/Unicode/repeat/Ctrl+A passed; checking clipboard shortcuts");fflush(0);
    inject(handle,12);pump(app);
    puts("CHECK: Ctrl+C returned");fflush(0);
    CHECK([view selectedRange].length==1 && [[view string] isEqual:@"x"]);
    inject(handle,13);pump(app);CHECK([[view string] length]==0);
    puts("CHECK: Ctrl+X returned");fflush(0);
    inject(handle,14);pump(app);CHECK([[view string] isEqual:@"x"]);
    // The real Roblox input view can retain AppKit's default rich-text flag.
    // Exercise its copy path too, rather than hiding RTF handling in the fixture.
    [view setRichText:1];
    [view setString:@"clipboard é🙂\nsecond line"];
    [view setSelectedRange:(Range){0,[[view string] length]}];
    puts("CHECK: copying from a rich text view");fflush(0);
    inject(handle,12);pump(app);
    inject(handle,13);pump(app);CHECK([[view string] length]==0);
    puts("CHECK: pasting back into a rich text view");fflush(0);
    inject(handle,14);pump(app);
    CHECK([[view string] isEqual:@"clipboard é🙂\nsecond line"]);
    NSPasteboard *board=[NSPasteboard generalPasteboard];
    CHECK(![board dataForType:@"NSRTFPboardType"]);
    CHECK([board setString:@"external é🙂" forType:@"public.utf8-plain-text"]);
    CHECK([[board stringForType:@"public.utf8-plain-text"] isEqual:@"external é🙂"]);
    CHECK([[board stringForType:@"NSStringPboardType"] isEqual:@"external é🙂"]);
    [view setSelectedRange:(Range){0,[[view string] length]}];
    inject(handle,14);pump(app);CHECK([[view string] isEqual:@"external é🙂"]);
    // Unsupported formats cannot shadow a later host clipboard replacement.
    CHECK(![board setData:[@"{\\rtf1 stale}" dataUsingEncoding:4] forType:@"NSRTFPboardType"]);
    CHECK(![board dataForType:@"NSRTFPboardType"]);
    [board clearContents];[view setSelectedRange:(Range){[[view string] length],0}];
    inject(handle,14);pump(app);CHECK([[view string] isEqual:@"external é🙂"]);
    NSPasteboard *private=[NSPasteboard pasteboardWithName:@"quadra-fixture-private"];
    id privateData=[@"private format" dataUsingEncoding:4];
    CHECK([private setData:privateData forType:@"quadra.fixture"]);
    CHECK([[private dataForType:@"quadra.fixture"] isEqual:privateData]);
    puts("PASS: plain/rich Ctrl+C/X/V, Unicode, both string encodings, replaced/empty clipboard and private formats");fflush(0);
    [view setRichText:0];[view setString:@"x"];[view setSelectedRange:(Range){1,0}];
    unsigned before_delete=insertions;
    inject(handle,5);pump(app);
    CHECK([[view string] length]==0 && insertions==before_delete);
    inject(handle,6);pump(app);
    CHECK(CGEventSourceKeyState(0,59) && CGEventSourceKeyState(0,62));
    CHECK(([NSEvent modifierFlags]&(1UL<<18)) && !([NSEvent modifierFlags]&(1UL<<20)));
    inject(handle,7);pump(app);
    CHECK(!CGEventSourceKeyState(0,59) && CGEventSourceKeyState(0,62));
    CHECK([NSEvent modifierFlags]&(1UL<<18));
    inject(handle,8);pump(app);
    CHECK(!CGEventSourceKeyState(0,59) && !CGEventSourceKeyState(0,62) && ![NSEvent modifierFlags]);
    inject(handle,9);pump(app);[app _setKeyWindow:window];CHECK([window makeFirstResponder:view]);
    [view setString:@"one two"];[view setSelectedRange:(Range){7,0}];
    inject(handle,15);pump(app);CHECK([view selectedRange].location==4);
    inject(handle,16);pump(app);CHECK([view selectedRange].location==7);
    inject(handle,17);pump(app);CHECK([[view string] isEqual:@"one "]);
    [view setString:@"xy"];[view setSelectedRange:(Range){2,0}];
    inject(handle,11);pump(app);CHECK([view selectedRange].location==1);
    RecordingTextView *other=[[RecordingTextView alloc] initWithFrame:(Rect){{0,0},{100,100}}];
    next_responder=other;
    inject(handle,10);pump(app);
    CHECK([[other string] isEqual:@"b"] && [[view string] isEqual:@"xy"]);
    // Only native physical events are filtered. Ordinary Cocoa-created keys
    // must retain their normal text interpretation.
    [app sendEvent:[NSEvent keyEventWithType:10 location:(Point){0,0} modifierFlags:0
        timestamp:0 windowNumber:[window windowNumber] context:0 characters:@"c"
        charactersIgnoringModifiers:@"c" isARepeat:0 keyCode:8]];
    CHECK([[other string] isEqual:@"bc"]);
    inject(handle,18);pump(app);
    CHECK(motion_kind==7 && motion_button==1 && motion_x==7 && motion_y==-9);
    inject(handle,19);pump(app);
    CHECK(motion_kind==7 && motion_button==1 && motion_x==3 && motion_y==4);
    inject(handle,20);pump(app);CHECK(motion_kind==5);
    inject(handle,21);pump(app);CHECK(motion_kind==7 && motion_button==1);
    inject(handle,22);pump(app);CHECK(motion_kind==6 && motion_button==0);
    inject(handle,23);pump(app);CHECK(motion_kind==5);
    puts("PASS: real AppKit captured RMB+LMB keeps right-drag deltas and both release orders restore ordinary motion");
    int (*captured)(void)=dlsym((void *)-2,"quadra_wayland_captured");CHECK(captured);
    int width,height;double hz;
    const struct quadra_wayland_api *(*host_api)(void)=(*elf)->symbol(host,"quadra_wayland_host_api");
    CHECK(host_api);const struct quadra_wayland_api *api=host_api();api->screen(&width,&height,&hz);
    // Lock and warp before polling the capture acknowledgement, then let the
    // event queue settle. Old motion must not replace the requested center.
    CHECK(!CGAssociateMouseAndMouseCursorPosition(0));
    Point center={200,height-140};CHECK(!CGWarpMouseCursorPosition(center));
    inject(handle,26);pump(app);CHECK(captured());
    Point location=[window mouseLocationOutsideOfEventStream];
    CHECK(location.x==200 && location.y==140);
    Point global=[NSEvent mouseLocation];CHECK(global.x==center.x && global.y==140);
    inject(handle,24);pump(app);CHECK(captured());
    location=[window mouseLocationOutsideOfEventStream];CHECK(location.x==200 && location.y==140);
    CHECK(!CGAssociateMouseAndMouseCursorPosition(1));inject(handle,26);pump(app);CHECK(!captured());
    // A drag interrupted by Alt+Tab must not be re-enabled by AppKit's
    // queued focus notification, even when blur and focus share one pump.
    inject(handle,18);pump(app);CHECK(captured());
    CHECK(!CGAssociateMouseAndMouseCursorPosition(0));
    inject(handle,24);pump(app);inject(handle,26);pump(app);CHECK(!captured());
    puts("PASS: real AppKit Shift Lock centers before capture acknowledgement and Alt+Tab cancels stale drag capture");
    puts("PASS: real AppKit single text delivery, repeats, Unicode, Ctrl+A/C/X/V, word editing, deletion, navigation, dual Ctrl, focus loss and responder ordering");fflush(0);
    [window close];[pool drain];return 0;
}
