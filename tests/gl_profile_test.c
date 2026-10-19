/* Native regression: this includes the wrappers so their driver calls can be mocked. */
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../gl_profile.c"

static void *mock_context = (void *)1;
static void *mock_display = (void *)2;
static void *mock_surface = (void *)3;
static const unsigned char *mock_renderer = (const unsigned char *)"AMD Radeon A";
static unsigned long long clock_ticks;
static unsigned int time_numer = 3, time_denom = 2;
static char logged[4096];
static unsigned long log_length;
static int swaps, mapped, destroyed, colormap_queries, selected_screen;
static int old_map_state = 2;
static int swap_interval, fail_interval;
static int mock_egl_error = 0x3000;

long write(int fd, const void *data, unsigned long length) {
    (void)fd;
    assert(log_length + length < sizeof logged);
    memcpy(logged + log_length, data, length);
    log_length += length;
    logged[log_length] = 0;
    return (long)length;
}

void *eglGetCurrentContext(void) { return mock_context; }
void *eglGetCurrentDisplay(void) { return mock_display; }
void *eglGetCurrentSurface(int which) { (void)which; return mock_surface; }
const unsigned char *glGetString(unsigned int name) {
    return name == 0x1F01 ? mock_renderer : (const unsigned char *)"4.6";
}
unsigned long long mach_absolute_time(void) { return clock_ticks; }
int mach_timebase_info(macoblox_timebase *info) {
    info->numer = time_numer;
    info->denom = time_denom;
    return 0;
}
unsigned int eglSwapInterval(void *display, int interval) {
    assert(display == mock_display);
    swaps++;
    if (fail_interval) {
        mock_egl_error = 0x300D;
        return 0;
    }
    swap_interval = interval;
    return 1;
}
/* Model Darling's successful CGL setter reaching the EGL interposer. */
int CGLSetParameter(void *context, int parameter, const int *value) {
    (void)context;
    if (parameter != 222) return 0;
    return macoblox_eglSwapInterval(mock_display, *value) ? 0 : 10008;
}
void *eglCreateContext(void *display, void *config, void *share, const int *attributes) {
    (void)display; (void)config; (void)share; (void)attributes;
    return (void *)4;
}
unsigned int eglChooseConfig(void *display, const int *attributes, void **configs, int count, int *found) {
    (void)display; (void)attributes; (void)configs; (void)count;
    *found = 0;
    return 0;
}
unsigned int eglGetConfigAttrib(void *display, void *config, int attribute, int *value) {
    (void)display; (void)config; (void)attribute; *value = 0; return 0;
}
void *eglCreateWindowSurface(void *display, void *config, unsigned long window, const int *attributes) {
    (void)display; (void)config; (void)window; (void)attributes; return mock_surface;
}
int eglGetError(void) { int error = mock_egl_error; mock_egl_error = 0x3000; return error; }
unsigned int eglBindAPI(unsigned int api) { assert(api == 0x30A2); return 1; }
void *CGLGetCurrentContext(void) { return mock_context; }
int CGLSetCurrentContext(void *context) { mock_context = context; return 0; }
int macoblox_raw_x_visuals(unsigned int window, unsigned int *root, unsigned int *visual) {
    (void)window; (void)root; (void)visual; return 0;
}
int macoblox_wayland_enabled(void) { return 0; }

static int x_attributes(void *display, XID window, void *output) {
    (void)display;
    memset(output, 0, 256);
    int *geometry = output;
    geometry[2] = 640;
    geometry[3] = 480;
    *(void **)((unsigned char *)output + 24) = (void *)9;
    *(int *)((unsigned char *)output + 92) = window == 10 ? 2 : old_map_state;
    *(void **)((unsigned char *)output + 128) = (void *)7;
    return 1;
}
static int x_screen(void *display) { (void)display; return 0; }
static int x_screen_number(void *screen) { return (int)(unsigned long)screen; }
static int x_depth(void *display, int screen) { (void)display; selected_screen = screen; return 24; }
static void *x_visual(void *display, int screen) { (void)display; selected_screen = screen; return (void *)8; }
static XID x_colormap(void *display, int screen) {
    (void)display; assert(screen == 7); colormap_queries++; return 42;
}
static XID x_create(void *display, XID parent, int x, int y, unsigned int width,
                    unsigned int height, unsigned int border, int depth, unsigned int cls,
                    void *visual, unsigned long mask, void *attributes) {
    (void)display; (void)x; (void)y; (void)border; (void)cls; (void)mask;
    assert(parent == 10 && width == 640 && height == 480 && depth == 24 && visual == (void *)8);
    assert(*(XID *)((unsigned char *)attributes + 96) == 42);
    return 30;
}
static int x_map(void *display, XID window) { (void)display; assert(window == 30); mapped++; return 1; }
static int x_destroy(void *display, XID window) { (void)display; assert(window == 20); destroyed++; return 1; }
void *dlsym(void *handle, const char *name) {
    (void)handle;
    if (!strcmp(name, "XGetWindowAttributes")) return (void *)x_attributes;
    if (!strcmp(name, "XDefaultScreen")) return (void *)x_screen;
    if (!strcmp(name, "XScreenNumberOfScreen")) return (void *)x_screen_number;
    if (!strcmp(name, "XDefaultDepth")) return (void *)x_depth;
    if (!strcmp(name, "XDefaultVisual")) return (void *)x_visual;
    if (!strcmp(name, "XDefaultColormap")) return (void *)x_colormap;
    if (!strcmp(name, "XCreateWindow")) return (void *)x_create;
    if (!strcmp(name, "XMapWindow")) return (void *)x_map;
    if (!strcmp(name, "XDestroyWindow")) return (void *)x_destroy;
    return NULL;
}

