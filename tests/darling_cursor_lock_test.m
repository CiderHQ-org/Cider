/* Optional real AppKit regression. Run in a disposable Darling prefix:
 * clang -target x86_64-apple-darwin -fuse-ld=lld -isysroot /usr/libexec/darling \
 *   -mmacosx-version-min=11.0 -fobjc-exceptions tests/darling_cursor_lock_test.m \
 *   -framework AppKit -framework Foundation -framework CoreGraphics \
 *   -o /tmp/quadra-cursor-lock-test
 * DPREFIX=/tmp/quadra-test-prefix darling shell /bin/bash -c \
 *   'export DYLD_FORCE_FLAT_NAMESPACE=1 DYLD_INSERT_LIBRARIES=/Volumes/SystemRoot/PATH/TO/build/libQuadraShims.dylib; exec /Volumes/SystemRoot/tmp/quadra-cursor-lock-test'
 */
extern int printf(const char *, ...);
extern int fflush(void *);
extern int usleep(unsigned int);
extern int CGAssociateMouseAndMouseCursorPosition(unsigned int);
typedef struct { double x, y; } Point;
typedef struct { double width, height; } Size;
typedef struct { Point origin; Size size; } Rect;
@interface NSObject
+ (id)alloc;
- (id)init;
- (unsigned char)respondsToSelector:(SEL)selector;
@end
@interface NSAutoreleasePool : NSObject @end
@interface NSApplication : NSObject
+ (id)sharedApplication;
- (void)finishLaunching;
- (id)keyWindow;
- (void)_setKeyWindow:(id)window;
@end
@interface NSWindow : NSObject
- (id)initWithContentRect:(Rect)rect styleMask:(unsigned long)style backing:(unsigned long)backing defer:(unsigned char)defer;
- (void)makeKeyAndOrderFront:(id)sender;
- (void)makeKeyWindow;
- (id)platformWindow;
@end
@interface NSException : NSObject
- (id)reason;
@end
@interface NSString : NSObject
- (const char *)UTF8String;
@end
int main(void) {
    [[NSAutoreleasePool alloc] init];
    NSApplication *app = [NSApplication sharedApplication];
    [app finishLaunching];
    NSWindow *window = [[NSWindow alloc] initWithContentRect:(Rect){{50,50},{640,480}}
                                                styleMask:3 backing:2 defer:0];
    [window makeKeyAndOrderFront:0];
    [window makeKeyWindow];
    /* No interactive event loop in this fixture: set AppKit's key window
     * explicitly, as its native focus notification would. */
    [app _setKeyWindow:window];
    printf("Window pair: key=%d Cocoa-handle=%d platform-handle=%d\n",
           [app keyWindow] == window,
           [window respondsToSelector:@selector(windowHandle)],
           [[window platformWindow] respondsToSelector:@selector(windowHandle)]);
    if ([app keyWindow] != window || [window respondsToSelector:@selector(windowHandle)] ||
        ![[window platformWindow] respondsToSelector:@selector(windowHandle)]) {
        printf("FAIL: expected Cocoa window with separate native platform window\n");
        fflush(0);
        return 1;
    }
    @try {
        for (int i = 0; i < 100; i++) {
            if (CGAssociateMouseAndMouseCursorPosition(0) ||
                CGAssociateMouseAndMouseCursorPosition(1)) return 1;
        }
        usleep(100000);
    } @catch(NSException *error) {
        printf("FAIL: camera lock raised %s\n", [[error reason] UTF8String]);
        fflush(0);
        return 1;
    }
    printf("PASS: 100 camera lock/unlock cycles with a real Cocoa/platform window pair\n");
    fflush(0);
    return 0;
}
