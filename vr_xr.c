/* OpenXR session for Cider's VR device: an EGL-bound session on the GL
 * renderer's own context (XR_MNDX_egl_enable), one swapchain per eye, eye
 * images copied in with glBlitFramebuffer. See vr_device.c. */
#include "vr_xr.h"
#include "vr_openxr.h"

extern int snprintf(char *, unsigned long, const char *, ...);
extern float tanf(float);
extern float sqrtf(float);

#define VR_XR_IMAGES 8
#define GL_FRAMEBUFFER_SRGB 0x8DB9
#define GL_SCISSOR_TEST 0x0C11
#define GL_COLOR_WRITEMASK 0x0C23
#define GL_READ_FRAMEBUFFER 0x8CA8
#define GL_DRAW_FRAMEBUFFER 0x8CA9
#define GL_READ_FRAMEBUFFER_BINDING 0x8CAA
#define GL_DRAW_FRAMEBUFFER_BINDING 0x8CA6
#define GL_COLOR_ATTACHMENT0 0x8CE0
#define GL_TEXTURE_2D 0x0DE1
#define GL_SRGB8_ALPHA8 0x8C43
#define GL_RGBA8 0x8058
#define EGL_CONFIG_ID 0x3028
#define EGL_NONE 0x3038

static const VrXrHost *vr_host;
static PFN_xrGetInstanceProcAddr gipa;
static XrInstance instance;
static XrSystemId system_id;
static XrSession session;
static XrSpace local_space, view_space, stage_space;
static XrSpace base_space; /* LOCAL, or LOCAL re-anchored by the last recenter */
static XrSwapchain swapchains[2];
static XrSwapchainImageOpenGLKHR images[2][VR_XR_IMAGES];
static uint32_t image_counts[2];
static int eye_width, eye_height, running, frame_begun, views_located;
static float render_scale = 1;
static XrFrameState frame_state;
static XrView located[2], submitted[2];
static XrSpace located_space, submitted_space;
static int submit_lag = 1, have_submitted;
static unsigned int copy_framebuffer;

/* Controllers: one action per hand and input, numbered like the Quest
 * build's OpenXrDevice so Roblox's VR scripts see the same slots. */
typedef struct {
    const char *name, *label;
    int type, slot;
    const char *touch, *index, *simple;
} VrXrInputAction;
static const VrXrInputAction input_actions[] = {
    {"left_x", "Left X", XR_ACTION_TYPE_BOOLEAN_INPUT, 24,
     "/user/hand/left/input/x/click", "/user/hand/left/input/a/click", 0},
    {"left_y", "Left Y", XR_ACTION_TYPE_BOOLEAN_INPUT, 25,
     "/user/hand/left/input/y/click", "/user/hand/left/input/b/click", 0},
    {"left_thumbstick_click", "Left Thumbstick Click", XR_ACTION_TYPE_BOOLEAN_INPUT, 0,
     "/user/hand/left/input/thumbstick/click", "/user/hand/left/input/thumbstick/click", 0},
    {"left_menu", "Menu", XR_ACTION_TYPE_BOOLEAN_INPUT, 26,
     "/user/hand/left/input/menu/click", 0, "/user/hand/left/input/menu/click"},
    {"right_a", "Right A", XR_ACTION_TYPE_BOOLEAN_INPUT, 22,
     "/user/hand/right/input/a/click", "/user/hand/right/input/a/click", 0},
    {"right_b", "Right B", XR_ACTION_TYPE_BOOLEAN_INPUT, 23,
     "/user/hand/right/input/b/click", "/user/hand/right/input/b/click", 0},
    {"right_thumbstick_click", "Right Thumbstick Click", XR_ACTION_TYPE_BOOLEAN_INPUT, 9,
     "/user/hand/right/input/thumbstick/click", "/user/hand/right/input/thumbstick/click", 0},
    {"left_trigger", "Left Trigger", XR_ACTION_TYPE_FLOAT_INPUT, 3,
     "/user/hand/left/input/trigger/value", "/user/hand/left/input/trigger/value", "/user/hand/left/input/select/click"},
    {"left_grip", "Left Grip", XR_ACTION_TYPE_FLOAT_INPUT, 4,
     "/user/hand/left/input/squeeze/value", "/user/hand/left/input/squeeze/value", 0},
    {"left_thumbstick_x", "Left Thumbstick X", XR_ACTION_TYPE_FLOAT_INPUT, 1,
     "/user/hand/left/input/thumbstick/x", "/user/hand/left/input/thumbstick/x", 0},
    {"left_thumbstick_y", "Left Thumbstick Y", XR_ACTION_TYPE_FLOAT_INPUT, 2,
     "/user/hand/left/input/thumbstick/y", "/user/hand/left/input/thumbstick/y", 0},
    {"right_trigger", "Right Trigger", XR_ACTION_TYPE_FLOAT_INPUT, 12,
     "/user/hand/right/input/trigger/value", "/user/hand/right/input/trigger/value", "/user/hand/right/input/select/click"},
    {"right_grip", "Right Grip", XR_ACTION_TYPE_FLOAT_INPUT, 13,
     "/user/hand/right/input/squeeze/value", "/user/hand/right/input/squeeze/value", 0},
    {"right_thumbstick_x", "Right Thumbstick X", XR_ACTION_TYPE_FLOAT_INPUT, 10,
     "/user/hand/right/input/thumbstick/x", "/user/hand/right/input/thumbstick/x", 0},
    {"right_thumbstick_y", "Right Thumbstick Y", XR_ACTION_TYPE_FLOAT_INPUT, 11,
     "/user/hand/right/input/thumbstick/y", "/user/hand/right/input/thumbstick/y", 0},
};
#define VR_XR_INPUT_ACTIONS (int)(sizeof input_actions / sizeof *input_actions)
/* Hand position comes from the grip pose and orientation from the aim pose,
 * as in the Quest build. */
static const char *const pose_names[4] = {"left_grip_pose", "left_aim_pose", "right_grip_pose", "right_aim_pose"};
static const char *const pose_paths[4] = {"/user/hand/left/input/grip/pose", "/user/hand/left/input/aim/pose",
                                          "/user/hand/right/input/grip/pose", "/user/hand/right/input/aim/pose"};
