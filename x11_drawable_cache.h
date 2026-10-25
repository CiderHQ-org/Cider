#ifndef QUADRA_X11_DRAWABLE_CACHE_H
#define QUADRA_X11_DRAWABLE_CACHE_H

/* Include after the shim's Objective-C and QuadraRect declarations. This
 * removes repeated child-window requests without bypassing NSOpenGLContext's
 * preparation or its main-thread updateViewParameters call. */
extern Method *class_copyMethodList(Class, unsigned int *);
extern unsigned int method_getNumberOfArguments(Method);
extern void method_getArgumentType(Method, unsigned int, char *, unsigned long);
extern void method_getReturnType(Method, char *, unsigned long);
extern const char *ivar_getTypeEncoding(Ivar);
extern unsigned long class_getInstanceSize(Class);
extern id objc_getAssociatedObject(id, const void *);
extern void objc_setAssociatedObject(id, const void *, id, unsigned long);
extern void free(void *);
extern int pthread_main_np(void);

typedef struct {
    void *display;
    unsigned long child, parent_window;
    id parent;
    unsigned long long epoch;
    int x, y;
    unsigned int width, height;
    int frame_known, visibility_known, visible;
} QuadraDrawableState;

static Class quadra_drawable_class, quadra_drawable_parent_class;
static long quadra_drawable_display_offset, quadra_drawable_window_offset;
static long quadra_drawable_parent_offset;
static SEL quadra_drawable_convert_selector, quadra_drawable_handle_selector;
static QuadraRect (*quadra_drawable_convert_original)(id, SEL, QuadraRect);
static void (*quadra_drawable_frame_original)(id, SEL, QuadraRect);
static void (*quadra_drawable_show_original)(id, SEL);
static void (*quadra_drawable_hide_original)(id, SEL);
static int quadra_drawable_install_state;
static unsigned int quadra_drawable_off_main_active;
static unsigned long long quadra_drawable_off_main_epoch;
static unsigned long long quadra_drawable_main_calls; /* main thread only */
static char quadra_drawable_state_key;

static int quadra_drawable_equal(const char *a, const char *b) {
    if (!a || !b) return 0;
    while (*a && *a == *b) { a++; b++; }
    return *a == *b;
}

/* Ignore struct names, but require exactly two nested pairs of doubles.
 * A size-only check could accidentally accept a different 32-byte ABI. */
static const char *quadra_drawable_struct_fields(const char *type) {
    if (!type || *type++ != '{') return 0;
    while (*type && *type != '=') {
        if (*type == '{' || *type == '}') return 0;
        type++;
    }
    return *type == '=' ? type + 1 : 0;
}

static int quadra_drawable_rect_type(const char *type) {
    const char *fields = quadra_drawable_struct_fields(type);
    if (!fields) return 0;
    for (int pair = 0; pair < 2; pair++) {
        fields = quadra_drawable_struct_fields(fields);
        if (!fields || fields[0] != 'd' || fields[1] != 'd' || fields[2] != '}') return 0;
        fields += 3;
    }
    return fields[0] == '}' && !fields[1];
}

static int quadra_drawable_method_abi(Method method, int rect_argument, int rect_return) {
    if (!method || method_getNumberOfArguments(method) != (rect_argument ? 3U : 2U)) return 0;
    char type[256] = {0};
    method_getReturnType(method, type, sizeof type);
    type[sizeof type - 1] = 0;
    if (rect_return ? !quadra_drawable_rect_type(type) : !quadra_drawable_equal(type, "v")) return 0;
    method_getArgumentType(method, 0, type, sizeof type);
    type[sizeof type - 1] = 0;
    if (!quadra_drawable_equal(type, "@")) return 0;
    method_getArgumentType(method, 1, type, sizeof type);
    type[sizeof type - 1] = 0;
    if (!quadra_drawable_equal(type, ":")) return 0;
    if (rect_argument) {
        method_getArgumentType(method, 2, type, sizeof type);
        type[sizeof type - 1] = 0;
        if (!quadra_drawable_rect_type(type)) return 0;
    }
    return 1;
}

static int quadra_drawable_owned(Class cls, Method method) {
    unsigned int count = 0;
    Method *methods = class_copyMethodList(cls, &count);
    int owned = 0;
    for (unsigned int index = 0; methods && index < count; index++)
        if (methods[index] == method) { owned = 1; break; }
    free(methods);
    return owned;
}