static void clear_log(void) { log_length = 0; logged[0] = 0; }

int main(int argc, char **argv) {
    if (argc == 2 && !strcmp(argv[1], "--fps-drop")) {
        setenv("MACOBLOX_FPS_LOG", "0", 1);
        time_numer = time_denom = 1;
        clock_ticks = 1;
        macoblox_frame_presented(mock_display, mock_surface, 1);
        for (int i=0;i<300;i++) {
            clock_ticks += 16666667;
            macoblox_frame_presented(mock_display, mock_surface, 1);
        }
        assert(!log_length); /* Normal play is quiet without verbose FPS logs. */
        for (int i=0;i<75;i++) {
            clock_ticks += 66666667;
            macoblox_frame_presented(mock_display, mock_surface, 1);
        }
        assert(strstr(logged,"[Quadra FPS drop] fps=15.0 baseline=60.0"));
        clear_log();
        for (int i=0;i<75;i++) {
            clock_ticks += 66666667;
            macoblox_frame_presented(mock_display, mock_surface, 1);
        }
        assert(!log_length); /* One marker per drop, rather than per slow frame. */
        forget_configured_surface(mock_surface);
        macoblox_frame_presented(mock_display, mock_surface, 1);
        for (int i=0;i<75;i++) {
            clock_ticks += 66666667;
            macoblox_frame_presented(mock_display, mock_surface, 1);
        }
        assert(!log_length); /* A new surface has no inherited fast baseline. */
        puts("PASS: automatic 60-to-15 FPS evidence without verbose logging, no spam or inherited baseline");
        return 0;
    }
    unsetenv("MACOBLOX_GL_COMPAT");
    const unsigned char *first = macoblox_glGetString(0x1F01);
    assert(!strcmp((const char *)first, "Radeon A"));
    assert(first == macoblox_glGetString(0x1F01));
    mock_context = (void *)5;
    mock_renderer = (const unsigned char *)"AMD Radeon B";
    const unsigned char *second = macoblox_glGetString(0x1F01);
    assert(!strcmp((const char *)second, "Radeon B"));
    assert(!strcmp((const char *)first, "Radeon A"));
    mock_renderer = (const unsigned char *)"NVIDIA GPU";
    assert(macoblox_glGetString(0x1F01) == mock_renderer);
    macoblox_forget_gl_context((void *)1);
    macoblox_forget_gl_context((void *)5);

    clear_log();
    assert(macoblox_replace_gl_subwindow((void *)1, 10, 20) == 30);
    assert(selected_screen == 7 && mapped == 1 && destroyed == 1 && colormap_queries == 1);
    assert(log_length == strlen(logged)); /* No NUL inserted into launch logs. */
    old_map_state = 0;
    assert(macoblox_replace_gl_subwindow((void *)1, 10, 20) == 30);
    assert(mapped == 1 && destroyed == 2 && colormap_queries == 2);

    clear_log();
    macoblox_frame_presenting(NULL);
    macoblox_frame_presenting(NULL);
    assert(swaps == 1);
    forget_configured_surface(mock_surface);
    macoblox_frame_presenting(NULL);
    assert(swaps == 2);

    const int vsync_on = 1;
    assert(!CGLSetParameter(mock_context, 222, &vsync_on));
    assert(swap_interval == 1 && swaps == 3);
    macoblox_frame_presenting(NULL);
    assert(swap_interval == 0 && swaps == 4); /* A later setter cannot bypass the policy cache. */
    macoblox_frame_presenting(NULL);
    assert(swaps == 4); /* Normal frames still avoid redundant driver calls. */
    fail_interval = 1;
    assert(CGLSetParameter(mock_context, 222, &vsync_on) == 10008);
    assert(eglGetError() == 0x300D); /* Observation doesn't consume caller error state. */
    fail_interval = 0;
    macoblox_frame_presenting(NULL);
    assert(swaps == 5); /* A failed setter leaves the successful zero setting cached. */

    mock_surface = (void *)8;
    macoblox_frame_presenting(NULL);
    assert(swaps == 6);
    assert(!CGLSetParameter(mock_context, 222, &vsync_on));
    assert(swaps == 7);
    mock_surface = (void *)3;
    macoblox_frame_presenting(NULL);
    assert(swaps == 7); /* Changing another drawable doesn't invalidate this one. */
    assert(!CGLSetParameter(mock_context, 999, &vsync_on));
    macoblox_frame_presenting(NULL);
    assert(swaps == 7); /* Unrelated CGL properties leave the swap cache intact. */

    setenv("MACOBLOX_FPS_LOG", "1", 1);
    clear_log();
    clock_ticks = 100;
    macoblox_frame_presented(mock_display, mock_surface, 1);
    for (int i = 0; i < 5; i++) {
        clock_ticks += 1000000000;
        macoblox_frame_presented(mock_display, mock_surface, 0);
    }
    assert(!log_length); /* Failed swaps do not increment FPS or trigger reports. */
    clock_ticks = 100 + 4000000000ULL;
    macoblox_frame_presented(mock_display, mock_surface, 1);
    assert(strstr(logged, "0.2 surface=0x3")); /* 1 successful interval / 6 seconds. */
    clear_log();
    forget_configured_surface(mock_surface);
    macoblox_frame_presented(mock_display, mock_surface, 1);
    clock_ticks += 4000000000ULL;
    macoblox_frame_presented(mock_display, (void *)99, 1);
    assert(!log_length); /* Different/recreated surfaces start their own windows. */
    puts("PASS: immutable GPU strings, subwindow resources and successful presentation timing");
    return 0;
}
