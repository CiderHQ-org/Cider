/* Drives vr_xr.c natively against the host OpenXR runtime with a test
 * pattern, outside Darling and Roblox. Needs a running runtime (WiVRn,
 * Monado, ...) and a connected headset; not part of tests/run.sh.
 *
 *   clang -O2 -Wall -Wextra tests/vr_xr_host.c vr_xr.c -lEGL -lm -ldl -o vr-xr-host
 *   ./vr-xr-host [seconds]
 */
#include <EGL/egl.h>
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include "../vr_xr.h"

static void *host_open(const char *library) { return dlopen(library, RTLD_NOW); }
static void *host_symbol(void *library, const char *name) { return dlsym(library, name); }
static void *host_gl(const char *name) { return (void *)eglGetProcAddress(name); }
static void host_log(const char *line) { fputs(line, stderr); }

static double now(void) {
    struct timespec time;
    clock_gettime(CLOCK_MONOTONIC, &time);
    return time.tv_sec + time.tv_nsec / 1e9;
}

int main(int argc, char **argv) {
    double seconds = argc > 1 ? atof(argv[1]) : 20;
    EGLDisplay display = eglGetDisplay(EGL_DEFAULT_DISPLAY);
    EGLint major, minor, count;
    EGLConfig config;
    const EGLint attributes[] = {EGL_SURFACE_TYPE, EGL_PBUFFER_BIT, EGL_RENDERABLE_TYPE, EGL_OPENGL_BIT,
                                 EGL_RED_SIZE, 8, EGL_GREEN_SIZE, 8, EGL_BLUE_SIZE, 8, EGL_ALPHA_SIZE, 8, EGL_NONE};
    if (!eglInitialize(display, &major, &minor) || !eglBindAPI(EGL_OPENGL_API) ||
        !eglChooseConfig(display, attributes, &config, 1, &count) || count != 1) {
        fprintf(stderr, "EGL setup failed\n");
        return 1;
    }
    const EGLint pbuffer[] = {EGL_WIDTH, 16, EGL_HEIGHT, 16, EGL_NONE};
    EGLSurface surface = eglCreatePbufferSurface(display, config, pbuffer);
    EGLContext context = eglCreateContext(display, config, EGL_NO_CONTEXT, 0);
    if (!context || !eglMakeCurrent(display, surface, surface, context)) {
        fprintf(stderr, "EGL context failed\n");
        return 1;
    }
    VrXrHost host = {host_open, host_symbol, host_gl, host_log};
    int started = 0;
    for (double deadline = now() + 30; started == 0 && now() < deadline;) {
        started = vr_xr_start(&host, display, context, (void *(*)(const char *))eglGetProcAddress,
                              (int (*)(void *, void *, int, int *))eglQueryContext,
                              (int (*)(void *, const int *, void **, int, int *))eglChooseConfig);
        if (!started) {
            fprintf(stderr, "waiting for a headset...\n");
            struct timespec pause = {1, 0};
            nanosleep(&pause, 0);
        }
    }
    if (started <= 0) return 1;
    int width, height;
    vr_xr_eye_size(&width, &height);
    void (*gen_textures)(int, unsigned *) = host_gl("glGenTextures");
    void (*bind_texture)(unsigned, unsigned) = host_gl("glBindTexture");
    void (*tex_storage)(unsigned, int, unsigned, int, int) = host_gl("glTexStorage2D");
    void (*gen_framebuffers)(int, unsigned *) = host_gl("glGenFramebuffers");
    void (*bind_framebuffer)(unsigned, unsigned) = host_gl("glBindFramebuffer");
    void (*attach)(unsigned, unsigned, unsigned, unsigned, int) = host_gl("glFramebufferTexture2D");
    void (*clear_color)(float, float, float, float) = host_gl("glClearColor");
    void (*clear)(unsigned) = host_gl("glClear");
    void (*scissor)(int, int, int, int) = host_gl("glScissor");
    void (*enable)(unsigned) = host_gl("glEnable");
    void (*disable)(unsigned) = host_gl("glDisable");
    unsigned textures[2], framebuffers[2];
    gen_textures(2, textures);
    gen_framebuffers(2, framebuffers);
    for (int eye = 0; eye < 2; ++eye) {
        bind_texture(0x0DE1, textures[eye]);
        tex_storage(0x0DE1, 1, 0x8058 /* GL_RGBA8 */, width, height);
        bind_framebuffer(0x8D40, framebuffers[eye]);
        attach(0x8D40, 0x8CE0, 0x0DE1, textures[eye], 0);
    }
    unsigned long frames = 0, rendered = 0;
    double start = now(), report = start + 1;
    while (now() - start < seconds) {
        if (!vr_xr_begin_frame()) {
            struct timespec pause = {0, 5000000};
            nanosleep(&pause, 0);
            continue;
        }
        VrXrViews views;
        int located = vr_xr_locate(&views);
        /* Left eye red, right eye blue, with a centered white cross so the
         * stereo pair can be fused. */
        for (int eye = 0; eye < 2; ++eye) {
            bind_framebuffer(0x8D40, framebuffers[eye]);
            disable(0x0C11);
            clear_color(eye ? 0.1f : 0.5f, 0.1f, eye ? 0.5f : 0.1f, 1);
            clear(0x4000);
            enable(0x0C11);
            clear_color(1, 1, 1, 1);
            scissor(width / 2 - 4, height / 4, 8, height / 2);
            clear(0x4000);
            scissor(width / 4, height / 2 - 4, width / 2, 8);
            clear(0x4000);
            disable(0x0C11);
        }
        vr_xr_end_frame(framebuffers, width, height);
        if (located && views.controllers && views.changed) {
            for (int slot = 0; slot < VR_XR_INPUTS; ++slot)
                if (views.changed & (1u << slot)) fprintf(stderr, "  input slot %2d = %.2f\n", slot, views.input[slot]);
            /* Triggers vibrate their own hand; A recenters. */
            if (views.changed & (1u << 3)) vr_xr_set_haptic(0, views.input[3]);
            if (views.changed & (1u << 12)) vr_xr_set_haptic(1, views.input[12]);
            if ((views.changed & (1u << 22)) && views.input[22] > 0.5f) vr_xr_recenter();
        }
        ++frames;
        rendered += located;
        if (now() > report) {
            report += 1;
            if (located)
                fprintf(stderr, "  display %.0f Hz\n", (double)vr_xr_display_rate());
            if (located)
                fprintf(stderr, "  hands: left %s (%.2f %.2f %.2f), right %s (%.2f %.2f %.2f)\n",
                        views.hand_position_valid[0] ? "tracked" : "lost", views.hand[0].position[0],
                        views.hand[0].position[1], views.hand[0].position[2],
                        views.hand_position_valid[1] ? "tracked" : "lost", views.hand[1].position[0],
                        views.hand[1].position[1], views.hand[1].position[2]);
            if (located)
                fprintf(stderr, "frames %lu  head (%.2f %.2f %.2f) quat (%.2f %.2f %.2f %.2f)  eye x %.3f %.3f  tan %.2f %.2f %.2f %.2f\n",
                        frames, views.head.position[0], views.head.position[1], views.head.position[2],
                        views.head.orientation[0], views.head.orientation[1], views.head.orientation[2],
                        views.head.orientation[3], views.eye_offset[0][0], views.eye_offset[1][0],
                        views.tangent[0][0], views.tangent[0][1], views.tangent[0][2], views.tangent[0][3]);
            else
                fprintf(stderr, "frames %lu (no pose yet)\n", frames);
        }
    }
    fprintf(stderr, "%lu frames, %lu with poses, %.1f fps\n", frames, rendered, frames / (now() - start));
    return 0;
}