static int quadra_drawable_ivar(Class cls, const char *name, char kind, long *offset) {
    Ivar ivar = class_getInstanceVariable(cls, name);
    const char *type = ivar ? ivar_getTypeEncoding(ivar) : 0;
    if (!type || type[0] != kind || (kind == 'Q' && type[1])) return 0;
    long position = ivar_getOffset(ivar);
    unsigned long size = class_getInstanceSize(cls);
    if (position < (long)sizeof(void *) || (unsigned long)position % sizeof(void *) ||
        size < sizeof(void *) || (unsigned long)position > size - sizeof(void *)) return 0;
    *offset = position;
    return 1;
}

static int quadra_drawable_epoch_valid(unsigned long long epoch) {
    return !__atomic_load_n(&quadra_drawable_off_main_active, __ATOMIC_ACQUIRE) &&
        __atomic_load_n(&quadra_drawable_off_main_epoch, __ATOMIC_ACQUIRE) == epoch;
}

static void quadra_drawable_off_main_begin(void) {
    __atomic_add_fetch(&quadra_drawable_off_main_active, 1, __ATOMIC_ACQ_REL);
    __atomic_add_fetch(&quadra_drawable_off_main_epoch, 1, __ATOMIC_ACQ_REL);
}

static void quadra_drawable_off_main_end(void) {
    __atomic_add_fetch(&quadra_drawable_off_main_epoch, 1, __ATOMIC_RELEASE);
    __atomic_sub_fetch(&quadra_drawable_off_main_active, 1, __ATOMIC_RELEASE);
}

static int quadra_drawable_identity(id self, QuadraDrawableState *state) {
    if (!self || object_getClass(self) != quadra_drawable_class) return 0;
    state->display = *(void **)((char *)self + quadra_drawable_display_offset);
    state->child = *(unsigned long *)((char *)self + quadra_drawable_window_offset);
    state->parent = *(id *)((char *)self + quadra_drawable_parent_offset);
    if (!state->display || !state->child || !state->parent ||
        object_getClass(state->parent) != quadra_drawable_parent_class) return 0;
    state->parent_window = ((unsigned long (*)(id, SEL))objc_msgSend)(
        state->parent, quadra_drawable_handle_selector);
    return state->parent_window != 0;
}

static int quadra_drawable_same_identity(const QuadraDrawableState *a,
                                           const QuadraDrawableState *b) {
    return a->display == b->display && a->child == b->child &&
        a->parent == b->parent && a->parent_window == b->parent_window;
}

/* Only the main thread reads or changes the association. Atomic retain gives
 * the returned immutable NSData its normal safe getter lifetime. */
static void quadra_drawable_load(id self, QuadraDrawableState *state) {
    id data = objc_getAssociatedObject(self, &quadra_drawable_state_key);
    if (!data || ((unsigned long (*)(id, SEL))objc_msgSend)(data, sel_registerName("length")) != sizeof *state)
        return;
    const unsigned char *bytes = ((const unsigned char *(*)(id, SEL))objc_msgSend)(data, sel_registerName("bytes"));
    if (!bytes) return;
    QuadraDrawableState cached;
    for (unsigned long index = 0; index < sizeof cached; index++)
        ((unsigned char *)&cached)[index] = bytes[index];
    if (cached.epoch == state->epoch && quadra_drawable_same_identity(&cached, state) &&
        quadra_drawable_epoch_valid(state->epoch))
        *state = cached;
}

static void quadra_drawable_publish(id self, const QuadraDrawableState *state,
                                     unsigned long long call) {
    if (quadra_drawable_main_calls != call || !quadra_drawable_epoch_valid(state->epoch)) return;
    QuadraDrawableState current = {0};
    if (!quadra_drawable_identity(self, &current) || !quadra_drawable_same_identity(state, &current)) return;
    id data = ((id (*)(id, SEL, const void *, unsigned long))objc_msgSend)(
        (id)objc_getClass("NSData"), sel_registerName("dataWithBytes:length:"), state, sizeof *state);
    if (data && quadra_drawable_main_calls == call && quadra_drawable_epoch_valid(state->epoch)) {
        objc_setAssociatedObject(self, &quadra_drawable_state_key, data,
                                 01401UL /* OBJC_ASSOCIATION_RETAIN, atomic */);
        /* A worker may start between the last check and publication. Its
         * changed epoch makes this state unusable; never inspect it there. */
        if (!quadra_drawable_epoch_valid(state->epoch))
            objc_setAssociatedObject(self, &quadra_drawable_state_key, 0, 01401UL);
    }
}

