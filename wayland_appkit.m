/* AppKit's native Wayland display. Interfaces are declared here because the
 * Darling runtime packages do not include SDK headers. */
#include "wayland_bridge.h"
#include "mouse_motion.h"
#include "cursor_pixels.h"
#include "wayland_coordinates.h"
typedef unsigned long NSUInteger;
typedef long NSInteger;
typedef signed char BOOL;
typedef MacOBloxWaylandPoint NSPoint;
typedef MacOBloxWaylandSize NSSize;
typedef MacOBloxWaylandRect NSRect;
typedef struct objc_class *Class;
typedef struct objc_method *Method;
typedef void (*IMP)(void);
#define nil ((id)0)
#define YES 1
#define NO 0
extern char *getenv(const char *);
extern void *malloc(unsigned long);
extern void free(void *);
extern int strcmp(const char *,const char *);
extern void *dlsym(void *,const char *);
extern long write(int,const void *,unsigned long);
extern int snprintf(char *,unsigned long,const char *,...);
extern Class objc_getClass(const char *);
extern Method class_getInstanceMethod(Class,SEL);
extern IMP method_getImplementation(Method);
extern IMP method_setImplementation(Method,IMP);
extern void objc_setAssociatedObject(id,const void *,id,unsigned long);
extern id objc_getAssociatedObject(id,const void *);
extern const char *method_getTypeEncoding(Method);
extern BOOL class_addMethod(Class,SEL,IMP,const char *);
extern SEL sel_registerName(const char *);
extern int CGLRegisterNativeDisplay(void *);
extern void *eglGetDisplay(void *);
extern unsigned int eglInitialize(void *,int *,int *);
extern unsigned int eglChooseConfig(void *,const int *,void **,int,int *);
extern unsigned int eglBindAPI(unsigned int);
extern int eglGetError(void);
extern const char *eglQueryString(void *,int);
extern void *CGBitmapContextCreate(void *,unsigned long,unsigned long,unsigned long,unsigned long,const void *,unsigned int);
extern const void *CGColorSpaceCreateDeviceRGB(void);
extern void CGColorSpaceRelease(const void *);
extern void CGContextRelease(void *);
extern void *CGBitmapContextGetData(void *);
extern unsigned long CGBitmapContextGetBytesPerRow(void *);

@interface NSObject {Class isa;}
+ (id)alloc; + (id)new; + (Class)class;
- (id)init; - (id)retain; - (id)autorelease; - (void)release; - (void)dealloc;
- (BOOL)respondsToSelector:(SEL)selector;
@end
@interface NSString:NSObject
+ (id)stringWithUTF8String:(const char *)text;
- (const char *)UTF8String; - (BOOL)isEqual:(id)other;
- (id)initWithData:(id)data encoding:(NSUInteger)encoding;
- (id)dataUsingEncoding:(NSUInteger)encoding;
@end
@interface NSResponder:NSObject
- (void)interpretKeyEvents:(id)events;
@end
@interface NSNumber:NSObject
+ (id)numberWithInt:(int)value; + (id)numberWithDouble:(double)value;
+ (id)numberWithLong:(long)value;
- (long)longValue;
@end
@interface NSArray:NSObject
+ (id)arrayWithObjects:(const id *)objects count:(NSUInteger)count;
- (NSUInteger)count; - (id)objectAtIndex:(NSUInteger)index;
@end
@interface NSMutableArray:NSArray
- (void)addObject:(id)object; - (void)removeObject:(id)object;
@end
@interface NSDictionary:NSObject
+ (id)dictionaryWithObjects:(const id *)objects forKeys:(const id *)keys count:(NSUInteger)count;
@end
@interface NSMutableDictionary:NSDictionary
- (id)objectForKey:(id)key; - (void)setObject:(id)value forKey:(id)key;
- (void)removeAllObjects; - (NSArray *)allKeys;
@end
@interface NSBundle:NSObject
+ (id)bundleForClass:(Class)cls; + (id)bundleWithPath:(NSString *)path;
- (NSArray *)pathsForResourcesOfType:(NSString *)type inDirectory:(NSString *)directory;
- (BOOL)load;
@end
@interface NSException:NSObject
+ (void)raise:(NSString *)name format:(NSString *)format,...;
@end
@interface NSTimer:NSObject
+ (id)scheduledTimerWithTimeInterval:(double)interval target:(id)target selector:(SEL)selector userInfo:(id)info repeats:(BOOL)repeats;
+ (id)timerWithTimeInterval:(double)interval target:(id)target selector:(SEL)selector userInfo:(id)info repeats:(BOOL)repeats;
@end
@interface NSRunLoop:NSObject
+ (id)currentRunLoop;
- (void)addTimer:(id)timer forMode:(id)mode;
@end
@interface NSDate:NSObject
+ (double)timeIntervalSinceReferenceDate;
@end
@interface NSApplication:NSObject
+ (id)sharedApplication; - (void)terminate:(id)sender; - (void)sendEvent:(id)event;
- (id)keyWindow;
@end
@interface NSWindow:NSObject
- (NSRect)frame; - (NSUInteger)styleMask; - (NSInteger)windowNumber; - (id)firstResponder;
- (id)platformWindow; - (void)performClose:(id)sender;
- (void)platformWindow:(id)window frameChanged:(NSRect)frame didSize:(BOOL)size;
- (void)platformWindowActivated:(id)window displayIfNeeded:(BOOL)display;
- (void)platformWindowDeactivated:(id)window checkForAppDeactivation:(BOOL)check;
- (BOOL)platformWindowSetCursorEvent:(id)window;
@end
@interface NSObject (WaylandText)
- (void)insertText:(id)text;
@end
@interface NSDisplay:NSObject {NSMutableArray *_eventQueue;}
+ (id)currentDisplay;
- (void)postEvent:(id)event atStart:(BOOL)start;
- (id)nextEventMatchingMask:(unsigned long long)mask untilDate:(id)date inMode:(id)mode dequeue:(BOOL)dequeue;
@end
@interface CGWindow:NSObject @end
@interface CGSubWindow:NSObject @end
@interface NSScreen:NSObject
- (id)initWithFrame:(NSRect)frame visibleFrame:(NSRect)visible;
@end
@interface NSEvent:NSObject
+ (id)mouseEventWithType:(NSUInteger)type location:(NSPoint)point modifierFlags:(NSUInteger)flags window:(id)window clickCount:(NSInteger)count deltaX:(double)dx deltaY:(double)dy;
+ (id)keyEventWithType:(NSUInteger)type location:(NSPoint)point modifierFlags:(NSUInteger)flags timestamp:(double)time windowNumber:(NSInteger)number context:(id)context characters:(NSString *)text charactersIgnoringModifiers:(NSString *)plain isARepeat:(BOOL)repeat keyCode:(unsigned short)key;
+ (id)otherEventWithType:(NSUInteger)type location:(NSPoint)point modifierFlags:(NSUInteger)flags timestamp:(double)time windowNumber:(NSInteger)number context:(id)context subtype:(short)subtype data1:(NSInteger)first data2:(NSInteger)second;
- (NSUInteger)type; - (NSUInteger)modifierFlags; - (NSPoint)locationInWindow;
- (double)timestamp; - (NSInteger)windowNumber; - (unsigned short)keyCode;
- (NSString *)charactersIgnoringModifiers; - (BOOL)isARepeat;
- (void)_setButtonNumber:(NSInteger)button;
@end
@interface NSImage:NSObject
- (NSSize)size;
- (void)drawInRect:(NSRect)rect fromRect:(NSRect)source operation:(NSUInteger)op fraction:(double)fraction;
@end
@interface NSGraphicsContext:NSObject
+ (void)saveGraphicsState; + (void)restoreGraphicsState;
+ (void)setCurrentContext:(id)context;
+ (id)graphicsContextWithGraphicsPort:(void *)port flipped:(BOOL)flipped;
@end
@interface NSPasteboard:NSObject
- (NSString *)stringForType:(NSString *)type;
- (BOOL)setString:(NSString *)text forType:(NSString *)type;
@end

