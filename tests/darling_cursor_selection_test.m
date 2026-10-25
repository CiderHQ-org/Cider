/* Optional actual AppKit regression. Run ONLY on a disposable X server and
 * no-auth Darling prefix, injecting the shim to check both image init paths.
 * clang -target x86_64-apple-darwin -fuse-ld=lld -isysroot /usr/libexec/darling \
 *   -mmacosx-version-min=11.0 -fobjc-exceptions tests/darling_cursor_selection_test.m \
 *   -framework AppKit -framework Foundation -framework CoreGraphics \
 *   -o /tmp/quadra-cursor-selection-native
 * Alarm bounds the fixture; it does not run Roblox or touch the desktop.
 */
extern int printf(const char *, ...), fflush(void *), usleep(unsigned int);
extern unsigned int alarm(unsigned int);
extern void *dlsym(void *, const char *);
typedef struct { double x,y; } Point;
typedef struct { double width,height; } Size;
typedef struct { Point origin;Size size; } Rect;
@interface NSObject
+ (id)alloc;
- (id)init;
@end
@interface NSAutoreleasePool : NSObject @end
@interface NSApplication : NSObject
+ (id)sharedApplication;
- (void)finishLaunching;
- (void)_setKeyWindow:(id)window;
@end
@interface NSWindow : NSObject
- (id)initWithContentRect:(Rect)rect styleMask:(unsigned long)style backing:(unsigned long)backing defer:(unsigned char)defer;
- (void)makeKeyAndOrderFront:(id)sender;
- (id)platformWindow;
@end
@interface NSDisplay : NSObject
+ (id)currentDisplay;
- (void *)display;
@end
@interface NSImage : NSObject
- (id)initWithSize:(Size)size;
- (void)addRepresentation:(id)rep;
@end
@interface NSBitmapImageRep : NSObject
- (id)initWithCGImage:(void *)image;
@end
@interface NSCursor : NSObject
+ (id)arrowCursor;
+ (void)hide;
+ (void)unhide;
- (id)initWithImage:(id)image hotSpot:(Point)hot;
- (void)set;
@end
@interface NSString : NSObject
- (const char *)UTF8String;
@end
@interface NSException : NSObject
- (id)reason;
@end
extern void *CGColorSpaceCreateDeviceRGB(void);
extern void CGColorSpaceRelease(void *);
extern void *CGDataProviderCreateWithData(void *,const void *,unsigned long,void *);
extern void CGDataProviderRelease(void *);
extern void *CGImageCreate(unsigned long,unsigned long,unsigned long,unsigned long,unsigned long,
                           void *,unsigned int,void *,const double *,unsigned char,unsigned int);
extern void CGImageRelease(void *);
extern void *object_getClass(id), *class_getInstanceVariable(void *,const char *);
extern long ivar_getOffset(void *);
typedef struct { short x,y;unsigned short width,height,xhot,yhot;
                 unsigned long serial,*pixels,atom;const char *name; } CursorImage;
