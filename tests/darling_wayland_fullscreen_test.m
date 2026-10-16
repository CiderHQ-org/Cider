/* Optional native AppKit regression, in a disposable prefix/compositor.
 * Start with fullscreen already requested before platform-window creation,
 * then check repeated Cocoa toggles against compositor-delivered geometry. */
extern int printf(const char *, ...), fflush(void *), puts(const char *);
extern unsigned alarm(unsigned);
typedef unsigned long NSUInteger;
typedef unsigned char BOOL;
typedef struct {double x,y;} NSPoint;
typedef struct {double width,height;} NSSize;
typedef struct {NSPoint origin;NSSize size;} NSRect;
@interface NSObject
+ (id)alloc; + (id)new;
@end
@interface NSAutoreleasePool:NSObject
- (void)drain;
@end
@interface NSApplication:NSObject
+ (id)sharedApplication; - (void)finishLaunching;
@end
@interface NSWindow:NSObject
- (id)initWithContentRect:(NSRect)rect styleMask:(NSUInteger)mask backing:(NSUInteger)backing defer:(BOOL)defer;
- (void)makeKeyAndOrderFront:(id)sender; - (void)toggleFullScreen:(id)sender; - (void)close;
- (NSUInteger)styleMask; - (NSRect)frame;
@end
@interface NSScreen:NSObject
+ (id)mainScreen; - (NSRect)frame;
@end
@interface NSDate:NSObject
+ (id)dateWithTimeIntervalSinceNow:(double)seconds;
@end
@interface NSRunLoop:NSObject
+ (id)currentRunLoop; - (void)runUntilDate:(id)date;
@end
static void pump(void) {
    for(int i=0;i<60;i++)
        [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:.01]];
}
int main(void) {
    alarm(15);
    NSAutoreleasePool *pool=[NSAutoreleasePool new];
    NSApplication *app=[NSApplication sharedApplication];[app finishLaunching];
    const NSUInteger fullscreen=1UL<<14;
    NSWindow *window=[[NSWindow alloc] initWithContentRect:(NSRect){{20,20},{640,480}}
        styleMask:1|2|8|fullscreen backing:2 defer:1];
    [window makeKeyAndOrderFront:0];pump();
    NSRect screen=[[NSScreen mainScreen] frame],frame=[window frame];
    printf("INITIAL_FULLSCREEN style=%lu frame=%dx%d screen=%dx%d\n",[window styleMask],
        (int)frame.size.width,(int)frame.size.height,(int)screen.size.width,(int)screen.size.height);fflush(0);
    if(!([window styleMask]&fullscreen) || frame.size.width!=screen.size.width ||
       frame.size.height!=screen.size.height)return 1;
    for(int i=0;i<4;i++) {
        [window toggleFullScreen:0];pump();frame=[window frame];
        BOOL expected=(i%2)!=0;
        if((([window styleMask]&fullscreen)!=0)!=expected)return 1;
        if(expected && (frame.size.width!=screen.size.width || frame.size.height!=screen.size.height))return 1;
        if(!expected && frame.size.width==screen.size.width && frame.size.height==screen.size.height)return 1;
        printf("FULLSCREEN_TOGGLE %d frame=%dx%d\n",expected,(int)frame.size.width,(int)frame.size.height);fflush(0);
    }
    puts("PASS: initially requested fullscreen is applied and repeated Cocoa toggles match actual window geometry");
    fflush(0);
    [window close];[pool drain];
    return 0;
}