static const struct macoblox_wayland_api *api;
static BOOL initialized;
static NSMutableArray *windows;
static unsigned modifiers;
static char key_transition_key,event_flags_key,queued_input_key;
static void (*original_interpret_keys)(id,SEL,id);
/* Keep the physical event's characters available to the game, but make
 * SDL_TEXTINPUT the only source of inserted text. Darling's interpreter still
 * sees charactersIgnoringModifiers for shortcuts and navigation bindings. */
static void interpret_wayland_keys(id self,SEL cmd,NSArray *incoming) {
    NSMutableArray *events=[NSMutableArray new];
    for(NSUInteger i=0;i<[incoming count];i++) {
        NSEvent *event=[incoming objectAtIndex:i];
        if(objc_getAssociatedObject(event,&key_transition_key)) {
            NSUInteger flags=[event modifierFlags];
            unsigned short key=[event keyCode];
            /* Preserve Linux Ctrl word/document navigation in the text
             * interpreter while gameplay receives the physical Control key.
             * Darling's bindings use Command for arrows/Delete, Option for
             * backward word deletion. Shift-selection keeps its own bit. */
            if((flags&(1UL<<18)) && !(flags&((1UL<<19)|(1UL<<20)))) {
                if(key==123 || key==124 || key==115 || key==119 || key==117)
                    flags=(flags&~(1UL<<18))|(1UL<<20);
                else if(key==51)flags=(flags&~(1UL<<18))|(1UL<<19);
            }
            event=[NSEvent keyEventWithType:[event type] location:[event locationInWindow]
                modifierFlags:flags timestamp:[event timestamp]
                windowNumber:[event windowNumber] context:nil characters:@""
                charactersIgnoringModifiers:[event charactersIgnoringModifiers]
                isARepeat:[event isARepeat] keyCode:[event keyCode]];
        }
        [events addObject:event];
    }
    @try {original_interpret_keys(self,cmd,events);}
    @finally {[events release];}
}
int macoblox_wayland_key_transition(id event) {
    return [(NSNumber *)objc_getAssociatedObject(event,&key_transition_key) longValue];
}
static void tag_event(id event,unsigned flags) {
    objc_setAssociatedObject(event,&event_flags_key,[NSNumber numberWithLong:flags],1);
}
static struct {NSPoint point;NSRect frame;unsigned window;} pointer_state;
static volatile unsigned pointer_lock;
static void lock_pointer(void){while(__atomic_exchange_n(&pointer_lock,1,__ATOMIC_ACQUIRE))__asm__ volatile("pause");}
static void unlock_pointer(void){__atomic_store_n(&pointer_lock,0,__ATOMIC_RELEASE);}
static __typeof__(pointer_state) pointer_snapshot(void){lock_pointer();__typeof__(pointer_state) value=pointer_state;unlock_pointer();return value;}
static void pointer_frame(unsigned window,NSRect frame){lock_pointer();if(!pointer_state.window)pointer_state.window=window;if(pointer_state.window==window)pointer_state.frame=frame;unlock_pointer();}
static void pointer_event(unsigned window,NSRect frame,NSPoint point){lock_pointer();pointer_state.window=window;pointer_state.frame=frame;pointer_state.point=point;unlock_pointer();}
static volatile unsigned captured;

