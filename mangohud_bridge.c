/* Darling calls EGL through Mach-O trampolines. Load MangoHud's host EGL
 * hooks directly, without its process-wide OpenGL dlsym/preload hooks. */
#include "graphics_context.h"
extern void quadra_frame_presented(void *, void *, unsigned int);
extern void quadra_forget_gl_context(void *);
extern void *dlsym(void *, const char *);
extern char *getenv(const char *);
extern long write(int, const void *, unsigned long);
extern unsigned int eglSwapBuffers(void *, void *);
extern unsigned int eglDestroyContext(void *, void *);

static volatile unsigned int initialized;
static unsigned int (*hud_swap)(void *, void *);
static unsigned int (*hud_destroy)(void *, void *);

static void initialize_overlay(void) {
    const char *library = getenv("QUADRA_MANGOHUD_OPENGL");
    if (!library || !*library)
        return;
    struct elf_head {
        void *(*open)(const char *, int);
        int (*close)(void *);
        void *(*symbol)(void *, const char *);
    } **elf = dlsym((void *)-2 /* RTLD_DEFAULT */, "_elfcalls");
    if (elf && *elf) {
        void *handle = (*elf)->open(library, 2 /* RTLD_NOW */);
        void *(*find)(const char *) = handle
            ? (*elf)->symbol(handle, "mangohud_find_egl_ptr") : 0;
        if (find) {
            hud_swap = find("eglSwapBuffers");
            hud_destroy = find("eglDestroyContext");
        }
    }
    static const char ready[] = "[MangoHud] Native OpenGL overlay enabled\n";
    static const char missing[] = "[MangoHud] OpenGL overlay unavailable; continuing without overlay\n";
    if (hud_swap) write(2, ready, sizeof(ready) - 1);
    else write(2, missing, sizeof(missing) - 1);
}

static unsigned int quadra_hud_swap(void *display, void *surface) {
    if (!__atomic_load_n(&initialized, __ATOMIC_ACQUIRE) &&
        __sync_bool_compare_and_swap(&initialized, 0, 1)) {
        initialize_overlay();
        __atomic_store_n(&initialized, 2, __ATOMIC_RELEASE);
    }
    /* A concurrent first swap can proceed normally while loading the overlay.
     * Publication only happens after all function pointers are initialized. */
    unsigned int result = __atomic_load_n(&initialized, __ATOMIC_ACQUIRE) == 2 && hud_swap
        ? hud_swap(display, surface) : eglSwapBuffers(display, surface);
    quadra_record_egl_swap(result);
    quadra_frame_presented(display, surface, result);
    return result;
}

static unsigned int quadra_hud_destroy(void *display, void *context) {
    unsigned int result = __atomic_load_n(&initialized, __ATOMIC_ACQUIRE) == 2 && hud_destroy
        ? hud_destroy(display, context) : eglDestroyContext(display, context);
    if (result) {
        quadra_forget_egl_context(context);
        quadra_forget_gl_context(context);
    }
    return result;
}

#define INTERPOSE(replacement, original) \
    __attribute__((used, section("__DATA,__interpose"))) \
    static const void *pair_##replacement[] = {(void *)replacement, (void *)original};
INTERPOSE(quadra_hud_swap, eglSwapBuffers)
INTERPOSE(quadra_hud_destroy, eglDestroyContext)