static XrActionSet action_set;
static XrAction actions[VR_XR_INPUT_ACTIONS], pose_actions[4];
static XrSpace hand_spaces[4];
static XrAction haptic_actions[2];
static uint32_t haptic_bits[2];        /* requested amplitude per hand, float bits (any thread) */
static float haptic_applied[2];
static XrTime haptic_refresh[2];
static int recenter_requested;
static int refresh_extension;
static uint32_t refresh_request_bits;  /* requested Hz, float bits (any thread) */
static float refresh_requested_applied, display_rate;
static float refresh_rates[16];
static int follow_requested_rate;
static uint32_t refresh_rate_count;

static XrResult (*xrEnumerateInstanceExtensionProperties_)(const char *, uint32_t, uint32_t *, XrExtensionProperties *);
static XrResult (*xrCreateInstance_)(const XrInstanceCreateInfo *, XrInstance *);
static XrResult (*xrResultToString_)(XrInstance, XrResult, char *);
static XrResult (*xrGetSystem_)(XrInstance, const XrSystemGetInfo *, XrSystemId *);
static XrResult (*xrGetOpenGLGraphicsRequirementsKHR_)(XrInstance, XrSystemId, XrGraphicsRequirementsOpenGLKHR *);
static XrResult (*xrEnumerateViewConfigurationViews_)(XrInstance, XrSystemId, int32_t, uint32_t, uint32_t *, XrViewConfigurationView *);
static XrResult (*xrCreateSession_)(XrInstance, const XrSessionCreateInfo *, XrSession *);
static XrResult (*xrDestroySession_)(XrSession);
static XrResult (*xrBeginSession_)(XrSession, const XrSessionBeginInfo *);
static XrResult (*xrEndSession_)(XrSession);
static XrResult (*xrCreateReferenceSpace_)(XrSession, const XrReferenceSpaceCreateInfo *, XrSpace *);
static XrResult (*xrEnumerateSwapchainFormats_)(XrSession, uint32_t, uint32_t *, int64_t *);
static XrResult (*xrCreateSwapchain_)(XrSession, const XrSwapchainCreateInfo *, XrSwapchain *);
static XrResult (*xrEnumerateSwapchainImages_)(XrSwapchain, uint32_t, uint32_t *, void *);
static XrResult (*xrAcquireSwapchainImage_)(XrSwapchain, const XrSwapchainImageAcquireInfo *, uint32_t *);
static XrResult (*xrWaitSwapchainImage_)(XrSwapchain, const XrSwapchainImageWaitInfo *);
static XrResult (*xrReleaseSwapchainImage_)(XrSwapchain, const XrSwapchainImageReleaseInfo *);
static XrResult (*xrPollEvent_)(XrInstance, XrEventDataBuffer *);
static XrResult (*xrWaitFrame_)(XrSession, const XrFrameWaitInfo *, XrFrameState *);
static XrResult (*xrBeginFrame_)(XrSession, const XrFrameBeginInfo *);
static XrResult (*xrEndFrame_)(XrSession, const XrFrameEndInfo *);
static XrResult (*xrLocateViews_)(XrSession, const XrViewLocateInfo *, XrViewState *, uint32_t, uint32_t *, XrView *);
static XrResult (*xrLocateSpace_)(XrSpace, XrSpace, XrTime, XrSpaceLocation *);
static XrResult (*xrStringToPath_)(XrInstance, const char *, XrPath *);
static XrResult (*xrCreateActionSet_)(XrInstance, const XrActionSetCreateInfo *, XrActionSet *);
static XrResult (*xrCreateAction_)(XrActionSet, const XrActionCreateInfo *, XrAction *);
static XrResult (*xrSuggestInteractionProfileBindings_)(XrInstance, const XrInteractionProfileSuggestedBinding *);
static XrResult (*xrAttachSessionActionSets_)(XrSession, const XrSessionActionSetsAttachInfo *);
static XrResult (*xrCreateActionSpace_)(XrSession, const XrActionSpaceCreateInfo *, XrSpace *);
static XrResult (*xrSyncActions_)(XrSession, const XrActionsSyncInfo *);
static XrResult (*xrGetActionStateBoolean_)(XrSession, const XrActionStateGetInfo *, XrActionStateBoolean *);
static XrResult (*xrGetActionStateFloat_)(XrSession, const XrActionStateGetInfo *, XrActionStateFloat *);
static XrResult (*xrApplyHapticFeedback_)(XrSession, const XrHapticActionInfo *, const XrHapticVibration *);
static XrResult (*xrStopHapticFeedback_)(XrSession, const XrHapticActionInfo *);
static XrResult (*xrDestroySpace_)(XrSpace);
static XrResult (*xrEnumerateDisplayRefreshRatesFB_)(XrSession, uint32_t, uint32_t *, float *);
static XrResult (*xrGetDisplayRefreshRateFB_)(XrSession, float *);
static XrResult (*xrRequestDisplayRefreshRateFB_)(XrSession, float);

static void (*glGenFramebuffers_)(int, unsigned int *);
static void (*glBindFramebuffer_)(unsigned int, unsigned int);
static void (*glFramebufferTexture2D_)(unsigned int, unsigned int, unsigned int, unsigned int, int);
static void (*glBlitFramebuffer_)(int, int, int, int, int, int, int, int, unsigned int, unsigned int);
static void (*glGetIntegerv_)(unsigned int, int *);
static void (*glGetBooleanv_)(unsigned int, unsigned char *);
static unsigned char (*glIsEnabled_)(unsigned int);
static void (*glEnable_)(unsigned int);
static void (*glDisable_)(unsigned int);
static void (*glColorMask_)(unsigned char, unsigned char, unsigned char, unsigned char);

static void vr_xr_log(const char *what, XrResult result) {
    char name[64] = "", line[256];
    if (instance && xrResultToString_) xrResultToString_(instance, result, name);
    snprintf(line, sizeof line, "[Cider VR] OpenXR %s: %s (%d)\n", what, name[0] ? name : "error", (int)result);
    vr_host->log(line);
}

static int vr_xr_function(const char *name, void *slot) {
    PFN_xrVoidFunction function = 0;
    if (gipa(instance, name, &function) != XR_SUCCESS || !function) {
        char line[160];
        snprintf(line, sizeof line, "[Cider VR] OpenXR runtime lacks %s\n", name);
        vr_host->log(line);
        return 0;
    }
    __builtin_memcpy(slot, &function, sizeof function);
    return 1;
}

static int vr_xr_strings_equal(const char *left, const char *right) {
    while (*left && *left == *right) ++left, ++right;
    return *left == *right;
}