int macoblox_wayland_enabled(void) {
    const char *value=getenv("MACOBLOX_WAYLAND");return value && !strcmp(value,"1");
}
int macoblox_wayland_captured(void){return __atomic_load_n(&captured,__ATOMIC_ACQUIRE)!=0;}
static void validate_egl(void *native) {
    void *display=eglGetDisplay(native),*config=0;
    int major=0,minor=0,count=0;
    const int attributes[]={0x3033,4,0x3040,8,0x3024,8,0x3023,8,0x3022,8,0x3038};
    const char *stage=0;
    if(!display)stage="display connection";
    else if(!eglInitialize(display,&major,&minor))stage="driver initialization";
    else if(!eglBindAPI(0x30A2))stage="desktop OpenGL binding";
    else if(!eglChooseConfig(display,attributes,&config,1,&count) || count<1 || !config)stage="window configuration";
    if(stage) {
        int error=eglGetError();
        {
            const char *platform=getenv("EGL_PLATFORM"),*driver=getenv("MESA_LOADER_DRIVER_OVERRIDE");
            char line[320];
            int length=snprintf(line,sizeof line,"[Quadra Wayland] EGL %s failed: error 0x%x, native %p, display %p, platform %s, driver %s\n",
                stage,error,native,display,platform?platform:"auto",driver?driver:"auto");
            if(length>0)write(2,line,(unsigned long)length<sizeof line?(unsigned long)length:sizeof line-1);
        }
        [NSException raise:@"NSWindowServerCommunicationException" format:@"Native Wayland EGL %s failed (0x%x). Select X11 / Xwayland until this graphics driver is supported.",stage,error];
    }
    {
        const char *vendor=eglQueryString(display,0x3053),*version=eglQueryString(display,0x3054);
        const char *platform=getenv("EGL_PLATFORM"),*driver=getenv("MESA_LOADER_DRIVER_OVERRIDE");
        char line[512];
        int length=snprintf(line,sizeof line,"[Quadra Wayland] EGL initialized: native %p, display %p, version %d.%d (%s), vendor %s, platform %s, driver %s\n",
            native,display,major,minor,version?version:"unknown",vendor?vendor:"unknown",platform?platform:"auto",driver?driver:"auto");
        if(length>0)write(2,line,(unsigned long)length<sizeof line?(unsigned long)length:sizeof line-1);
    }
}
static void initialize(void) {
    if(initialized)return;
    struct elf_head {void *(*open)(const char *,int);int (*close)(void *);void *(*symbol)(void *,const char *);};
    struct elf_head **elf=dlsym((void *)-2,"_elfcalls");
    const char *path=getenv("MACOBLOX_WAYLAND_HELPER");
    void *library=path && elf && *elf?(*elf)->open(path,2):0;
    const struct macoblox_wayland_api *(*get)(void)=library?(*elf)->symbol(library,"macoblox_wayland_host_api"):0;
    if(!get || !(api=get()))
        [NSException raise:@"NSWindowServerCommunicationException" format:@"Native Wayland initialization failed. Check the Wayland session and SDL2 helper (%s).",path?path:"helper not set"];
    if(api->version!=MACOBLOX_WAYLAND_ABI)
        [NSException raise:@"NSWindowServerCommunicationException" format:@"Native Wayland helper is outdated or incompatible (ABI %u; expected %u). Rebuild Quadra before using Native Wayland.",api->version,MACOBLOX_WAYLAND_ABI];
    /* Darling reports CGL success even when eglInitialize or config selection
     * fails. Check those operations explicitly before caching its display. */
    validate_egl(api->display());
    if(CGLRegisterNativeDisplay(api->display()))
        [NSException raise:@"NSWindowServerCommunicationException" format:@"Native Wayland EGL initialization failed"];
    windows=[NSMutableArray new];
    Method interpret=class_getInstanceMethod(objc_getClass("NSResponder"),@selector(interpretKeyEvents:));
    original_interpret_keys=(void *)method_setImplementation(interpret,(IMP)interpret_wayland_keys);
    initialized=YES;
}
@interface MacOBloxWaylandWindow:CGWindow {
@public NSWindow *owner;NSRect frame;NSUInteger style;unsigned handle,buttons;void *bitmap;BOOL mapped;
}
- (id)initWithOwner:(NSWindow *)window;
@end
@interface MacOBloxWaylandSubwindow:CGSubWindow {MacOBloxWaylandWindow *parent;unsigned handle;}
- (id)initWithParent:(MacOBloxWaylandWindow *)window frame:(NSRect)value;
- (void)setFrame:(NSRect)value;
@end
static BOOL subwindow_frame(MacOBloxWaylandWindow *parent,NSRect value,int *x,int *y,int *width,int *height) {
    /* AppKit views use bottom-left coordinates. The helper's Wayland surface
     * positions use the top-left of the logical, undecorated client area. */
    double top=parent->frame.size.height-value.origin.y-value.size.height;
    if(!__builtin_isfinite(value.origin.x) || !__builtin_isfinite(top) ||
       !__builtin_isfinite(value.size.width) || !__builtin_isfinite(value.size.height) ||
       value.origin.x < -32768 || value.origin.x > 32768 || top < -32768 || top > 32768 ||
       value.size.width < 0 || value.size.height < 0 || value.size.width > 16384 || value.size.height > 16384)return NO;
    *x=(int)value.origin.x;*y=(int)top;
    *width=value.size.width<1?1:(int)value.size.width;*height=value.size.height<1?1:(int)value.size.height;
    return YES;
}
@implementation MacOBloxWaylandSubwindow
- (id)initWithParent:(MacOBloxWaylandWindow *)window frame:(NSRect)value {
    if(!(self=[super init]))return nil;
    parent=[window retain];int x,y,width,height;
    if(!parent || !parent->handle || !subwindow_frame(parent,value,&x,&y,&width,&height) ||
       !(handle=api->create_subwindow(parent->handle,x,y,width,height)))
        [NSException raise:@"NSWindowServerCommunicationException" format:@"Native Wayland view failed: %s",api->error()];
    return self;
}
- (void)dealloc{if(handle)api->destroy_subwindow(handle);[parent release];[super dealloc];}
- (void *)nativeWindow{return handle?api->subwindow_surface(handle):0;}
- (void)show{if(handle && parent->handle)api->subwindow_visible(handle,1);}
- (void)hide{if(handle)api->subwindow_visible(handle,0);}
- (void)setFrame:(NSRect)value {
    int x,y,width,height;
    if(handle && parent->handle && subwindow_frame(parent,value,&x,&y,&width,&height))
        api->subwindow_frame(handle,x,y,width,height);
}
@end
@implementation MacOBloxWaylandWindow
- (id)initWithOwner:(NSWindow *)window {
    if(!(self=[super init]))return nil;
    initialize();owner=window;frame=[window frame];style=[window styleMask];
    handle=api->create(frame.size.width,frame.size.height);
    if(!handle)[NSException raise:@"NSWindowServerCommunicationException" format:@"Native Wayland window failed: %s",api->error()];
    /* NSWindow can request fullscreen before lazily creating its platform
     * window. Apply that initial state too; retaining only the Cocoa bit
     * leaves Roblox reporting fullscreen on a decorated, windowed surface. */
    if(style&(1UL<<14))api->action(handle,MW_FULLSCREEN,1,0,0);
    pointer_frame(handle,frame);
    /* Non-owning registration: NSWindow owns its platformWindow. */
    [windows addObject:[NSNumber numberWithLong:(long)self]];
    return self;
}
- (void)setDelegate:(id)delegate{owner=delegate;}
- (id)delegate{return owner;}
- (NSUInteger)windowHandle{return handle;}
/* Inherit CGWindow's pointer identity. NSWindow.windowNumber delegates to
 * its platformWindow, so forwarding back to owner would recurse forever. */