static int quadra_drawable_geometry(QuadraRect rect, QuadraDrawableState *state) {
    if (!(rect.origin.x >= -2147483648.0 && rect.origin.x <= 2147483647.0 &&
          rect.origin.y >= -2147483648.0 && rect.origin.y <= 2147483647.0 &&
          rect.size.width >= 1.0 && rect.size.width <= 4294967295.0 &&
          rect.size.height >= 1.0 && rect.size.height <= 4294967295.0)) return 0;
    state->x = (int)rect.origin.x;
    state->y = (int)rect.origin.y;
    state->width = (unsigned int)rect.size.width;
    state->height = (unsigned int)rect.size.height;
    return 1;
}

static int quadra_drawable_same_geometry(const QuadraDrawableState *a,
                                          const QuadraDrawableState *b) {
    return a->x == b->x && a->y == b->y && a->width == b->width && a->height == b->height;
}

static void quadra_drawable_set_frame(id self, SEL cmd, QuadraRect frame) {
    if (!pthread_main_np()) {
        quadra_drawable_off_main_begin();
        @try { quadra_drawable_frame_original(self, cmd, frame); }
        @finally { quadra_drawable_off_main_end(); }
        return;
    }
    QuadraDrawableState state = {0};
    state.epoch = __atomic_load_n(&quadra_drawable_off_main_epoch, __ATOMIC_ACQUIRE);
    int supported = __atomic_load_n(&quadra_drawable_install_state, __ATOMIC_ACQUIRE) == 2 &&
        quadra_drawable_identity(self, &state) && quadra_drawable_epoch_valid(state.epoch);
    QuadraDrawableState requested = state;
    if (supported) {
        quadra_drawable_load(self, &state);
        /* Calling the original IMP handles CGRect's structure-return ABI and
         * includes the parent's current frame height and border style. */
        supported = quadra_drawable_geometry(
            quadra_drawable_convert_original(self, quadra_drawable_convert_selector, frame), &requested);
        if (supported && state.frame_known && quadra_drawable_same_geometry(&state, &requested) &&
            quadra_drawable_epoch_valid(state.epoch)) return;
    }
    objc_setAssociatedObject(self, &quadra_drawable_state_key, 0, 01401UL);
    unsigned long long call = ++quadra_drawable_main_calls;
    quadra_drawable_frame_original(self, cmd, frame);
    /* Exceptions above propagate with the previous success state removed. */
    if (supported && quadra_drawable_epoch_valid(state.epoch)) {
        QuadraDrawableState after = requested;
        if (quadra_drawable_geometry(
                quadra_drawable_convert_original(self, quadra_drawable_convert_selector, frame), &after) &&
            quadra_drawable_same_geometry(&requested, &after)) {
            state.x = requested.x; state.y = requested.y;
            state.width = requested.width; state.height = requested.height;
            state.frame_known = 1;
            quadra_drawable_publish(self, &state, call);
        }
    }
}

static void quadra_drawable_visibility(id self, SEL cmd, int visible) {
    void (*original)(id, SEL) = visible ? quadra_drawable_show_original : quadra_drawable_hide_original;
    if (!pthread_main_np()) {
        quadra_drawable_off_main_begin();
        @try { original(self, cmd); }
        @finally { quadra_drawable_off_main_end(); }
        return;
    }
    QuadraDrawableState state = {0};
    state.epoch = __atomic_load_n(&quadra_drawable_off_main_epoch, __ATOMIC_ACQUIRE);
    int supported = __atomic_load_n(&quadra_drawable_install_state, __ATOMIC_ACQUIRE) == 2 &&
        quadra_drawable_identity(self, &state) && quadra_drawable_epoch_valid(state.epoch);
    if (supported) {
        quadra_drawable_load(self, &state);
        if (state.visibility_known && state.visible == visible && quadra_drawable_epoch_valid(state.epoch)) return;
    }
    objc_setAssociatedObject(self, &quadra_drawable_state_key, 0, 01401UL);
    unsigned long long call = ++quadra_drawable_main_calls;
    original(self, cmd);
    if (supported) {
        state.visibility_known = 1;
        state.visible = visible;
        quadra_drawable_publish(self, &state, call);
    }
}

