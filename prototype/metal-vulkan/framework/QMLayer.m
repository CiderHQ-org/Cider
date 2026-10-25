/* CAMetalLayer and its drawables.
 *
 * QuartzCore's CAMetalLayer is Darling's: CiderDarling's aborts on any Metal
 * selector, stock Darling's composites through GL. At the first device this
 * file makes a subclass at run time (QuartzCore links Metal, so this
 * framework cannot link QuartzCore back) and points +[CAMetalLayer
 * allocWithZone:] at it. Its drawables are swapchain images of a Vulkan
 * surface on the hosting view's own native window: an X11 child window of
 * the game window, or a Wayland subsurface from the shim's Wayland host. */
#include "qm.h"

struct objc_super {
    id receiver;
    Class super_class;
};
extern id objc_msgSendSuper(struct objc_super *super, SEL selector, ...);
extern void *objc_getAssociatedObject(id object, const void *key);
extern Class class_getSuperclass(Class cls);
extern void (*method_getImplementation(void *method))(void);
extern void *class_getInstanceMethod(Class cls, SEL name);
extern void *class_getClassMethod(Class cls, SEL name);
extern void (*method_setImplementation(void *method, void (*imp)(void)))(void);

/* The shim's native Wayland views (wayland_appkit.m), when it has them. */
typedef unsigned (*wayland_view_create)(id window, CGRect frame, void **display, void **surface);
typedef void (*wayland_view_frame)(unsigned view, id window, CGRect frame);
typedef void (*wayland_view_destroy)(unsigned view);

typedef struct {
    id device;              /* retained */
    id view;                /* the hosting NSView, not retained */
    NSUInteger pixel_format; /* 0: BGRA8Unorm */
    CGSize drawable_size;
    void *colorspace;
    NSUInteger maximum_drawable_count; /* 0: 3 */
    BOOL not_framebuffer_only, no_display_sync, no_timeout, presents_with_transaction, edr;
    id hud;                 /* retained */
    qm_mutex_t lock;
    void *surface;          /* host surface */
    BOOL surface_failed, warned_offscreen;
    qm_surface_config config;
    unsigned wayland_view;
    QMTexture *offscreen;   /* drawables without a window */
} qm_layer_state;

static Class layer_class, base_layer_class;

static qm_layer_state *state_of(id layer) {
    return object_getIndexedIvars(layer);
}

/* --- Drawables -------------------------------------------------------------- */

@implementation QMDrawable
- (id)init {
    if ((self = [super init])) {
        qm_mutex_t value = QM_MUTEX_INIT;
        lock = value;
    }
    return self;
}
- (void)dealloc {
    for (unsigned index = 0; index < presented_count; index++)
        _Block_release(presented_handlers[index]);
    free(presented_handlers);
    [texture release];
    [layer release];
    [super dealloc];
}
- (id)texture { return texture; }
- (id)layer { return layer; }
- (NSUInteger)drawableID { return (NSUInteger)(unsigned long)self; }
- (CFTimeInterval)presentedTime { return presented_time; }
- (void)addPresentedHandler:(QMDrawableHandler)block {
    if (!block)
        return;
    pthread_mutex_lock(&lock);
    presented_handlers = realloc(presented_handlers, (presented_count + 1) * sizeof *presented_handlers);
    presented_handlers[presented_count++] = _Block_copy(block);
    pthread_mutex_unlock(&lock);
}
- (void)didPresentAt:(double)time {
    pthread_mutex_lock(&lock);
    QMDrawableHandler *handlers = presented_handlers;
    unsigned count = presented_count;
    presented_handlers = 0;
    presented_count = 0;
    if (time)
        presented_time = time;
    pthread_mutex_unlock(&lock);
    for (unsigned index = 0; index < count; index++) {
        id pool = objc_autoreleasePoolPush();
        handlers[index](self);
        objc_autoreleasePoolPop(pool);
        _Block_release(handlers[index]);
    }
    free(handlers);
}
- (void)present {
    pthread_mutex_lock(&lock);
    BOOL first = !presented;
    presented = YES;
    pthread_mutex_unlock(&lock);
    if (first && handle)
        qm->drawable_present(handle);
    if (first)
        [self didPresentAt:qm_now()];
}
- (void)presentAtTime:(CFTimeInterval)time { [self present]; }
- (void)presentAfterMinimumDuration:(CFTimeInterval)duration { [self present]; }
@end

/* --- Where the frames go ------------------------------------------------------ */