- (NSRect)frame{return frame;}
- (NSUInteger)styleMask{return style;}
- (void)setStyleMask:(NSUInteger)value{style=value;api->action(handle,MW_FULLSCREEN,(style&(1UL<<14))!=0,0,0);}
- (void)setTitle:(NSString *)title{api->action(handle,MW_TITLE,0,0,[title UTF8String]);}
- (void)setFrame:(NSRect)value {
    frame=value;pointer_frame(handle,frame);
    api->action(handle,MW_RESIZE_WINDOW,value.size.width,value.size.height,0);
}
- (void)setLevel:(int)value{}
- (void)setOpaque:(BOOL)value{}
- (void)setAlphaValue:(double)value{}
- (void)setHasShadow:(BOOL)value{}
- (void)syncDelegateProperties{}
- (void)showWindowWithoutActivation{mapped=YES;api->action(handle,MW_SHOW,0,0,0);}
- (void)showWindowForAppActivation:(NSRect)value{[self showWindowWithoutActivation];}
- (void)hideWindowForAppDeactivation:(NSRect)value{[self hideWindow];}
- (void)hideWindow{mapped=NO;api->action(handle,MW_HIDE,0,0,0);if(captured==handle)__atomic_store_n(&captured,0,__ATOMIC_RELEASE);}
- (void)placeAboveWindow:(NSInteger)other{[self showWindowWithoutActivation];}
- (void)placeBelowWindow:(NSInteger)other{[self showWindowWithoutActivation];}
- (void)makeKey{[self showWindowWithoutActivation];}
- (void)makeMain{}
- (void)captureEvents{}
- (void)miniaturize{api->action(handle,MW_MINIMIZE,0,0,0);}
- (void)deminiaturize{[self showWindowWithoutActivation];}
- (BOOL)isMiniaturized{return NO;}
- (void)disableFlushWindow{}
- (void)enableFlushWindow{}
- (void)flushBuffer{}
- (void)flashWindow{}
- (void)addEntriesToDeviceDictionary:(id)entries{}
- (void *)cglContext{return 0;}
- (NSPoint)mouseLocationOutsideOfEventStream{
    __typeof__(pointer_state) value=pointer_snapshot();
    if(value.window==handle)return (NSPoint){value.point.x,value.frame.size.height-value.point.y};
    NSPoint global=macoblox_wayland_cocoa_point(value.point,value.frame);
    return (NSPoint){global.x-frame.origin.x,global.y-frame.origin.y};
}
- (id)createSubWindowWithFrame:(NSRect)value{return [[[MacOBloxWaylandSubwindow alloc] initWithParent:self frame:value] autorelease];}
- (id)cgContext {
    if(!bitmap){const void *color=CGColorSpaceCreateDeviceRGB();bitmap=CGBitmapContextCreate(0,frame.size.width>0?frame.size.width:1,frame.size.height>0?frame.size.height:1,8,0,color,0x2002);CGColorSpaceRelease(color);}
    return (id)bitmap;
}
- (void)invalidate {
    if(!handle)return;
    [self hideWindow];api->action(handle,MW_DESTROY,0,0,0);
    lock_pointer();if(pointer_state.window==handle)pointer_state=(__typeof__(pointer_state)){0};unlock_pointer();
    [windows removeObject:[NSNumber numberWithLong:(long)self]];
    handle=0;owner=nil;if(bitmap)CGContextRelease(bitmap);bitmap=0;
}
- (void)dealloc{[self invalidate];[super dealloc];}
@end