static int vr_xr_load_gl(void) {
#define GL(name) (*(void **)&name##_ = vr_host->gl(#name))
    return GL(glGenFramebuffers) && GL(glBindFramebuffer) && GL(glFramebufferTexture2D) &&
           GL(glBlitFramebuffer) && GL(glGetIntegerv) && GL(glGetBooleanv) && GL(glIsEnabled) &&
           GL(glEnable) && GL(glDisable) && GL(glColorMask);
#undef GL
}

static int vr_xr_instance(void) {
    if (!xrEnumerateInstanceExtensionProperties_ &&
        (!vr_xr_function("xrEnumerateInstanceExtensionProperties", &xrEnumerateInstanceExtensionProperties_) ||
         !vr_xr_function("xrCreateInstance", &xrCreateInstance_)))
        return -1;
    static XrExtensionProperties extensions[128];
    uint32_t count = 0;
    XrResult result = xrEnumerateInstanceExtensionProperties_(0, 0, &count, 0);
    if (result != XR_SUCCESS) {
        vr_xr_log("runtime unavailable", result);
        return 0;
    }
    if (count > 128) count = 128;
    for (uint32_t index = 0; index < count; ++index)
        extensions[index] = (XrExtensionProperties){XR_TYPE_EXTENSION_PROPERTIES, 0, "", 0};
    if (xrEnumerateInstanceExtensionProperties_(0, count, &count, extensions) != XR_SUCCESS) return 0;
    int opengl = 0, egl = 0;
    for (uint32_t index = 0; index < count; ++index) {
        opengl |= vr_xr_strings_equal(extensions[index].extensionName, "XR_KHR_opengl_enable");
        egl |= vr_xr_strings_equal(extensions[index].extensionName, "XR_MNDX_egl_enable");
        refresh_extension |= vr_xr_strings_equal(extensions[index].extensionName, "XR_FB_display_refresh_rate");
    }
    if (!opengl || !egl) {
        vr_host->log("[Cider VR] OpenXR runtime cannot take OpenGL frames over EGL (needs XR_KHR_opengl_enable and XR_MNDX_egl_enable)\n");
        return -1;
    }
    const char *enabled[] = {"XR_KHR_opengl_enable", "XR_MNDX_egl_enable", "XR_FB_display_refresh_rate"};
    XrInstanceCreateInfo create = {XR_TYPE_INSTANCE_CREATE_INFO, 0, 0, {"Roblox (Cider)", 1, "Cider", 1, XR_MAKE_VERSION(1, 0, 0)},
                                   0, 0, refresh_extension ? 3u : 2u, enabled};
    result = xrCreateInstance_(&create, &instance);
    if (result != XR_SUCCESS) {
        instance = 0;
        vr_xr_log("instance", result);
        return 0;
    }
    int loaded =
        vr_xr_function("xrResultToString", &xrResultToString_) &&
        vr_xr_function("xrGetSystem", &xrGetSystem_) &&
        vr_xr_function("xrGetOpenGLGraphicsRequirementsKHR", &xrGetOpenGLGraphicsRequirementsKHR_) &&
        vr_xr_function("xrEnumerateViewConfigurationViews", &xrEnumerateViewConfigurationViews_) &&
        vr_xr_function("xrCreateSession", &xrCreateSession_) &&
        vr_xr_function("xrDestroySession", &xrDestroySession_) &&
        vr_xr_function("xrBeginSession", &xrBeginSession_) &&
        vr_xr_function("xrEndSession", &xrEndSession_) &&
        vr_xr_function("xrCreateReferenceSpace", &xrCreateReferenceSpace_) &&
        vr_xr_function("xrEnumerateSwapchainFormats", &xrEnumerateSwapchainFormats_) &&
        vr_xr_function("xrCreateSwapchain", &xrCreateSwapchain_) &&
        vr_xr_function("xrEnumerateSwapchainImages", &xrEnumerateSwapchainImages_) &&
        vr_xr_function("xrAcquireSwapchainImage", &xrAcquireSwapchainImage_) &&
        vr_xr_function("xrWaitSwapchainImage", &xrWaitSwapchainImage_) &&
        vr_xr_function("xrReleaseSwapchainImage", &xrReleaseSwapchainImage_) &&
        vr_xr_function("xrPollEvent", &xrPollEvent_) &&
        vr_xr_function("xrWaitFrame", &xrWaitFrame_) &&
        vr_xr_function("xrBeginFrame", &xrBeginFrame_) &&
        vr_xr_function("xrEndFrame", &xrEndFrame_) &&
        vr_xr_function("xrLocateViews", &xrLocateViews_) &&
        vr_xr_function("xrLocateSpace", &xrLocateSpace_) &&
        vr_xr_function("xrStringToPath", &xrStringToPath_) &&
        vr_xr_function("xrCreateActionSet", &xrCreateActionSet_) &&
        vr_xr_function("xrCreateAction", &xrCreateAction_) &&
        vr_xr_function("xrSuggestInteractionProfileBindings", &xrSuggestInteractionProfileBindings_) &&
        vr_xr_function("xrAttachSessionActionSets", &xrAttachSessionActionSets_) &&
        vr_xr_function("xrCreateActionSpace", &xrCreateActionSpace_) &&
        vr_xr_function("xrSyncActions", &xrSyncActions_) &&
        vr_xr_function("xrGetActionStateBoolean", &xrGetActionStateBoolean_) &&
        vr_xr_function("xrGetActionStateFloat", &xrGetActionStateFloat_) &&
        vr_xr_function("xrApplyHapticFeedback", &xrApplyHapticFeedback_) &&
        vr_xr_function("xrStopHapticFeedback", &xrStopHapticFeedback_) &&
        vr_xr_function("xrDestroySpace", &xrDestroySpace_);
    if (loaded && refresh_extension &&
        !(vr_xr_function("xrEnumerateDisplayRefreshRatesFB", &xrEnumerateDisplayRefreshRatesFB_) &&
          vr_xr_function("xrGetDisplayRefreshRateFB", &xrGetDisplayRefreshRateFB_) &&
          vr_xr_function("xrRequestDisplayRefreshRateFB", &xrRequestDisplayRefreshRateFB_)))
        refresh_extension = 0;
    return loaded ? 1 : -1;
}

static void vr_xr_copy_name(char *out, unsigned long size, const char *text) {
    unsigned long index = 0;
    for (; text[index] && index + 1 < size; ++index) out[index] = text[index];
    out[index] = 0;
}

static XrPath vr_xr_path(const char *text) {
    XrPath path = 0;
    return text && xrStringToPath_(instance, text, &path) == XR_SUCCESS ? path : 0;
}