static id hosting_view(id layer, qm_layer_state *state) {
    if (state->view)
        return state->view;
    id delegate = [(id<QMLayerMethods>)layer delegate];
    if (delegate && [delegate respondsToSelector:sel_registerName("window")] &&
        [delegate respondsToSelector:sel_registerName("convertRect:toView:")])
        return delegate;
    return nil;
}

typedef void (*border_widths_fn)(NSUInteger style, CGFloat *top, CGFloat *left, CGFloat *bottom, CGFloat *right);

/* The view's rectangle, top-left based, inside the native window. */
static BOOL view_geometry(id view, id window, int wayland, int *x, int *y, unsigned *width, unsigned *height, CGRect *frame) {
    CGRect rect = [(id<QMViewMethods>)view convertRect:[(id<QMViewMethods>)view bounds] toView:nil];
    CGRect window_frame = [(id<QMWindowMethods>)window frame];
    if (!(rect.size.width > 0) || !(rect.size.height > 0) || rect.size.width > 16384 || rect.size.height > 16384)
        return NO;
    *frame = rect;
    double top = window_frame.size.height - (rect.origin.y + rect.size.height), left = rect.origin.x;
    if (!wayland) {
        /* As Darling's X11SubWindow: the X window is the frame without its
         * native border. */
        static border_widths_fn widths;
        static int looked;
        if (!looked) {
            widths = (border_widths_fn)dlsym(QM_RTLD_DEFAULT, "CGNativeBorderFrameWidthsForStyle");
            looked = 1;
        }
        CGFloat border_top = 0, border_left = 0, border_bottom = 0, border_right = 0;
        if (widths)
            widths([(id<QMWindowMethods>)window styleMask], &border_top, &border_left, &border_bottom, &border_right);
        top -= border_top;
        left -= border_left;
    }
    *x = (int)left;
    *y = (int)top;
    *width = (unsigned)rect.size.width;
    *height = (unsigned)rect.size.height;
    return YES;
}

static void *make_surface(qm_layer_state *state, id window, int wayland, CGRect frame) {
    qm_surface_target target;
    memset(&target, 0, sizeof target);
    if (wayland) {
        wayland_view_create create = (wayland_view_create)dlsym(QM_RTLD_DEFAULT, "quadra_wayland_metal_view");
        if (!create) {
            qm_log("[Quadra Metal] this shim has no native Wayland Metal views");
            return 0;
        }
        void *display = 0, *surface = 0;
        state->wayland_view = create(window, frame, &display, &surface);
        if (!state->wayland_view)
            return 0;
        target.kind = QM_SURFACE_WAYLAND;
        target.wl_display = display;
        target.wl_surface = surface;
    } else {
        id platform = [(id<QMWindowMethods>)window platformWindow];
        SEL handle_selector = sel_registerName("windowHandle");
        if (!platform || ![platform respondsToSelector:handle_selector])
            return 0;
        target.kind = QM_SURFACE_X11;
        target.x11_parent = (uint64_t)(NSUInteger)objc_msgSend(platform, handle_selector);
        target.x11_display = getenv("DISPLAY");
        if (!target.x11_parent)
            return 0;
    }
    void *surface = qm->surface_new(qm_handle(qm_device), &target);
    if (!surface)
        qm_log("[Quadra Metal] no presentation surface: %s", qm->last_error());
    return surface;
}

static QMDrawable *offscreen_drawable(id layer, qm_layer_state *state, unsigned width, unsigned height) {
    if (!state->warned_offscreen) {
        state->warned_offscreen = YES;
        qm_log("[Quadra Metal] CAMetalLayer has no window yet: drawing offscreen");
    }
    if (!state->offscreen || state->offscreen->info.width != width || state->offscreen->info.height != height ||
        state->offscreen->info.pixel_format != (state->pixel_format ? state->pixel_format : 80)) {
        [state->offscreen release];
        state->offscreen = nil;
        qm_texture_desc descriptor;
        memset(&descriptor, 0, sizeof descriptor);
        descriptor.texture_type = 2;
        descriptor.pixel_format = state->pixel_format ? state->pixel_format : 80;
        descriptor.width = width;
        descriptor.height = height;
        descriptor.depth = descriptor.mipmap_level_count = descriptor.sample_count = descriptor.array_length = 1;
        descriptor.usage = 4 | 1; /* RenderTarget, ShaderRead */
        descriptor.resource_options = 2 << 4; /* Private */
        void *texture = qm->texture_new(qm_handle(qm_device), &descriptor);
        if (!texture)
            return nil;
        state->offscreen = [QMTexture newWithHandle:texture owner:nil];
    }
    QMDrawable *drawable = [QMDrawable new];
    drawable->layer = [layer retain];
    drawable->texture = [state->offscreen retain];
    return [drawable autorelease];
}