@interface MacOBloxWaylandPasteboard:NSPasteboard {NSString *name;NSMutableDictionary *values;NSInteger changes;}
- (id)initWithName:(NSString *)value;
@end
@implementation MacOBloxWaylandPasteboard
- (id)initWithName:(NSString *)value{if((self=[super init])){name=[value retain];values=[NSMutableDictionary new];}return self;}
- (void)dealloc{[name release];[values release];[super dealloc];}
- (NSString *)name{return name;}
- (BOOL)isGeneral{return [name isEqual:@"NSGeneralPboard"] || [name isEqual:@"Apple CFPasteboard general"];}
- (BOOL)isText:(NSString *)type{return [type isEqual:@"NSStringPboardType"] || [type isEqual:@"public.utf8-plain-text"];}
- (NSInteger)changeCount{return changes;}
- (NSInteger)clearContents{[values removeAllObjects];if([self isGeneral])api->clipboard("");return ++changes;}
- (NSInteger)declareTypes:(id)types owner:(id)owner{return [self clearContents];}
- (NSInteger)addTypes:(id)types owner:(id)owner{return ++changes;}
- (NSArray *)types{return [self isGeneral]?@[@"NSStringPboardType",@"public.utf8-plain-text"]:[values allKeys];}
- (id)dataForType:(NSString *)type {
    if(![self isGeneral])return [values objectForKey:type];
    // SDL transfers plain text only. Keeping a local RTF copy made AppKit
    // prefer its unsupported RTF importer on paste, and could also paste old
    // formatted data after another application replaced the host clipboard.
    if(![self isText:type])return nil;
    return [[NSString stringWithUTF8String:api->clipboard(0)] dataUsingEncoding:[type isEqual:@"NSStringPboardType"]?10:4];
}
- (NSString *)stringForType:(NSString *)type {
    if(![self isText:type])return [super stringForType:type];
    if([self isGeneral])return [NSString stringWithUTF8String:api->clipboard(0)];
    return [[[NSString alloc] initWithData:[self dataForType:type]
        encoding:[type isEqual:@"NSStringPboardType"]?10:4] autorelease];
}
- (BOOL)setString:(NSString *)text forType:(NSString *)type {
    if(![self isText:type])return [super setString:text forType:type];
    if(!text)return NO;
    if([self isGeneral]){api->clipboard([text UTF8String]);changes++;return YES;}
    return [self setData:[text dataUsingEncoding:[type isEqual:@"NSStringPboardType"]?10:4] forType:type];
}
- (BOOL)setData:(id)data forType:(NSString *)type {
    if(!data || !type)return NO;
    if([self isGeneral]){
        if(![self isText:type])return NO;
        NSString *text=[[[NSString alloc] initWithData:data encoding:[type isEqual:@"NSStringPboardType"]?10:4] autorelease];
        if(!text)return NO;api->clipboard([text UTF8String]);
        changes++;return YES;
    }
    [values setObject:data forKey:type];changes++;return YES;
}
@end
@interface MacOBloxWaylandCursor:NSObject {@public NSImage *image;NSPoint hot;NSString *name;}
@end
@implementation MacOBloxWaylandCursor
- (void)dealloc{[image release];[name release];[super dealloc];}
@end
@interface MacOBloxWaylandDisplay:NSDisplay
- (void)pump:(id)timer;
- (void)grabMouse:(BOOL)value;
- (void)warpMouse:(NSPoint)position;
@end
@interface MacOBloxWaylandQueuedInput:NSObject {
@public unsigned kind,flags,buttons;NSWindow *owner;MacOBloxWaylandWindow *window;NSString *text;
}
@end
@implementation MacOBloxWaylandQueuedInput
- (void)dealloc{[owner release];[window release];[text release];[super dealloc];}
@end
/* Text and focus changes must follow earlier queued key/mouse events. Calling
 * insertText inside the pump used the old responder and inserted once before
 * keyDown inserted the same character a second time. */
