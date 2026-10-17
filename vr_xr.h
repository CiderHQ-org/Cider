#ifndef MACOBLOX_VR_XR_H
#define MACOBLOX_VR_XR_H

/* An OpenXR session presenting a GL renderer's two eye framebuffers. The
 * same code runs inside Darling (host libraries through _elfcalls, GL through
 * Darling's OpenGL) and in tests/vr_xr_host.c (plain dlopen). */
typedef struct {
    void *(*open)(const char *library);                 /* host dlopen */
    void *(*symbol)(void *library, const char *name);   /* host dlsym */
    void *(*gl)(const char *name);                      /* the renderer's GL entry points */
    void (*log)(const char *line);
} VrXrHost;

typedef struct {
    float position[3];
    float orientation[4]; /* x, y, z, w */
} VrXrPose;

/* Roblox's VR input slots, as the Quest build numbers them. */
#define VR_XR_INPUTS 27

typedef struct {
    int head_valid, floor_valid, eyes_valid;
    VrXrPose head;        /* view space in the LOCAL space, meters */
    VrXrPose floor;       /* STAGE origin in the LOCAL space, when the runtime has one */
    float eye_offset[2][3];  /* eye positions in the view space */
    float tangent[2][4];     /* tan of up, down, left, right half angles, all positive outward */
    int controllers;         /* actions were synced for this frame */
    int hand_position_valid[2], hand_orientation_valid[2];  /* left, right */
    VrXrPose hand[2];        /* grip position and aim orientation, LOCAL space */
    unsigned int changed;    /* bit per input slot that changed since the last frame */
    float input[VR_XR_INPUTS];
} VrXrViews;

/* On the renderer's thread with its EGL context current. Returns 1 once a
 * session exists, 0 to retry later (no runtime or no headset yet), -1 when
 * this host can never present. */
int vr_xr_start(const VrXrHost *host, void *egl_display, void *egl_context,
                void *(*egl_get_proc_address)(const char *),
                int (*egl_query_context)(void *, void *, int, int *),
                int (*egl_choose_config)(void *, const int *, void **, int, int *));
/* Fraction of the runtime's recommended eye size to render, before start. */
void vr_xr_set_render_scale(float scale);
/* 1 (default): views are located one frame ahead and submitted with the
 * next frame, as Roblox renders one frame behind its state; 0 for development. */
void vr_xr_set_submit_lag(int frames);
void vr_xr_eye_size(int *width, int *height);
/* Polls events, then waits for and begins the next frame while the session
 * runs. Returns 1 when the caller should render and later call
 * vr_xr_end_frame. */
int vr_xr_begin_frame(void);
/* Head, floor and eye data for the current frame's predicted display time. */
int vr_xr_locate(VrXrViews *views);
/* Copies each eye's GL framebuffer into its swapchain and submits. */
void vr_xr_end_frame(const unsigned int framebuffer[2], int width, int height);
int vr_xr_running(void);
/* Any thread: Roblox's device calls. Applied on the render thread. */
void vr_xr_set_haptic(int hand, float amplitude);  /* 0 left, 1 right; 0 stops */
void vr_xr_recenter(void);
void vr_xr_request_display_rate(float hertz);
/* Whether Roblox's display-rate requests reach the headset (default off:
 * the rate chosen in the runtime stays). */
void vr_xr_follow_requested_rate(int follow);
float vr_xr_display_rate(void);
/* Nanoseconds between headset frames, from the last xrWaitFrame. */
long long vr_xr_display_period(void);

#endif