static void vr_xr_suggest(const char *profile, int column) {
    XrActionSuggestedBinding bindings[VR_XR_INPUT_ACTIONS + 6];
    uint32_t count = 0;
    for (int index = 0; index < VR_XR_INPUT_ACTIONS; ++index) {
        const VrXrInputAction *input = &input_actions[index];
        XrPath path = vr_xr_path(column == 0 ? input->touch : column == 1 ? input->index : input->simple);
        if (path) bindings[count++] = (XrActionSuggestedBinding){actions[index], path};
    }
    for (int index = 0; index < 4; ++index)
        bindings[count++] = (XrActionSuggestedBinding){pose_actions[index], vr_xr_path(pose_paths[index])};
    bindings[count++] = (XrActionSuggestedBinding){haptic_actions[0], vr_xr_path("/user/hand/left/output/haptic")};
    bindings[count++] = (XrActionSuggestedBinding){haptic_actions[1], vr_xr_path("/user/hand/right/output/haptic")};
    XrInteractionProfileSuggestedBinding suggest = {XR_TYPE_INTERACTION_PROFILE_SUGGESTED_BINDING, 0,
                                                    vr_xr_path(profile), count, bindings};
    XrResult result = xrSuggestInteractionProfileBindings_(instance, &suggest);
    if (result != XR_SUCCESS) vr_xr_log(profile, result);
}

/* Without controllers the headset still works; failures only log. */
static void vr_xr_controllers(void) {
    XrActionSetCreateInfo set = {XR_TYPE_ACTION_SET_CREATE_INFO, 0, "roblox", "Roblox", 0};
    XrResult result = xrCreateActionSet_(instance, &set, &action_set);
    if (result != XR_SUCCESS) {
        action_set = 0;
        vr_xr_log("controller actions", result);
        return;
    }
    for (int index = 0; index < VR_XR_INPUT_ACTIONS + 4; ++index) {
        XrActionCreateInfo create = {XR_TYPE_ACTION_CREATE_INFO, 0, "", 0, 0, 0, ""};
        const char *name = index < VR_XR_INPUT_ACTIONS ? input_actions[index].name : pose_names[index - VR_XR_INPUT_ACTIONS];
        vr_xr_copy_name(create.actionName, sizeof create.actionName, name);
        vr_xr_copy_name(create.localizedActionName, sizeof create.localizedActionName,
                        index < VR_XR_INPUT_ACTIONS ? input_actions[index].label : name);
        create.actionType = index < VR_XR_INPUT_ACTIONS ? input_actions[index].type : XR_ACTION_TYPE_POSE_INPUT;
        XrAction *action = index < VR_XR_INPUT_ACTIONS ? &actions[index] : &pose_actions[index - VR_XR_INPUT_ACTIONS];
        if ((result = xrCreateAction_(action_set, &create, action)) != XR_SUCCESS) {
            vr_xr_log(name, result);
            action_set = 0;
            return;
        }
    }
    static const char *const haptic_names[2] = {"left_haptic", "right_haptic"};
    for (int hand = 0; hand < 2; ++hand) {
        XrActionCreateInfo create = {XR_TYPE_ACTION_CREATE_INFO, 0, "", XR_ACTION_TYPE_VIBRATION_OUTPUT, 0, 0, ""};
        vr_xr_copy_name(create.actionName, sizeof create.actionName, haptic_names[hand]);
        vr_xr_copy_name(create.localizedActionName, sizeof create.localizedActionName, haptic_names[hand]);
        if ((result = xrCreateAction_(action_set, &create, &haptic_actions[hand])) != XR_SUCCESS) {
            vr_xr_log(haptic_names[hand], result);
            action_set = 0;
            return;
        }
    }
    vr_xr_suggest("/interaction_profiles/oculus/touch_controller", 0);
    vr_xr_suggest("/interaction_profiles/valve/index_controller", 1);
    vr_xr_suggest("/interaction_profiles/khr/simple_controller", 2);
    XrSessionActionSetsAttachInfo attach = {XR_TYPE_SESSION_ACTION_SETS_ATTACH_INFO, 0, 1, &action_set};
    if ((result = xrAttachSessionActionSets_(session, &attach)) != XR_SUCCESS) {
        vr_xr_log("attach controller actions", result);
        action_set = 0;
        return;
    }
    for (int index = 0; index < 4; ++index) {
        XrActionSpaceCreateInfo space = {XR_TYPE_ACTION_SPACE_CREATE_INFO, 0, pose_actions[index], 0,
                                         {{0, 0, 0, 1}, {0, 0, 0}}};
        if (xrCreateActionSpace_(session, &space, &hand_spaces[index]) != XR_SUCCESS) hand_spaces[index] = 0;
    }
}