static CursorImage *(*get_cursor_image)(void *);
static int (*free_data)(void *);
static int opacity(void *display) {
    CursorImage *image=get_cursor_image(display);
    if(!image)return -1;
    int count=0;
    for(unsigned long index=0;index<(unsigned long)image->width*image->height;index++)
        count+=(image->pixels[index]>>24)!=0;
    free_data(image);return count;
}
static int wait_opacity(void *display,int wanted) {
    for(int attempt=0;attempt<100;attempt++) {
        int pixels=opacity(display);
        if(pixels>=0 && (pixels>0)==wanted)return 1;
        usleep(10000);
    }
    return 0;
}
static unsigned long cursor_id(id cursor) {
    void *platform_ivar=class_getInstanceVariable(object_getClass(cursor),"_platformCursor");
    id platform=platform_ivar?*(id *)((char *)cursor+ivar_getOffset(platform_ivar)):0;
    void *native_ivar=platform?class_getInstanceVariable(object_getClass(platform),"_cursor"):0;
    return native_ivar?*(unsigned long *)((char *)platform+ivar_getOffset(native_ivar)):0;
}
static id cursor_with_pixels(int visible) {
    static unsigned char white[8*8*4],blank[8*8*4];
    for(unsigned int index=0;index<sizeof white;index++)white[index]=255;
    void *space=CGColorSpaceCreateDeviceRGB();
    void *data=CGDataProviderCreateWithData(0,visible?white:blank,sizeof white,0);
    void *image=CGImageCreate(8,8,8,32,32,space,3 /* straight RGBA */,data,0,0,0);
    id rep=image?[[NSBitmapImageRep alloc] initWithCGImage:image]:0;
    id nsimage=[[NSImage alloc] initWithSize:(Size){8,8}];
    if(rep)[nsimage addRepresentation:rep];
    if(image)CGImageRelease(image);
    CGDataProviderRelease(data);CGColorSpaceRelease(space);
    return rep?[[NSCursor alloc] initWithImage:nsimage hotSpot:(Point){0,0}]:0;
}
#define REQUIRE(test,message) do {if(!(test)){printf("FAIL: %s\n",message);fflush(0);return 1;}}while(0)
int main(void) {
    alarm(8);
    [[NSAutoreleasePool alloc] init];
    @try {
        NSApplication *app=[NSApplication sharedApplication];[app finishLaunching];
        NSWindow *window=[[NSWindow alloc] initWithContentRect:(Rect){{0,0},{200,200}}
                                                   styleMask:0 backing:2 defer:0];
        [window makeKeyAndOrderFront:0];[app _setKeyWindow:window];
        void *display=[[NSDisplay currentDisplay] display];
        unsigned long (*handle)(id,SEL)=dlsym((void *)-2,"objc_msgSend");
        SEL (*selector)(const char *)=dlsym((void *)-2,"sel_registerName");
        unsigned long parent=handle([window platformWindow],selector("windowHandle"));
        unsigned long (*create)(void *,unsigned long,int,int,unsigned int,unsigned int,unsigned int,unsigned long,unsigned long)=dlsym((void *)-2,"XCreateSimpleWindow");
        int (*map)(void *,unsigned long)=dlsym((void *)-2,"XMapWindow");
        int (*define)(void *,unsigned long,unsigned long)=dlsym((void *)-2,"XDefineCursor");
        int (*warp)(void *,unsigned long,unsigned long,int,int,unsigned int,unsigned int,int,int)=dlsym((void *)-2,"XWarpPointer");
        int (*sync)(void *,int)=dlsym((void *)-2,"XSync");
        free_data=dlsym((void *)-2,"XFree");
        struct Elf {void *(*open)(const char *,int);int (*close)(void *);void *(*symbol)(void *,const char *);} **elf=dlsym((void *)-2,"_elfcalls");
        REQUIRE(display&&parent&&create&&map&&define&&warp&&sync&&free_data&&elf&&*elf,"X11 functions");
        void *fixes=(*elf)->open("libXfixes.so.3",2);
        get_cursor_image=fixes?(*elf)->symbol(fixes,"XFixesGetCursorImage"):0;
        REQUIRE(get_cursor_image,"XFixes image function");
        unsigned long child=create(display,parent,0,0,200,200,0,0,0);REQUIRE(child,"rendering child");
        map(display,child);warp(display,0,child,0,0,0,0,80,90);sync(display,0);
        [[NSCursor arrowCursor] set];REQUIRE(wait_opacity(display,1),"initial cursor visible");usleep(100000);
        id blank=cursor_with_pixels(0);REQUIRE(blank&&cursor_id(blank),"blank image cursor");
        define(display,child,cursor_id(blank));sync(display,0);
        REQUIRE(wait_opacity(display,0),"stale blank child reproduced");
        id visible=cursor_with_pixels(1);REQUIRE(visible,"fast pixel cursor");usleep(100000);
        REQUIRE(opacity(display)==0,"cursor construction did not select it");
        [visible set];REQUIRE(wait_opacity(display,1),"actual fast-path cursor set restores child visibility");
        /* No CGImage representation: forces the fallback construction path. */
        id unused=[[NSCursor alloc] initWithImage:[[NSImage alloc] initWithSize:(Size){8,8}] hotSpot:(Point){0,0}];
        REQUIRE(unused,"unused fallback cursor");usleep(100000);
        REQUIRE(opacity(display)>0,"unused fallback construction preserves selected cursor");
        [NSCursor hide];REQUIRE(wait_opacity(display,0),"hide selects blank cursor");
        [NSCursor unhide];REQUIRE(wait_opacity(display,1),"unhide restores selected cursor");
        unsigned long newer=create(display,parent,0,0,200,200,0,0,0);map(display,newer);sync(display,0);
        REQUIRE(opacity(display)>0,"new drawable inherits selected cursor");
        printf("PASS: real AppKit fast-path selection, unused fallback construction, rendering child, hide/unhide and new drawable\n");
        fflush(0);return 0;
    } @catch(NSException *error) {
        printf("FAIL: AppKit exception %s\n",[[error reason] UTF8String]);fflush(0);return 1;
    }
}