static id layer_next_drawable(id self, SEL _cmd) {
    qm_layer_state *state = state_of(self);
    if (!qm_device)
        return nil;
    pthread_mutex_lock(&state->lock);
    CGSize size = state->drawable_size;
    if (!(size.width >= 1) || !(size.height >= 1)) {
        CGRect bounds = [(id<QMLayerMethods>)self bounds];
        CGFloat scale = [(id<QMLayerMethods>)self contentsScale];
        if (!(scale > 0))
            scale = 1;
        size.width = bounds.size.width * scale;
        size.height = bounds.size.height * scale;
    }
    unsigned width = size.width >= 1 ? (unsigned)size.width : 1, height = size.height >= 1 ? (unsigned)size.height : 1;
    id view = hosting_view(self, state);
    id window = view ? [(id<QMViewMethods>)view window] : nil;
    const char *wayland_setting = getenv("QUADRA_WAYLAND");
    int wayland = wayland_setting && !strcmp(wayland_setting, "1");
    int x = 0, y = 0;
    unsigned view_width = width, view_height = height;
    CGRect frame;
    BOOL placed = window && view_geometry(view, window, wayland, &x, &y, &view_width, &view_height, &frame);
    if (placed && !state->surface && !state->surface_failed) {
        state->surface = make_surface(state, window, wayland, frame);
        state->surface_failed = !state->surface;
    }
    if (!state->surface) {
        QMDrawable *drawable = offscreen_drawable(self, state, width, height);
        pthread_mutex_unlock(&state->lock);
        return drawable;
    }
    qm_surface_config config;
    memset(&config, 0, sizeof config);
    config.x = x;
    config.y = y;
    config.width = width; /* the native window shows the drawable 1:1 */
    config.height = height;
    config.drawable_width = width;
    config.drawable_height = height;
    config.pixel_format = state->pixel_format ? state->pixel_format : 80;
    config.display_sync = !state->no_display_sync;
    config.maximum_drawable_count = state->maximum_drawable_count ? (uint32_t)state->maximum_drawable_count : 3;
    config.framebuffer_only = !state->not_framebuffer_only;
    config.visible = 1;
    if (memcmp(&config, &state->config, sizeof config)) {
        if (state->config.drawable_width != width || state->config.drawable_height != height)
            qm_log("[Quadra Metal] drawable %ux%u at %d,%d (view %ux%u)", width, height, x, y, view_width, view_height);
        if (wayland && state->wayland_view) {
            wayland_view_frame move = (wayland_view_frame)dlsym(QM_RTLD_DEFAULT, "quadra_wayland_metal_view_frame");
            if (move)
                move(state->wayland_view, window, frame);
        }
        qm->surface_configure(state->surface, &config);
        state->config = config;
    }
    void *surface = state->surface;
    /* The layer owns the surface. Keep it alive while the driver waits, with no
     * layer mutex held: AppKit must still update its state during that wait. */
    [self retain];
    pthread_mutex_unlock(&state->lock);
    void *texture = 0;
    void *drawable_handle = qm->surface_next_drawable(surface, &texture);
    if (!drawable_handle) {
        [self release];
        return nil;
    }
    QMDrawable *drawable = [QMDrawable new];
    drawable->handle = drawable_handle;
    drawable->layer = self; /* transfers the retain held across acquisition */
    drawable->texture = [QMTexture newWithHandle:texture owner:nil];
    return [drawable autorelease];
}

/* --- Properties ---------------------------------------------------------------- */