static int vr_xr_session(void *display, void *context, void *(*get_proc_address)(const char *),
                         int (*query_context)(void *, void *, int, int *),
                         int (*choose_config)(void *, const int *, void **, int, int *)) {
    XrGraphicsRequirementsOpenGLKHR requirements = {XR_TYPE_GRAPHICS_REQUIREMENTS_OPENGL_KHR, 0, 0, 0};
    XrResult result = xrGetOpenGLGraphicsRequirementsKHR_(instance, system_id, &requirements);
    if (result != XR_SUCCESS) {
        vr_xr_log("OpenGL requirements", result);
        return -1;
    }
    int config_id = 0, configs = 0;
    void *config = 0;
    if (!query_context(display, context, EGL_CONFIG_ID, &config_id)) {
        vr_host->log("[Cider VR] The game's EGL context has no config\n");
        return -1;
    }
    const int attributes[] = {EGL_CONFIG_ID, config_id, EGL_NONE};
    if (!choose_config(display, attributes, &config, 1, &configs) || configs != 1) config = 0;
    XrGraphicsBindingEGLMNDX binding = {XR_TYPE_GRAPHICS_BINDING_EGL_MNDX, 0,
                                        (PFN_xrEglGetProcAddressMNDX)get_proc_address, display, config, context};
    XrSessionCreateInfo create = {XR_TYPE_SESSION_CREATE_INFO, &binding, 0, system_id};
    result = xrCreateSession_(instance, &create, &session);
    if (result != XR_SUCCESS) {
        session = 0;
        vr_xr_log("session", result);
        return -1;
    }
    XrReferenceSpaceCreateInfo space = {XR_TYPE_REFERENCE_SPACE_CREATE_INFO, 0, XR_REFERENCE_SPACE_TYPE_LOCAL,
                                        {{0, 0, 0, 1}, {0, 0, 0}}};
    if ((result = xrCreateReferenceSpace_(session, &space, &local_space)) != XR_SUCCESS) {
        vr_xr_log("local space", result);
        return -1;
    }
    space.referenceSpaceType = XR_REFERENCE_SPACE_TYPE_VIEW;
    if ((result = xrCreateReferenceSpace_(session, &space, &view_space)) != XR_SUCCESS) {
        vr_xr_log("view space", result);
        return -1;
    }
    space.referenceSpaceType = XR_REFERENCE_SPACE_TYPE_STAGE;
    if (xrCreateReferenceSpace_(session, &space, &stage_space) != XR_SUCCESS) stage_space = 0;

    int64_t formats[64], format = 0;
    uint32_t format_count = 0;
    if (xrEnumerateSwapchainFormats_(session, 64, &format_count, formats) != XR_SUCCESS) format_count = 0;
    /* Roblox's eye targets hold display-ready (sRGB-encoded) 8-bit color;
     * an sRGB swapchain receives the bytes unchanged and tells the runtime
     * how to read them. */
    for (uint32_t index = 0; index < format_count && !format; ++index)
        if (formats[index] == GL_SRGB8_ALPHA8) format = GL_SRGB8_ALPHA8;
    for (uint32_t index = 0; index < format_count && !format; ++index)
        if (formats[index] == GL_RGBA8) format = GL_RGBA8;
    if (!format) {
        vr_host->log("[Cider VR] OpenXR runtime offers no 8-bit RGBA swapchain format\n");
        return -1;
    }
    for (int eye = 0; eye < 2; ++eye) {
        XrSwapchainCreateInfo chain = {XR_TYPE_SWAPCHAIN_CREATE_INFO, 0, 0,
                                       XR_SWAPCHAIN_USAGE_COLOR_ATTACHMENT_BIT | XR_SWAPCHAIN_USAGE_TRANSFER_DST_BIT,
                                       format, 1, (uint32_t)eye_width, (uint32_t)eye_height, 1, 1, 1};
        if ((result = xrCreateSwapchain_(session, &chain, &swapchains[eye])) != XR_SUCCESS) {
            vr_xr_log("swapchain", result);
            return -1;
        }
        for (int index = 0; index < VR_XR_IMAGES; ++index)
            images[eye][index] = (XrSwapchainImageOpenGLKHR){XR_TYPE_SWAPCHAIN_IMAGE_OPENGL_KHR, 0, 0};
        if ((result = xrEnumerateSwapchainImages_(swapchains[eye], VR_XR_IMAGES, &image_counts[eye], images[eye])) !=
            XR_SUCCESS) {
            vr_xr_log("swapchain images", result);
            return -1;
        }
    }
    glGenFramebuffers_(1, &copy_framebuffer);
    base_space = local_space;
    vr_xr_controllers();
    if (refresh_extension &&
        (xrEnumerateDisplayRefreshRatesFB_(session, 16, &refresh_rate_count, refresh_rates) != XR_SUCCESS ||
         !refresh_rate_count))
        refresh_extension = 0;
    char line[200];
    snprintf(line, sizeof line, "[Cider VR] OpenXR session created: %dx%d per eye, %s swapchain, %s\n",
             eye_width, eye_height, format == GL_SRGB8_ALPHA8 ? "sRGB" : "RGBA8",
             stage_space ? "stage space available" : "no stage space");
    vr_host->log(line);
    snprintf(line, sizeof line, "[Cider VR] Controllers: %s\n",
             action_set ? "Touch, Index and generic profiles bound" : "unavailable");
    vr_host->log(line);
    return 1;
}

int vr_xr_start(const VrXrHost *host, void *display, void *context, void *(*get_proc_address)(const char *),
                int (*query_context)(void *, void *, int, int *),
                int (*choose_config)(void *, const int *, void **, int, int *)) {
    vr_host = host;
    if (session) return 1;
    if (!gipa) {
        void *loader = host->open("libopenxr_loader.so.1");
        if (!loader) loader = host->open("libopenxr_loader.so");
        gipa = loader ? (PFN_xrGetInstanceProcAddr)host->symbol(loader, "xrGetInstanceProcAddr") : 0;
        if (!gipa) {
            host->log("[Cider VR] The OpenXR loader (libopenxr_loader.so.1) is not installed\n");
            return -1;
        }
        if (!vr_xr_load_gl()) {
            host->log("[Cider VR] OpenGL framebuffer functions are missing\n");
            return -1;
        }
    }
    if (!instance) {
        int created = vr_xr_instance();
        if (created <= 0) return created;
    }
    if (!system_id) {
        XrSystemGetInfo get = {XR_TYPE_SYSTEM_GET_INFO, 0, XR_FORM_FACTOR_HEAD_MOUNTED_DISPLAY};
        XrResult result = xrGetSystem_(instance, &get, &system_id);
        if (result != XR_SUCCESS) {
            system_id = 0;
            if (result != XR_ERROR_FORM_FACTOR_UNAVAILABLE) vr_xr_log("headset", result);
            return 0;
        }
        XrViewConfigurationView views[2] = {{.type = XR_TYPE_VIEW_CONFIGURATION_VIEW}, {.type = XR_TYPE_VIEW_CONFIGURATION_VIEW}};
        uint32_t count = 0;
        result = xrEnumerateViewConfigurationViews_(instance, system_id, XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO, 2,
                                                    &count, views);
        if (result != XR_SUCCESS || count != 2) {
            vr_xr_log("stereo view configuration", result);
            return -1;
        }
        /* The swapchains match the eye targets, scaled from the runtime's
         * recommendation; the compositor stretches them to the panels. */
        eye_width = (int)(views[0].recommendedImageRectWidth * render_scale + 0.5f) & ~1;
        eye_height = (int)(views[0].recommendedImageRectHeight * render_scale + 0.5f) & ~1;
        if (eye_width > (int)views[0].maxImageRectWidth) eye_width = (int)views[0].maxImageRectWidth;
        if (eye_height > (int)views[0].maxImageRectHeight) eye_height = (int)views[0].maxImageRectHeight;
        char line[160];
        snprintf(line, sizeof line, "[Cider VR] Headset recommends %ux%u per eye; rendering %dx%d\n",
                 views[0].recommendedImageRectWidth, views[0].recommendedImageRectHeight, eye_width, eye_height);
        vr_host->log(line);
    }
    return vr_xr_session(display, context, get_proc_address, query_context, choose_config);
}

void vr_xr_set_haptic(int hand, float amplitude) {
    uint32_t bits;
    if (!(amplitude > 0)) amplitude = 0;
    __builtin_memcpy(&bits, &amplitude, sizeof bits);
    __atomic_store_n(&haptic_bits[hand ? 1 : 0], bits, __ATOMIC_RELAXED);
}