static id queued_input(MacOBloxWaylandWindow *window,const struct macoblox_wayland_event *input) {
    MacOBloxWaylandQueuedInput *queued=[MacOBloxWaylandQueuedInput new];
    queued->kind=input->type;queued->flags=input->modifiers;
    queued->buttons=window->buttons;
    queued->owner=[window->owner retain];queued->window=[window retain];
    if(input->type==MW_TEXT)queued->text=[[NSString stringWithUTF8String:input->text] retain];
    id event=[NSEvent otherEventWithType:15 location:(NSPoint){0,0} modifierFlags:input->modifiers
        timestamp:[NSDate timeIntervalSinceReferenceDate] windowNumber:[window->owner windowNumber]
        context:nil subtype:0 data1:0 data2:0];
    objc_setAssociatedObject(event,&queued_input_key,queued,1);[queued release];return event;
}
int macoblox_wayland_dispatch_event(id event) {
    NSNumber *flags=objc_getAssociatedObject(event,&event_flags_key);
    if(flags)modifiers=[flags longValue];
    MacOBloxWaylandQueuedInput *queued=objc_getAssociatedObject(event,&queued_input_key);
    if(!queued)return 0;
    modifiers=queued->flags;
    MacOBloxWaylandWindow *window=queued->window;NSWindow *owner=queued->owner;
    if(window->owner!=owner)return 1; // closed while the event was queued
    if(queued->kind==MW_TEXT) {
        id responder=[owner firstResponder];
        if(queued->text && [responder respondsToSelector:@selector(insertText:)])
            [responder insertText:queued->text];
    } else if(queued->kind==MW_FOCUS) {
        [owner platformWindowActivated:window displayIfNeeded:YES];
    } else if(queued->kind==MW_BLUR) {
        NSPoint point=pointer_snapshot().point;
        NSPoint location={point.x,window->frame.size.height-point.y};
        for(unsigned button=1;button<32;button++)if(queued->buttons&(1u<<button)) {
            NSEvent *up=[NSEvent mouseEventWithType:button==1?2:button==3?4:26 location:location modifierFlags:0 window:owner clickCount:1 deltaX:0 deltaY:0];
            [up _setButtonNumber:button];[[NSApplication sharedApplication] sendEvent:up];
        }
        [owner platformWindowDeactivated:window checkForAppDeactivation:YES];
    }
    return 1;
}
@implementation MacOBloxWaylandDisplay
- (id)init {
    if(!(self=[super init]))return nil;
    /* X11.backend supplies Fontconfig and named colors, without constructing
     * X11Display or opening an X connection. */
    NSBundle *bundle=[NSBundle bundleForClass:[NSDisplay class]];
    NSArray *paths=[bundle pathsForResourcesOfType:@"backend" inDirectory:@"Backends"];
    for(NSUInteger i=0;i<[paths count];i++)[[NSBundle bundleWithPath:[paths objectAtIndex:i]] load];
    const char *names[]={"allFontFamilyNames","fontTypefacesForFamilyName:","substituteFamilyName:","colorWithName:"};
    for(unsigned i=0;i<4;i++){SEL selector=sel_registerName(names[i]);Method method=class_getInstanceMethod(objc_getClass("X11Display"),selector);if(method)class_addMethod([MacOBloxWaylandDisplay class],selector,method_getImplementation(method),method_getTypeEncoding(method));}
    initialize();
    id timer=[NSTimer timerWithTimeInterval:0.004 target:self selector:@selector(pump:) userInfo:nil repeats:YES];
    id loop=[NSRunLoop currentRunLoop];
    [loop addTimer:timer forMode:@"NSDefaultRunLoopMode"];
    [loop addTimer:timer forMode:@"NSRunLoopCommonModes"];
    [loop addTimer:timer forMode:@"NSEventTrackingRunLoopMode"];
    [loop addTimer:timer forMode:@"NSModalPanelRunLoopMode"];
    return self;
}
- (void *)display{return api->display();}
- (id)nextEventMatchingMask:(unsigned long long)mask untilDate:(id)date inMode:(id)mode dequeue:(BOOL)dequeue {
    [self pump:nil];
    return [super nextEventMatchingMask:mask untilDate:date inMode:mode dequeue:dequeue];
}
- (id)newWindowWithDelegate:(id)delegate{return [[MacOBloxWaylandWindow alloc] initWithOwner:delegate];}
- (NSArray *)screens {
    int w,h;double hz;api->screen(&w,&h,&hz);NSRect rect={{0,0},{w,h}};
    return @[[[[NSScreen alloc] initWithFrame:rect visibleFrame:rect] autorelease]];
}
- (NSDictionary *)currentModeForScreen:(int)index{int w,h;double hz;api->screen(&w,&h,&hz);return @{@"Width":@(w),@"Height":@(h),@"Depth":@32,@"RefreshRate":@(hz)};}
- (NSArray *)modesForScreen:(int)index{return @[[self currentModeForScreen:index]];}
- (BOOL)setMode:(id)mode forScreen:(int)index{return NO;}
- (NSRect)insetRect:(NSRect)frame forNativeWindowBorderWithStyle:(NSUInteger)style{return frame;}
- (NSRect)outsetRect:(NSRect)frame forNativeWindowBorderWithStyle:(NSUInteger)style{return frame;}
- (NSPoint)mouseLocation{__typeof__(pointer_state) value=pointer_snapshot();return macoblox_wayland_cocoa_point(value.point,value.frame);}
- (NSUInteger)currentModifierFlags{return modifiers;}
- (NSArray *)orderedWindowNumbers{return @[];}
- (double)textCaretBlinkInterval{return 0.5;}
- (double)doubleClickInterval{return 0.5;}
- (double)scrollerWidth{return 15;}
- (id)draggingManager{return nil;}
- (void)beep{}
- (void)_addSystemColor:(id)color forName:(id)name{}
- (int)keyboardLayoutId{return 0;}
- (void)keyboardLayoutName:(id *)name fullName:(id *)full{if(name)*name=@"Wayland";if(full)*full=@"Wayland keyboard";}
- (void *)keyboardLayout:(unsigned int *)length{if(length)*length=0;return 0;}
- (id)pasteboardWithName:(NSString *)name {
    static NSMutableDictionary *boards;if(!boards)boards=[NSMutableDictionary new];
    id board=[boards objectForKey:name];if(!board){board=[[[MacOBloxWaylandPasteboard alloc] initWithName:name] autorelease];[boards setObject:board forKey:name];}return board;
}
- (void)hideCursor{api->action(0,MW_CURSOR_VISIBLE,0,0,0);}
- (void)unhideCursor{api->action(0,MW_CURSOR_VISIBLE,1,0,0);}
- (id)cursorWithName:(NSString *)name{MacOBloxWaylandCursor *cursor=[MacOBloxWaylandCursor new];cursor->name=[name retain];return [cursor autorelease];}
- (id)cursorWithImage:(NSImage *)image hotSpot:(NSPoint)hot{MacOBloxWaylandCursor *cursor=[MacOBloxWaylandCursor new];cursor->image=[image retain];cursor->hot=hot;return [cursor autorelease];}
- (void)setCursor:(MacOBloxWaylandCursor *)cursor {
    if(!cursor)return;
    static MacOBloxWaylandCursor *applied;
    if(applied==cursor)return;
    [cursor retain];[applied release];applied=cursor;
    if(!cursor->image){api->cursor(0,0,0,0,0,0,[cursor->name UTF8String]);return;}
    NSSize size=[cursor->image size];
    if(!__builtin_isfinite(size.width) || !__builtin_isfinite(size.height) ||
       size.width<1 || size.height<1 || size.width>1024 || size.height>1024)return;
    unsigned long width=(unsigned long)size.width,height=(unsigned long)size.height;
    unsigned long source_width=0,source_height=0;
    unsigned int *pixels=macoblox_cursor_pixels_from_image(cursor->image,&source_width,&source_height);
    if(pixels) {
        unsigned int *logical=pixels;
        if(source_width!=width || source_height!=height) {
            logical=malloc(width*height*4);
            if(!logical){free(pixels);return;}
            for(unsigned long row=0;row<height;row++)
                for(unsigned long column=0;column<width;column++)
                    logical[row*width+column]=macoblox_cursor_sample_argb(pixels,source_width,source_height,
                        ((double)column+0.5)*source_width/width-0.5,
                        ((double)row+0.5)*source_height/height-0.5);
        }
        /* Copy the source bitmap directly: Darling's NSImage drawing can
         * corrupt the channels at translucent cursor edges. Keep the logical
         * size/hot spot when a representation uses more backing pixels. */
        api->cursor(logical,width,height,width*4,cursor->hot.x,cursor->hot.y,0);
        if(logical!=pixels)free(logical);
        free(pixels);
        return;
    }
    const void *color=CGColorSpaceCreateDeviceRGB();void *context=CGBitmapContextCreate(0,size.width,size.height,8,0,color,0x2002);CGColorSpaceRelease(color);if(!context)return;
    [NSGraphicsContext saveGraphicsState];[NSGraphicsContext setCurrentContext:[NSGraphicsContext graphicsContextWithGraphicsPort:context flipped:NO]];
    [cursor->image drawInRect:(NSRect){{0,0},size} fromRect:(NSRect){{0,0},{0,0}} operation:1 fraction:1];
    [NSGraphicsContext restoreGraphicsState];
    api->cursor(CGBitmapContextGetData(context),size.width,size.height,CGBitmapContextGetBytesPerRow(context),cursor->hot.x,cursor->hot.y,0);CGContextRelease(context);
}
- (void)grabMouse:(BOOL)value {
    unsigned handle=pointer_snapshot().window;
    /* Host acknowledgement determines actual capture; preserve intent on blur. */
    if(!value) {
        unsigned old=__atomic_exchange_n(&captured,0,__ATOMIC_ACQ_REL);
        if(old)api->action(old,MW_LOCK,0,0,0);
        if(handle && handle!=old)api->action(handle,MW_LOCK,0,0,0);
    } else if(handle)api->action(handle,MW_LOCK,1,0,0);
}
- (void)warpMouse:(NSPoint)position {
    __typeof__(pointer_state) value=pointer_snapshot();
    if(!value.window)return;int w,h;double hz;api->screen(&w,&h,&hz);
    NSPoint local;
    if(!macoblox_wayland_local_warp(position,value.frame,h,&local))return;
    api->action(value.window,MW_WARP,local.x,local.y,0);
}
- (void)pump:(id)timer {
    static BOOL pumping;if(pumping)return;pumping=YES;
    static BOOL traced;
    if(!traced && getenv("MACOBLOX_TRACE_WAYLAND")){traced=YES;write(2,"[Quadra Wayland] AppKit pump active\n",sizeof("[Quadra Wayland] AppKit pump active\n")-1);}
    @try {
        struct macoblox_wayland_event input;
        for(unsigned i=0;i<256 && api->poll(&input);i++) {
            MacOBloxWaylandWindow *window=nil;
            for(NSUInteger j=0;j<[windows count];j++){MacOBloxWaylandWindow *candidate=(void *)[(NSNumber *)[windows objectAtIndex:j] longValue];if(candidate->handle==input.window){window=candidate;break;}}
            if(!window || !window->owner)continue;
            NSWindow *owner=window->owner;
            if(input.type==MW_CAPTURE){__atomic_store_n(&captured,input.button?input.window:0,__ATOMIC_RELEASE);continue;}
            if(input.type==MW_RESIZE){window->frame.size=(NSSize){input.x,input.y};pointer_frame(window->handle,window->frame);if(window->bitmap)CGContextRelease(window->bitmap);window->bitmap=0;[owner platformWindow:window frameChanged:window->frame didSize:YES];continue;}
            if(input.type==MW_CLOSE){[owner performClose:nil];continue;}
            if(input.type==MW_TEXT || input.type==MW_FOCUS || input.type==MW_BLUR){
                if(input.type==MW_FOCUS)pointer_event(input.window,window->frame,(NSPoint){input.x,input.y});
                if(input.type==MW_BLUR)__atomic_store_n(&captured,0,__ATOMIC_RELEASE);
                [self postEvent:queued_input(window,&input) atStart:NO];
                if(input.type==MW_BLUR)window->buttons=0;
                continue;
            }
            if(input.type==MW_KEY_DOWN || input.type==MW_KEY_UP){
                if(input.key==0xffff)continue;NSString *text=[NSString stringWithUTF8String:input.text];
                unsigned type=(input.key>=54 && input.key<=62)?12:input.type==MW_KEY_DOWN?10:11;
                NSPoint point=pointer_snapshot().point;
                id event=[NSEvent keyEventWithType:type location:(NSPoint){point.x,window->frame.size.height-point.y} modifierFlags:input.modifiers timestamp:[NSDate timeIntervalSinceReferenceDate] windowNumber:[owner windowNumber] context:nil characters:text charactersIgnoringModifiers:text isARepeat:input.repeat keyCode:input.key];
                tag_event(event,input.modifiers);
                objc_setAssociatedObject(event,&key_transition_key,[NSNumber numberWithInt:input.type==MW_KEY_DOWN?1:2],1);
                [self postEvent:event atStart:NO];continue;
            }
            pointer_event(input.window,window->frame,(NSPoint){input.x,input.y});NSPoint location={input.x,window->frame.size.height-input.y};unsigned type=5;
            if(input.type==MW_DOWN || input.type==MW_UP){if(input.button<32){if(input.type==MW_DOWN)window->buttons|=1u<<input.button;else window->buttons&=~(1u<<input.button);}type=input.button==1?(input.type==MW_DOWN?1:2):input.button==3?(input.type==MW_DOWN?3:4):(input.type==MW_DOWN?25:26);}
            else if(input.type==MW_SCROLL)type=22;
            else type=macoblox_mouse_motion_event(window->buttons,
                __atomic_load_n(&captured,__ATOMIC_ACQUIRE)==window->handle,&input.button);
            /* Existing deltaY compatibility hook flips Cocoa's vertical delta. */
            NSEvent *event=[NSEvent mouseEventWithType:type location:location modifierFlags:input.modifiers window:owner clickCount:input.clicks?:1 deltaX:input.dx deltaY:input.type==MW_SCROLL?input.dy:-input.dy];
            tag_event(event,input.modifiers);
            [event _setButtonNumber:input.button];[self postEvent:event atStart:NO];
            if(input.type==MW_MOTION)[owner platformWindowSetCursorEvent:window];
        }
    } @finally {pumping=NO;}
}
@end
id macoblox_wayland_display(void){return [[MacOBloxWaylandDisplay alloc] init];}
int macoblox_wayland_associate(unsigned int connected) {
    extern id objc_msgSend(id,SEL,...);
    MacOBloxWaylandDisplay *display=((id(*)(id,SEL))objc_msgSend)((id)objc_getClass("NSDisplay"),sel_registerName("currentDisplay"));
    [display grabMouse:!connected];return 0;
}
int macoblox_wayland_warp(NSPoint position) {
    extern id objc_msgSend(id,SEL,...);
    MacOBloxWaylandDisplay *display=((id(*)(id,SEL))objc_msgSend)((id)objc_getClass("NSDisplay"),sel_registerName("currentDisplay"));
    [display warpMouse:position];return 0;
}
/* Metal views (prototype/metal-vulkan/framework/QMLayer.m): a subsurface of the window's own
 * Wayland surface, for a Vulkan swapchain. The frame is the view's rectangle
 * in window coordinates, as an AppKit GL view's subwindow gets it. */