static void quadra_drawable_show(id self, SEL cmd) { quadra_drawable_visibility(self, cmd, 1); }
static void quadra_drawable_hide(id self, SEL cmd) { quadra_drawable_visibility(self, cmd, 0); }

static void quadra_install_x11_drawable_cache(Class cls) {
    if (!cls || quadra_wayland_enabled()) return;
    int expected = 0;
    if (!__atomic_compare_exchange_n(&quadra_drawable_install_state, &expected, 1, 0,
                                     __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) return;
    SEL convert_selector = sel_registerName("convertFrame:");
    Method convert = class_getInstanceMethod(cls, convert_selector);
    Method frame = class_getInstanceMethod(cls, sel_registerName("setFrame:"));
    Method show = class_getInstanceMethod(cls, sel_registerName("show"));
    Method hide = class_getInstanceMethod(cls, sel_registerName("hide"));
    Class parent_class = objc_getClass("X11Window");
    SEL handle_selector = sel_registerName("windowHandle");
    Method handle = parent_class ? class_getInstanceMethod(parent_class, handle_selector) : 0;
    char type[32] = {0};
    if (handle) method_getReturnType(handle, type, sizeof type);
    int valid = sizeof(QuadraRect) == 32 && __alignof__(QuadraRect) == 8 && sizeof(void *) == 8 &&
        quadra_drawable_owned(cls, convert) && quadra_drawable_owned(cls, frame) &&
        quadra_drawable_owned(cls, show) && quadra_drawable_owned(cls, hide) &&
        quadra_drawable_method_abi(convert, 1, 1) && quadra_drawable_method_abi(frame, 1, 0) &&
        quadra_drawable_method_abi(show, 0, 0) && quadra_drawable_method_abi(hide, 0, 0) &&
        handle && quadra_drawable_owned(parent_class, handle) &&
        method_getNumberOfArguments(handle) == 2 && quadra_drawable_equal(type, "Q") &&
        objc_getClass("NSData") &&
        quadra_drawable_ivar(cls, "_display", '^', &quadra_drawable_display_offset) &&
        quadra_drawable_ivar(cls, "_window", 'Q', &quadra_drawable_window_offset) &&
        quadra_drawable_ivar(cls, "_parent", '@', &quadra_drawable_parent_offset) &&
        quadra_drawable_display_offset != quadra_drawable_window_offset &&
        quadra_drawable_display_offset != quadra_drawable_parent_offset &&
        quadra_drawable_window_offset != quadra_drawable_parent_offset;
    if (valid) {
        method_getArgumentType(handle, 0, type, sizeof type);
        valid = quadra_drawable_equal(type, "@");
        method_getArgumentType(handle, 1, type, sizeof type);
        valid = valid && quadra_drawable_equal(type, ":");
    }
    if (!valid || !method_getImplementation(convert) || !method_getImplementation(frame) ||
        !method_getImplementation(show) || !method_getImplementation(hide)) {
        __atomic_store_n(&quadra_drawable_install_state, 3, __ATOMIC_RELEASE);
        write_str("[Quadra] X11 drawable cache skipped: unsupported backend ABI\n");
        return;
    }
    quadra_drawable_class = cls;
    quadra_drawable_parent_class = parent_class;
    quadra_drawable_convert_selector = convert_selector;
    quadra_drawable_handle_selector = handle_selector;
    quadra_drawable_convert_original = (QuadraRect (*)(id, SEL, QuadraRect))method_getImplementation(convert);
    quadra_drawable_frame_original = (void (*)(id, SEL, QuadraRect))method_getImplementation(frame);
    quadra_drawable_show_original = (void (*)(id, SEL))method_getImplementation(show);
    quadra_drawable_hide_original = (void (*)(id, SEL))method_getImplementation(hide);
    method_setImplementation(frame, (IMP)quadra_drawable_set_frame);
    method_setImplementation(show, (IMP)quadra_drawable_show);
    method_setImplementation(hide, (IMP)quadra_drawable_hide);
    __atomic_store_n(&quadra_drawable_install_state, 2, __ATOMIC_RELEASE);
    write_str("[Quadra] X11 drawable updates skip unchanged geometry and visibility\n");
}
#endif