void vr_xr_recenter(void) {
    __atomic_store_n(&recenter_requested, 1, __ATOMIC_RELEASE);
}

void vr_xr_follow_requested_rate(int follow) {
    follow_requested_rate = follow ? 1 : 0;
}

void vr_xr_request_display_rate(float hertz) {
    uint32_t bits;
    __builtin_memcpy(&bits, &hertz, sizeof bits);
    __atomic_store_n(&refresh_request_bits, bits, __ATOMIC_RELAXED);
}

float vr_xr_display_rate(void) {
    return display_rate;
}

void vr_xr_set_submit_lag(int frames) {
    submit_lag = frames > 0;
}


void vr_xr_set_render_scale(float scale) {
    if (scale >= 0.25f && scale <= 2.0f) render_scale = scale;
}

void vr_xr_eye_size(int *width, int *height) {
    *width = eye_width;
    *height = eye_height;
}

long long vr_xr_display_period(void) {
    return frame_state.predictedDisplayPeriod;
}

int vr_xr_running(void) {
    return running;
}

static void vr_xr_poll(void) {
    XrEventDataBuffer event;
    for (;;) {
        event.type = XR_TYPE_EVENT_DATA_BUFFER;
        event.next = 0;
        if (xrPollEvent_(instance, &event) != XR_SUCCESS) return;
        if (event.type != XR_TYPE_EVENT_DATA_SESSION_STATE_CHANGED) continue;
        const XrEventDataSessionStateChanged *changed = (const XrEventDataSessionStateChanged *)&event;
        static const char *const names[] = {"unknown", "idle", "ready", "synchronized", "visible",
                                            "focused", "stopping", "loss pending", "exiting"};
        char line[96];
        snprintf(line, sizeof line, "[Cider VR] OpenXR session %s\n",
                 changed->state >= 0 && changed->state <= 8 ? names[changed->state] : "state changed");
        vr_host->log(line);
        if (changed->state == XR_SESSION_STATE_READY) {
            XrSessionBeginInfo begin = {XR_TYPE_SESSION_BEGIN_INFO, 0, XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO};
            XrResult result = xrBeginSession_(session, &begin);
            if (result == XR_SUCCESS) running = 1;
            else vr_xr_log("begin session", result);
        } else if (changed->state == XR_SESSION_STATE_STOPPING) {
            running = 0;
            frame_begun = 0;
            xrEndSession_(session);
        } else if (changed->state == XR_SESSION_STATE_EXITING || changed->state == XR_SESSION_STATE_LOSS_PENDING) {
            running = 0;
            frame_begun = 0;
        }
    }
}

/* Roblox asks for a display rate through the device; the headset's list
 * decides. The current rate is reported back (and used for pacing). */
static void vr_xr_refresh_rate(void) {
    if (!refresh_extension) {
        if (frame_state.predictedDisplayPeriod > 0) display_rate = 1e9f / (float)frame_state.predictedDisplayPeriod;
        return;
    }
    float rate = 0;
    if (xrGetDisplayRefreshRateFB_(session, &rate) == XR_SUCCESS && rate > 0) display_rate = rate;
    uint32_t bits = __atomic_load_n(&refresh_request_bits, __ATOMIC_RELAXED);
    float requested;
    __builtin_memcpy(&requested, &bits, sizeof requested);
    if (!(requested > 0) || requested == refresh_requested_applied) return;
    refresh_requested_applied = requested;
    float best = 0;
    for (uint32_t index = 0; index < refresh_rate_count; ++index)
        if (refresh_rates[index] <= requested + 0.5f && refresh_rates[index] > best) best = refresh_rates[index];
    char line[160];
    if (!follow_requested_rate || best <= 0 || best == display_rate) {
        snprintf(line, sizeof line, "[Cider VR] Roblox asked for %.0f Hz; keeping the headset's %.0f Hz\n",
                 (double)requested, (double)display_rate);
    } else {
        XrResult result = xrRequestDisplayRefreshRateFB_(session, best);
        snprintf(line, sizeof line, "[Cider VR] Roblox asked for %.0f Hz; requesting %.0f Hz (%s)\n",
                 (double)requested, (double)best, result == XR_SUCCESS ? "ok" : "refused");
    }
    vr_host->log(line);
}

int vr_xr_begin_frame(void) {
    if (!session) return 0;
    vr_xr_poll();
    if (!running) return 0;
    XrFrameWaitInfo wait = {XR_TYPE_FRAME_WAIT_INFO, 0};
    frame_state = (XrFrameState){XR_TYPE_FRAME_STATE, 0, 0, 0, 0};
    XrResult result = xrWaitFrame_(session, &wait, &frame_state);
    if (result != XR_SUCCESS && result != XR_SESSION_LOSS_PENDING) {
        vr_xr_log("wait frame", result);
        return 0;
    }
    XrFrameBeginInfo begin = {XR_TYPE_FRAME_BEGIN_INFO, 0};
    result = xrBeginFrame_(session, &begin);
    if (result < 0) {
        vr_xr_log("begin frame", result);
        return 0;
    }
    frame_begun = 1;
    views_located = 0;
    vr_xr_refresh_rate();
    return 1;
}

static void vr_xr_copy_pose(VrXrPose *out, const XrPosef *pose) {
    out->position[0] = pose->position.x;
    out->position[1] = pose->position.y;
    out->position[2] = pose->position.z;
    out->orientation[0] = pose->orientation.x;
    out->orientation[1] = pose->orientation.y;
    out->orientation[2] = pose->orientation.z;
    out->orientation[3] = pose->orientation.w;
}

/* Roblox's HapticService holds a motor at an amplitude until set to 0;
 * OpenXR vibrations have a duration, so active ones are renewed. */
static void vr_xr_haptics(XrTime time) {
    for (int hand = 0; hand < 2; ++hand) {
        uint32_t bits = __atomic_load_n(&haptic_bits[hand], __ATOMIC_RELAXED);
        float amplitude;
        __builtin_memcpy(&amplitude, &bits, sizeof amplitude);
        XrHapticActionInfo info = {XR_TYPE_HAPTIC_ACTION_INFO, 0, haptic_actions[hand], 0};
        if (amplitude <= 0) {
            if (haptic_applied[hand] > 0) xrStopHapticFeedback_(session, &info);
            haptic_applied[hand] = 0;
            continue;
        }
        if (amplitude == haptic_applied[hand] && time < haptic_refresh[hand]) continue;
        XrHapticVibration vibration = {XR_TYPE_HAPTIC_VIBRATION, 0, 200000000, XR_FREQUENCY_UNSPECIFIED,
                                       amplitude > 1 ? 1 : amplitude};
        if (xrApplyHapticFeedback_(session, &info, &vibration) == XR_SUCCESS) {
            haptic_applied[hand] = amplitude;
            haptic_refresh[hand] = time + 100000000;
        }
    }
}