static BOOL metal_view_parent(id platform) {
    extern Class object_getClass(id);
    return platform && object_getClass(platform)==(Class)objc_getClass("MacOBloxWaylandWindow");
}
unsigned macoblox_wayland_metal_view(id window,NSRect value,void **display,void **surface) {
    if(!api || !window || !display || !surface)return 0;
    id platform=[window platformWindow];
    if(!metal_view_parent(platform))return 0;
    MacOBloxWaylandWindow *parent=platform;int x,y,width,height;
    if(!parent->handle || !subwindow_frame(parent,value,&x,&y,&width,&height))return 0;
    unsigned view=api->create_subwindow(parent->handle,x,y,width,height);
    if(!view){char line[300];int length=snprintf(line,sizeof line,"[Quadra Wayland] Metal view failed: %s\n",api->error());if(length>0)write(2,line,length);return 0;}
    *display=api->display();*surface=api->subwindow_wl_surface(view);
    if(!*surface){api->destroy_subwindow(view);return 0;}
    return view;
}
void macoblox_wayland_metal_view_frame(unsigned view,id window,NSRect value) {
    id platform=window?[window platformWindow]:nil;int x,y,width,height;
    if(!api || !view || !metal_view_parent(platform))return;
    if(subwindow_frame((MacOBloxWaylandWindow *)platform,value,&x,&y,&width,&height))api->subwindow_frame(view,x,y,width,height);
}
void macoblox_wayland_metal_view_destroy(unsigned view){if(api && view)api->destroy_subwindow(view);}