static id layer_device(id self, SEL _cmd) { return state_of(self)->device; }
static void layer_set_device(id self, SEL _cmd, id device) {
    qm_layer_state *state = state_of(self);
    [device retain];
    [state->device release];
    state->device = device;
}
static id layer_preferred_device(id self, SEL _cmd) { return qm_device; }
static NSUInteger layer_pixel_format(id self, SEL _cmd) {
    NSUInteger format = state_of(self)->pixel_format;
    return format ? format : 80;
}
static void layer_set_pixel_format(id self, SEL _cmd, NSUInteger format) { state_of(self)->pixel_format = format; }
static void *layer_colorspace(id self, SEL _cmd) { return state_of(self)->colorspace; }
static void layer_set_colorspace(id self, SEL _cmd, void *colorspace) { state_of(self)->colorspace = colorspace; }
static BOOL layer_framebuffer_only(id self, SEL _cmd) { return !state_of(self)->not_framebuffer_only; }
static void layer_set_framebuffer_only(id self, SEL _cmd, BOOL value) { state_of(self)->not_framebuffer_only = !value; }
static CGSize layer_drawable_size(id self, SEL _cmd) {
    qm_layer_state *state = state_of(self);
    if (state->drawable_size.width >= 1 && state->drawable_size.height >= 1)
        return state->drawable_size;
    CGRect bounds = [(id<QMLayerMethods>)self bounds];
    CGFloat scale = [(id<QMLayerMethods>)self contentsScale];
    if (!(scale > 0))
        scale = 1;
    CGSize size = {bounds.size.width * scale, bounds.size.height * scale};
    return size;
}
static void layer_set_drawable_size(id self, SEL _cmd, CGSize size) { state_of(self)->drawable_size = size; }
static BOOL layer_presents_with_transaction(id self, SEL _cmd) { return state_of(self)->presents_with_transaction; }
static void layer_set_presents_with_transaction(id self, SEL _cmd, BOOL value) { state_of(self)->presents_with_transaction = value; }
static BOOL layer_display_sync(id self, SEL _cmd) { return !state_of(self)->no_display_sync; }
static void layer_set_display_sync(id self, SEL _cmd, BOOL value) { state_of(self)->no_display_sync = !value; }
static BOOL layer_edr(id self, SEL _cmd) { return state_of(self)->edr; }
static void layer_set_edr(id self, SEL _cmd, BOOL value) { state_of(self)->edr = value; }
static NSUInteger layer_maximum_drawables(id self, SEL _cmd) {
    NSUInteger count = state_of(self)->maximum_drawable_count;
    return count ? count : 3;
}
static void layer_set_maximum_drawables(id self, SEL _cmd, NSUInteger count) {
    state_of(self)->maximum_drawable_count = count < 2 ? 2 : count > 3 ? 3 : count;
}
static BOOL layer_allows_timeout(id self, SEL _cmd) { return !state_of(self)->no_timeout; }
static void layer_set_allows_timeout(id self, SEL _cmd, BOOL value) { state_of(self)->no_timeout = !value; }
static id layer_hud(id self, SEL _cmd) { return state_of(self)->hud; }
static void layer_set_hud(id self, SEL _cmd, id value) {
    qm_layer_state *state = state_of(self);
    [value retain];
    [state->hud release];
    state->hud = value;
}
static id layer_nil(id self, SEL _cmd) { return nil; }
static void layer_set_ignored(id self, SEL _cmd, id value) {}

static void layer_dealloc(id self, SEL _cmd) {
    qm_layer_state *state = state_of(self);
    [state->device release];
    [state->hud release];
    [state->offscreen release];
    if (state->surface)
        qm->release(state->surface);
    if (state->wayland_view) {
        wayland_view_destroy destroy = (wayland_view_destroy)dlsym(QM_RTLD_DEFAULT, "quadra_wayland_metal_view_destroy");
        if (destroy)
            destroy(state->wayland_view);
    }
    struct objc_super super = {self, base_layer_class};
    objc_msgSendSuper(&super, _cmd);
}

/* Darling's no-Metal CAMetalLayer aborts in -forwardInvocation:; this layer
 * answers like any NSObject again. */
static NSMethodSignature *layer_method_signature(id self, SEL _cmd, SEL selector) {
    struct objc_super super = {self, (Class)objc_getClass("NSObject")};
    return (NSMethodSignature *)objc_msgSendSuper(&super, _cmd, selector);
}
static void layer_forward(id self, SEL _cmd, NSInvocation *invocation) {
    struct objc_super super = {self, (Class)objc_getClass("NSObject")};
    objc_msgSendSuper(&super, _cmd, invocation);
}

static id (*original_alloc)(id, SEL, NSZone *);
static id metal_layer_alloc(id self, SEL _cmd, NSZone *zone) {
    if ((Class)self == base_layer_class || (Class)self == layer_class) {
        id layer = class_createInstance(layer_class, sizeof(qm_layer_state));
        qm_mutex_t lock = QM_MUTEX_INIT;
        if (layer)
            state_of(layer)->lock = lock;
        return layer;
    }
    if (original_alloc)
        return original_alloc(self, _cmd, zone);
    return class_createInstance((Class)self, 0);
}