/* Re-anchor the base space at the head's current position and heading, like
 * the Quest build's recenter: positions become relative to the head, yaw 0. */
static void vr_xr_recenter_now(XrTime time) {
    XrSpaceLocation head = {.type = XR_TYPE_SPACE_LOCATION};
    if (xrLocateSpace_(view_space, local_space, time, &head) != XR_SUCCESS ||
        (head.locationFlags & (XR_SPACE_LOCATION_ORIENTATION_VALID_BIT | XR_SPACE_LOCATION_POSITION_VALID_BIT)) !=
            (XR_SPACE_LOCATION_ORIENTATION_VALID_BIT | XR_SPACE_LOCATION_POSITION_VALID_BIT))
        return;
    float y = head.pose.orientation.y, w = head.pose.orientation.w;
    float length = y * y + w * w;
    if (length < 1e-6f) return;
    length = sqrtf(length);
    XrReferenceSpaceCreateInfo create = {XR_TYPE_REFERENCE_SPACE_CREATE_INFO, 0, XR_REFERENCE_SPACE_TYPE_LOCAL,
                                         {{0, y / length, 0, w / length}, head.pose.position}};
    XrSpace recentered = 0;
    XrResult result = xrCreateReferenceSpace_(session, &create, &recentered);
    if (result != XR_SUCCESS) {
        vr_xr_log("recenter", result);
        return;
    }
    /* The previous base stays alive: a submitted frame may still refer to it. */
    static XrSpace retired;
    if (retired && retired != local_space && retired != submitted_space) xrDestroySpace_(retired);
    retired = base_space;
    base_space = recentered;
    vr_host->log("[Cider VR] Recentered on the headset's current position and heading\n");
}

static void vr_xr_input(VrXrViews *views, XrTime time) {
    views->controllers = 0;
    views->changed = 0;
    for (int hand = 0; hand < 2; ++hand)
        views->hand_position_valid[hand] = views->hand_orientation_valid[hand] = 0;
    if (!action_set) return;
    XrActiveActionSet active = {action_set, 0};
    XrActionsSyncInfo sync = {XR_TYPE_ACTIONS_SYNC_INFO, 0, 1, &active};
    if (xrSyncActions_(session, &sync) != XR_SUCCESS) return; /* not focused */
    views->controllers = 1;
    vr_xr_haptics(time);
    for (int index = 0; index < VR_XR_INPUT_ACTIONS; ++index) {
        const VrXrInputAction *input = &input_actions[index];
        XrActionStateGetInfo get = {XR_TYPE_ACTION_STATE_GET_INFO, 0, actions[index], 0};
        float value;
        if (input->type == XR_ACTION_TYPE_BOOLEAN_INPUT) {
            XrActionStateBoolean state = {.type = XR_TYPE_ACTION_STATE_BOOLEAN};
            if (xrGetActionStateBoolean_(session, &get, &state) != XR_SUCCESS || !state.isActive ||
                !state.changedSinceLastSync)
                continue;
            value = state.currentState ? 1.0f : 0.0f;
        } else {
            XrActionStateFloat state = {.type = XR_TYPE_ACTION_STATE_FLOAT};
            if (xrGetActionStateFloat_(session, &get, &state) != XR_SUCCESS || !state.isActive ||
                !state.changedSinceLastSync)
                continue;
            value = state.currentState;
            /* Triggers and grips snap to their ends, as on Quest. */
            if (input->slot == 3 || input->slot == 4 || input->slot == 12 || input->slot == 13)
                value = value > 0.99f ? 1.0f : value < 0.01f ? 0.0f : value;
        }
        views->input[input->slot] = value;
        views->changed |= 1u << input->slot;
    }
    for (int hand = 0; hand < 2; ++hand) {
        XrSpaceLocation grip = {.type = XR_TYPE_SPACE_LOCATION}, aim = {.type = XR_TYPE_SPACE_LOCATION};
        if (hand_spaces[hand * 2] && xrLocateSpace_(hand_spaces[hand * 2], base_space, time, &grip) == XR_SUCCESS &&
            (grip.locationFlags & XR_SPACE_LOCATION_POSITION_VALID_BIT)) {
            vr_xr_copy_pose(&views->hand[hand], &grip.pose);
            views->hand_position_valid[hand] = 1;
        }
        if (hand_spaces[hand * 2 + 1] &&
            xrLocateSpace_(hand_spaces[hand * 2 + 1], base_space, time, &aim) == XR_SUCCESS &&
            (aim.locationFlags & XR_SPACE_LOCATION_ORIENTATION_VALID_BIT)) {
            views->hand[hand].orientation[0] = aim.pose.orientation.x;
            views->hand[hand].orientation[1] = aim.pose.orientation.y;
            views->hand[hand].orientation[2] = aim.pose.orientation.z;
            views->hand[hand].orientation[3] = aim.pose.orientation.w;
            views->hand_orientation_valid[hand] = 1;
        }
    }
}

