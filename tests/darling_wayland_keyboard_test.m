/* Real Darling AppKit regression; use the test-only SDL helper, a disposable
 * prefix and a private compositor. No Roblox, account or desktop input. */
#include "../wayland_bridge.h"
extern int printf(const char *,...),puts(const char *),fflush(void *);
extern unsigned alarm(unsigned);
extern void *dlsym(void *,const char *);
extern char *getenv(const char *);
extern unsigned char CGEventSourceKeyState(int,unsigned short);
typedef unsigned long NSUInteger;
typedef signed char BOOL;
typedef struct {double x,y;} Point;
typedef struct {double width,height;} Size;
typedef struct {Point origin;Size size;} Rect;
typedef struct {NSUInteger location,length;} Range;
@interface NSObject
+ (id)alloc; + (id)new; - (id)init;
@end
@interface NSAutoreleasePool:NSObject
- (void)drain;
@end
@interface NSString:NSObject
- (NSUInteger)length; - (BOOL)isEqual:(id)other;
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
+ (NSUInteger)modifierFlags; - (NSUInteger)type; - (unsigned short)keyCode;
+ (id)keyEventWithType:(NSUInteger)type location:(Point)point modifierFlags:(NSUInteger)flags timestamp:(double)time windowNumber:(long)number context:(id)context characters:(id)text charactersIgnoringModifiers:(id)plain isARepeat:(BOOL)repeat keyCode:(unsigned short)key;
@end
@interface NSDisplay:NSObject
+ (id)currentDisplay; - (void)pump:(id)timer;
- (id)nextEventMatchingMask:(unsigned long long)mask untilDate:(id)date inMode:(id)mode dequeue:(BOOL)dequeue;
@end
@interface NSWindow:NSObject
- (id)initWithContentRect:(Rect)frame styleMask:(NSUInteger)style backing:(NSUInteger)backing defer:(BOOL)defer;
- (void)makeKeyAndOrderFront:(id)sender; - (BOOL)makeFirstResponder:(id)responder;
- (void)setContentView:(id)view; - (id)platformWindow; - (void)close;
- (long)windowNumber;
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
    NSWindow *window=[[NSWindow alloc] initWithContentRect:(Rect){{0,0},{400,280}} styleMask:11 backing:2 defer:1];
    RecordingTextView *view=[[RecordingTextView alloc] initWithFrame:(Rect){{0,0},{400,280}}];
    [view setRichText:0]; // Roblox chat/search are plain text, not an RTF editor
    [window setContentView:view];[window makeKeyAndOrderFront:0];[app _setKeyWindow:window];
    for(int i=0;i<30;i++){[[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:.01]];pump(app);}
    CHECK([window makeFirstResponder:view]);
    struct ElfHead **elf=dlsym((void *)-2,"_elfcalls");CHECK(elf && *elf);
    void *host=(*elf)->open(getenv("MACOBLOX_WAYLAND_HELPER"),2);CHECK(host);
    void (*inject)(unsigned,int)=(*elf)->symbol(host,"macoblox_wayland_keyboard_fixture");CHECK(inject);
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
    puts("PASS: real AppKit single text delivery, repeats, Unicode, Ctrl+A/C/X/V, word editing, deletion, navigation, dual Ctrl, focus loss and responder ordering");fflush(0);
    [window close];[pool drain];return 0;
}