/* NSView keeps the layer it hosts; the layer learns its view here. */
static void (*original_set_layer)(id, SEL, id);
static void view_set_layer(id self, SEL _cmd, id layer) {
    original_set_layer(self, _cmd, layer);
    if (layer && layer_class && object_getClass(layer) == layer_class)
        state_of(layer)->view = self;
}

#define ADD(name, function, types) class_addMethod(layer_class, sel_registerName(name), (void (*)(void))function, types)

void qm_install_layer(void) {
    if (layer_class)
        return;
    base_layer_class = (Class)objc_getClass("CAMetalLayer");
    if (!base_layer_class) {
        qm_log("[Quadra Metal] QuartzCore has no CAMetalLayer; nothing to present to");
        return;
    }
    Class cls = objc_allocateClassPair(base_layer_class, "QMMetalLayer", 0);
    if (!cls)
        return;
    layer_class = cls;
    ADD("device", layer_device, "@@:");
    ADD("setDevice:", layer_set_device, "v@:@");
    ADD("preferredDevice", layer_preferred_device, "@@:");
    ADD("pixelFormat", layer_pixel_format, "Q@:");
    ADD("setPixelFormat:", layer_set_pixel_format, "v@:Q");
    ADD("colorspace", layer_colorspace, "^v@:");
    ADD("setColorspace:", layer_set_colorspace, "v@:^v");
    ADD("framebufferOnly", layer_framebuffer_only, "c@:");
    ADD("setFramebufferOnly:", layer_set_framebuffer_only, "v@:c");
    ADD("drawableSize", layer_drawable_size, "{CGSize=dd}@:");
    ADD("setDrawableSize:", layer_set_drawable_size, "v@:{CGSize=dd}");
    ADD("presentsWithTransaction", layer_presents_with_transaction, "c@:");
    ADD("setPresentsWithTransaction:", layer_set_presents_with_transaction, "v@:c");
    ADD("displaySyncEnabled", layer_display_sync, "c@:");
    ADD("setDisplaySyncEnabled:", layer_set_display_sync, "v@:c");
    ADD("wantsExtendedDynamicRangeContent", layer_edr, "c@:");
    ADD("setWantsExtendedDynamicRangeContent:", layer_set_edr, "v@:c");
    ADD("maximumDrawableCount", layer_maximum_drawables, "Q@:");
    ADD("setMaximumDrawableCount:", layer_set_maximum_drawables, "v@:Q");
    ADD("allowsNextDrawableTimeout", layer_allows_timeout, "c@:");
    ADD("setAllowsNextDrawableTimeout:", layer_set_allows_timeout, "v@:c");
    ADD("developerHUDProperties", layer_hud, "@@:");
    ADD("setDeveloperHUDProperties:", layer_set_hud, "v@:@");
    ADD("EDRMetadata", layer_nil, "@@:");
    ADD("setEDRMetadata:", layer_set_ignored, "v@:@");
    /* The Vulkan subsurface owns the pixels. CALayer's GL compositor must
     * never interpret a drawable or IOSurface as a CGImage. */
    ADD("contents", layer_nil, "@@:");
    ADD("setContents:", layer_set_ignored, "v@:@");
    ADD("nextDrawable", layer_next_drawable, "@@:");
    ADD("dealloc", layer_dealloc, "v@:");
    ADD("methodSignatureForSelector:", layer_method_signature, "@@::");
    ADD("forwardInvocation:", layer_forward, "v@:@");
    objc_registerClassPair(cls);

    Class meta = object_getClass((id)base_layer_class);
    void *alloc_method = class_getClassMethod(base_layer_class, sel_registerName("allocWithZone:"));
    /* Keep NSObject's (or Darling's own) for subclasses other than ours. */
    original_alloc = alloc_method ? (id (*)(id, SEL, NSZone *))method_getImplementation(alloc_method) : 0;
    class_replaceMethod(meta, sel_registerName("allocWithZone:"), (void (*)(void))metal_layer_alloc, "@@:^v");
    if (original_alloc == (id (*)(id, SEL, NSZone *))metal_layer_alloc)
        original_alloc = 0;

    Class view_class = (Class)objc_getClass("NSView");
    void *set_layer = view_class ? class_getInstanceMethod(view_class, sel_registerName("setLayer:")) : 0;
    if (set_layer) {
        original_set_layer = (void (*)(id, SEL, id))method_getImplementation(set_layer);
        method_setImplementation(set_layer, (void (*)(void))view_set_layer);
    }
    qm_log("[Quadra Metal] CAMetalLayer now presents through Vulkan");
}