int vr_xr_locate(VrXrViews *views) {
    if (!frame_begun) return 0;
    XrTime time = frame_state.predictedDisplayTime + (submit_lag ? frame_state.predictedDisplayPeriod : 0);
    if (__atomic_exchange_n(&recenter_requested, 0, __ATOMIC_ACQUIRE)) vr_xr_recenter_now(time);
    XrViewLocateInfo info = {XR_TYPE_VIEW_LOCATE_INFO, 0, XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO, time, base_space};
    XrViewState state = {XR_TYPE_VIEW_STATE, 0, 0};
    uint32_t count = 0;
    located[0] = located[1] = (XrView){.type = XR_TYPE_VIEW};
    views->head_valid = views->floor_valid = views->eyes_valid = 0;
    if (xrLocateViews_(session, &info, &state, 2, &count, located) != XR_SUCCESS || count != 2 ||
        (state.viewStateFlags & (XR_VIEW_STATE_ORIENTATION_VALID_BIT | XR_VIEW_STATE_POSITION_VALID_BIT)) !=
            (XR_VIEW_STATE_ORIENTATION_VALID_BIT | XR_VIEW_STATE_POSITION_VALID_BIT))
        return 0;
    views_located = 1;
    located_space = base_space;
    XrSpaceLocation head = {.type = XR_TYPE_SPACE_LOCATION};
    if (xrLocateSpace_(view_space, base_space, time, &head) == XR_SUCCESS &&
        (head.locationFlags & XR_SPACE_LOCATION_ORIENTATION_VALID_BIT)) {
        vr_xr_copy_pose(&views->head, &head.pose);
        views->head_valid = 1;
    }
    if (stage_space) {
        XrSpaceLocation floor = {.type = XR_TYPE_SPACE_LOCATION};
        if (xrLocateSpace_(stage_space, base_space, time, &floor) == XR_SUCCESS &&
            (floor.locationFlags & XR_SPACE_LOCATION_POSITION_VALID_BIT)) {
            vr_xr_copy_pose(&views->floor, &floor.pose);
            views->floor_valid = 1;
        }
    }
    XrView eyes[2] = {{.type = XR_TYPE_VIEW}, {.type = XR_TYPE_VIEW}};
    info.space = view_space;
    if (xrLocateViews_(session, &info, &state, 2, &count, eyes) == XR_SUCCESS && count == 2) {
        for (int eye = 0; eye < 2; ++eye) {
            views->eye_offset[eye][0] = eyes[eye].pose.position.x;
            views->eye_offset[eye][1] = eyes[eye].pose.position.y;
            views->eye_offset[eye][2] = eyes[eye].pose.position.z;
            const XrFovf *fov = &located[eye].fov;
            views->tangent[eye][0] = tanf(fov->angleUp);
            views->tangent[eye][1] = -tanf(fov->angleDown);
            views->tangent[eye][2] = -tanf(fov->angleLeft);
            views->tangent[eye][3] = tanf(fov->angleRight);
        }
        views->eyes_valid = 1;
    }
    vr_xr_input(views, time);
    return views->head_valid;
}

static void vr_xr_copy(const unsigned int framebuffer[2], int width, int height) {
    int read = 0, draw = 0;
    unsigned char mask[4] = {1, 1, 1, 1};
    glGetIntegerv_(GL_READ_FRAMEBUFFER_BINDING, &read);
    glGetIntegerv_(GL_DRAW_FRAMEBUFFER_BINDING, &draw);
    glGetBooleanv_(GL_COLOR_WRITEMASK, mask);
    unsigned char scissor = glIsEnabled_(GL_SCISSOR_TEST), srgb = glIsEnabled_(GL_FRAMEBUFFER_SRGB);
    if (scissor) glDisable_(GL_SCISSOR_TEST);
    if (srgb) glDisable_(GL_FRAMEBUFFER_SRGB);
    glColorMask_(1, 1, 1, 1);
    for (int eye = 0; eye < 2; ++eye) {
        uint32_t index = 0;
        XrSwapchainImageAcquireInfo acquire = {XR_TYPE_SWAPCHAIN_IMAGE_ACQUIRE_INFO, 0};
        XrSwapchainImageWaitInfo wait = {XR_TYPE_SWAPCHAIN_IMAGE_WAIT_INFO, 0, XR_INFINITE_DURATION};
        XrSwapchainImageReleaseInfo release = {XR_TYPE_SWAPCHAIN_IMAGE_RELEASE_INFO, 0};
        if (xrAcquireSwapchainImage_(swapchains[eye], &acquire, &index) != XR_SUCCESS) continue;
        if (xrWaitSwapchainImage_(swapchains[eye], &wait) == XR_SUCCESS && index < image_counts[eye]) {
            glBindFramebuffer_(GL_DRAW_FRAMEBUFFER, copy_framebuffer);
            glFramebufferTexture2D_(GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D,
                                    images[eye][index].image, 0);
            glBindFramebuffer_(GL_READ_FRAMEBUFFER, framebuffer[eye]);
            glBlitFramebuffer_(0, 0, width, height, 0, 0, eye_width, eye_height,
                               0x4000 /* GL_COLOR_BUFFER_BIT */, 0x2601 /* GL_LINEAR */);
            glFramebufferTexture2D_(GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, 0, 0);
        }
        xrReleaseSwapchainImage_(swapchains[eye], &release);
    }
    glBindFramebuffer_(GL_READ_FRAMEBUFFER, (unsigned int)read);
    glBindFramebuffer_(GL_DRAW_FRAMEBUFFER, (unsigned int)draw);
    glColorMask_(mask[0], mask[1], mask[2], mask[3]);
    if (srgb) glEnable_(GL_FRAMEBUFFER_SRGB);
    if (scissor) glEnable_(GL_SCISSOR_TEST);
}

void vr_xr_end_frame(const unsigned int framebuffer[2], int width, int height) {
    if (!frame_begun) return;
    frame_begun = 0;
    XrCompositionLayerProjectionView views[2];
    XrCompositionLayerProjection projection = {XR_TYPE_COMPOSITION_LAYER_PROJECTION, 0, 0, base_space, 2, views};
    const XrCompositionLayerBaseHeader *layers[] = {(const XrCompositionLayerBaseHeader *)&projection};
    int submit = frame_state.shouldRender && views_located && framebuffer[0] && framebuffer[1];
    if (submit) {
        vr_xr_copy(framebuffer, width, height);
        /* Roblox draws with the head pose its game step took from VRService
         * during the previous frame, so a frame's image matches the views
         * located (one display period ahead) when the previous frame opened. */
        const XrView *pose = submit_lag && have_submitted ? submitted : located;
        projection.space = submit_lag && have_submitted ? submitted_space : located_space;
        for (int eye = 0; eye < 2; ++eye)
            views[eye] = (XrCompositionLayerProjectionView){
                XR_TYPE_COMPOSITION_LAYER_PROJECTION_VIEW, 0, pose[eye].pose, pose[eye].fov,
                {swapchains[eye], {{0, 0}, {eye_width, eye_height}}, 0}};
    }
    if (submit) {
        submitted[0] = located[0];
        submitted[1] = located[1];
        submitted_space = located_space;
        have_submitted = 1;
    }
    XrFrameEndInfo end = {XR_TYPE_FRAME_END_INFO, 0, frame_state.predictedDisplayTime,
                          XR_ENVIRONMENT_BLEND_MODE_OPAQUE, submit ? 1u : 0u, submit ? layers : 0};
    XrResult result = xrEndFrame_(session, &end);
    if (result < 0) {
        static int warned;
        if (warned++ < 8) vr_xr_log("end frame", result);
    }
}
