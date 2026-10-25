/* The part of the OpenXR 1.0 ABI that vr_xr.c uses, for building the shim
 * where no OpenXR headers are installed. Names and layouts follow the
 * Khronos openxr.h (Apache-2.0); tests/vr_openxr_abi_test.c checks every
 * struct against the real header. */
#ifndef QUADRA_VR_OPENXR_H
#define QUADRA_VR_OPENXR_H
#include <stdint.h>

typedef int32_t XrResult;
typedef int32_t XrStructureType;
typedef uint64_t XrVersion;
typedef uint64_t XrFlags64;
typedef uint64_t XrSystemId;
typedef int64_t XrTime;
typedef int64_t XrDuration;
typedef uint32_t XrBool32;
typedef struct XrInstance_T *XrInstance;
typedef struct XrSession_T *XrSession;
typedef struct XrSpace_T *XrSpace;
typedef struct XrSwapchain_T *XrSwapchain;
typedef struct XrActionSet_T *XrActionSet;
typedef struct XrAction_T *XrAction;
typedef uint64_t XrPath;
typedef void (*PFN_xrVoidFunction)(void);

#define XR_MAKE_VERSION(major, minor, patch) \
    ((((uint64_t)(major) & 0xffffULL) << 48) | (((uint64_t)(minor) & 0xffffULL) << 32) | ((uint64_t)(patch) & 0xffffffffULL))
#define XR_INFINITE_DURATION 0x7fffffffffffffffLL
#define XR_FREQUENCY_UNSPECIFIED 0

enum {
    XR_SUCCESS = 0,
    XR_EVENT_UNAVAILABLE = 4,
    XR_SESSION_LOSS_PENDING = 3,
    XR_SESSION_NOT_FOCUSED = 8,
    XR_ERROR_FORM_FACTOR_UNAVAILABLE = -35,
};

enum {
    XR_TYPE_INSTANCE_CREATE_INFO = 3,
    XR_TYPE_SYSTEM_GET_INFO = 4,
    XR_TYPE_VIEW_LOCATE_INFO = 6,
    XR_TYPE_VIEW = 7,
    XR_TYPE_SESSION_CREATE_INFO = 8,
    XR_TYPE_SWAPCHAIN_CREATE_INFO = 9,
    XR_TYPE_SESSION_BEGIN_INFO = 10,
    XR_TYPE_VIEW_STATE = 11,
    XR_TYPE_FRAME_END_INFO = 12,
    XR_TYPE_HAPTIC_VIBRATION = 13,
    XR_TYPE_EVENT_DATA_BUFFER = 16,
    XR_TYPE_EVENT_DATA_INSTANCE_LOSS_PENDING = 17,
    XR_TYPE_EVENT_DATA_SESSION_STATE_CHANGED = 18,
    XR_TYPE_ACTION_STATE_BOOLEAN = 23,
    XR_TYPE_ACTION_STATE_FLOAT = 24,
    XR_TYPE_ACTION_SET_CREATE_INFO = 28,
    XR_TYPE_ACTION_CREATE_INFO = 29,
    XR_TYPE_EXTENSION_PROPERTIES = 2,
    XR_TYPE_FRAME_WAIT_INFO = 33,
    XR_TYPE_COMPOSITION_LAYER_PROJECTION = 35,
    XR_TYPE_REFERENCE_SPACE_CREATE_INFO = 37,
    XR_TYPE_ACTION_SPACE_CREATE_INFO = 38,
    XR_TYPE_VIEW_CONFIGURATION_VIEW = 41,
    XR_TYPE_SPACE_LOCATION = 42,
    XR_TYPE_FRAME_STATE = 44,
    XR_TYPE_FRAME_BEGIN_INFO = 46,
    XR_TYPE_COMPOSITION_LAYER_PROJECTION_VIEW = 48,
    XR_TYPE_INTERACTION_PROFILE_SUGGESTED_BINDING = 51,
    XR_TYPE_SWAPCHAIN_IMAGE_ACQUIRE_INFO = 55,
    XR_TYPE_SWAPCHAIN_IMAGE_WAIT_INFO = 56,
    XR_TYPE_SWAPCHAIN_IMAGE_RELEASE_INFO = 57,
    XR_TYPE_ACTION_STATE_GET_INFO = 58,
    XR_TYPE_HAPTIC_ACTION_INFO = 59,
    XR_TYPE_SESSION_ACTION_SETS_ATTACH_INFO = 60,
    XR_TYPE_ACTIONS_SYNC_INFO = 61,
    XR_TYPE_SWAPCHAIN_IMAGE_OPENGL_KHR = 1000023004,
    XR_TYPE_GRAPHICS_REQUIREMENTS_OPENGL_KHR = 1000023005,
    XR_TYPE_GRAPHICS_BINDING_EGL_MNDX = 1000048004,
};

enum {
    XR_FORM_FACTOR_HEAD_MOUNTED_DISPLAY = 1,
    XR_VIEW_CONFIGURATION_TYPE_PRIMARY_STEREO = 2,
    XR_ENVIRONMENT_BLEND_MODE_OPAQUE = 1,
    XR_REFERENCE_SPACE_TYPE_VIEW = 1,
    XR_REFERENCE_SPACE_TYPE_LOCAL = 2,
    XR_REFERENCE_SPACE_TYPE_STAGE = 3,
    XR_SESSION_STATE_IDLE = 1,
    XR_SESSION_STATE_READY = 2,
    XR_SESSION_STATE_SYNCHRONIZED = 3,
    XR_SESSION_STATE_VISIBLE = 4,
    XR_SESSION_STATE_FOCUSED = 5,
    XR_SESSION_STATE_STOPPING = 6,
    XR_SESSION_STATE_LOSS_PENDING = 7,
    XR_SESSION_STATE_EXITING = 8,
    XR_ACTION_TYPE_BOOLEAN_INPUT = 1,
    XR_ACTION_TYPE_FLOAT_INPUT = 2,
    XR_ACTION_TYPE_POSE_INPUT = 4,
    XR_ACTION_TYPE_VIBRATION_OUTPUT = 100,
};

#define XR_SWAPCHAIN_USAGE_COLOR_ATTACHMENT_BIT 0x00000001ULL
#define XR_SWAPCHAIN_USAGE_TRANSFER_DST_BIT 0x00000010ULL
#define XR_SWAPCHAIN_USAGE_SAMPLED_BIT 0x00000020ULL
#define XR_SPACE_LOCATION_ORIENTATION_VALID_BIT 0x00000001ULL
#define XR_SPACE_LOCATION_POSITION_VALID_BIT 0x00000002ULL
#define XR_VIEW_STATE_ORIENTATION_VALID_BIT 0x00000001ULL
#define XR_VIEW_STATE_POSITION_VALID_BIT 0x00000002ULL

typedef struct XrQuaternionf { float x, y, z, w; } XrQuaternionf;
typedef struct XrVector3f { float x, y, z; } XrVector3f;
typedef struct XrPosef { XrQuaternionf orientation; XrVector3f position; } XrPosef;
typedef struct XrFovf { float angleLeft, angleRight, angleUp, angleDown; } XrFovf;
typedef struct XrOffset2Di { int32_t x, y; } XrOffset2Di;
typedef struct XrExtent2Di { int32_t width, height; } XrExtent2Di;
typedef struct XrRect2Di { XrOffset2Di offset; XrExtent2Di extent; } XrRect2Di;

typedef struct XrApplicationInfo {
    char applicationName[128];
    uint32_t applicationVersion;
    char engineName[128];
    uint32_t engineVersion;
    XrVersion apiVersion;
} XrApplicationInfo;

typedef struct XrInstanceCreateInfo {
    XrStructureType type;
    const void *next;
    XrFlags64 createFlags;
    XrApplicationInfo applicationInfo;
    uint32_t enabledApiLayerCount;
    const char *const *enabledApiLayerNames;
    uint32_t enabledExtensionCount;
    const char *const *enabledExtensionNames;
} XrInstanceCreateInfo;

typedef struct XrExtensionProperties {
    XrStructureType type;
    void *next;
    char extensionName[128];
    uint32_t extensionVersion;
} XrExtensionProperties;

typedef struct XrSystemGetInfo {
    XrStructureType type;
    const void *next;
    int32_t formFactor;
} XrSystemGetInfo;

typedef struct XrGraphicsRequirementsOpenGLKHR {
    XrStructureType type;
    void *next;
    XrVersion minApiVersionSupported;
    XrVersion maxApiVersionSupported;
} XrGraphicsRequirementsOpenGLKHR;

typedef void (*(*PFN_xrEglGetProcAddressMNDX)(const char *))(void);
typedef struct XrGraphicsBindingEGLMNDX {
    XrStructureType type;
    const void *next;
    PFN_xrEglGetProcAddressMNDX getProcAddress;
    void *display;
    void *config;
    void *context;
} XrGraphicsBindingEGLMNDX;

typedef struct XrSessionCreateInfo {
    XrStructureType type;
    const void *next;
    XrFlags64 createFlags;
    XrSystemId systemId;
} XrSessionCreateInfo;

typedef struct XrSessionBeginInfo {
    XrStructureType type;
    const void *next;
    int32_t primaryViewConfigurationType;
} XrSessionBeginInfo;

typedef struct XrReferenceSpaceCreateInfo {
    XrStructureType type;
    const void *next;
    int32_t referenceSpaceType;
    XrPosef poseInReferenceSpace;
} XrReferenceSpaceCreateInfo;

typedef struct XrViewConfigurationView {
    XrStructureType type;
    void *next;
    uint32_t recommendedImageRectWidth;
    uint32_t maxImageRectWidth;
    uint32_t recommendedImageRectHeight;
    uint32_t maxImageRectHeight;
    uint32_t recommendedSwapchainSampleCount;
    uint32_t maxSwapchainSampleCount;
} XrViewConfigurationView;

typedef struct XrSwapchainCreateInfo {
    XrStructureType type;
    const void *next;
    XrFlags64 createFlags;
    XrFlags64 usageFlags;
    int64_t format;
    uint32_t sampleCount;
    uint32_t width;
    uint32_t height;
    uint32_t faceCount;
    uint32_t arraySize;
    uint32_t mipCount;
} XrSwapchainCreateInfo;

typedef struct XrSwapchainImageOpenGLKHR {
    XrStructureType type;
    void *next;
    uint32_t image;
} XrSwapchainImageOpenGLKHR;

typedef struct XrSwapchainImageAcquireInfo { XrStructureType type; const void *next; } XrSwapchainImageAcquireInfo;
typedef struct XrSwapchainImageWaitInfo { XrStructureType type; const void *next; XrDuration timeout; } XrSwapchainImageWaitInfo;
typedef struct XrSwapchainImageReleaseInfo { XrStructureType type; const void *next; } XrSwapchainImageReleaseInfo;
typedef struct XrFrameWaitInfo { XrStructureType type; const void *next; } XrFrameWaitInfo;
typedef struct XrFrameBeginInfo { XrStructureType type; const void *next; } XrFrameBeginInfo;

typedef struct XrFrameState {
    XrStructureType type;
    void *next;
    XrTime predictedDisplayTime;
    XrDuration predictedDisplayPeriod;
    XrBool32 shouldRender;
} XrFrameState;

typedef struct XrCompositionLayerBaseHeader {
    XrStructureType type;
    const void *next;
    XrFlags64 layerFlags;
    XrSpace space;
} XrCompositionLayerBaseHeader;

typedef struct XrFrameEndInfo {
    XrStructureType type;
    const void *next;
    XrTime displayTime;
    int32_t environmentBlendMode;
    uint32_t layerCount;
    const XrCompositionLayerBaseHeader *const *layers;
} XrFrameEndInfo;

typedef struct XrViewLocateInfo {
    XrStructureType type;
    const void *next;
    int32_t viewConfigurationType;
    XrTime displayTime;
    XrSpace space;
} XrViewLocateInfo;

typedef struct XrViewState {
    XrStructureType type;
    void *next;
    XrFlags64 viewStateFlags;
} XrViewState;

typedef struct XrView {
    XrStructureType type;
    void *next;
    XrPosef pose;
    XrFovf fov;
} XrView;

typedef struct XrSpaceLocation {
    XrStructureType type;
    void *next;
    XrFlags64 locationFlags;
    XrPosef pose;
} XrSpaceLocation;

typedef struct XrSwapchainSubImage {
    XrSwapchain swapchain;
    XrRect2Di imageRect;
    uint32_t imageArrayIndex;
} XrSwapchainSubImage;

typedef struct XrCompositionLayerProjectionView {
    XrStructureType type;
    const void *next;
    XrPosef pose;
    XrFovf fov;
    XrSwapchainSubImage subImage;
} XrCompositionLayerProjectionView;

typedef struct XrCompositionLayerProjection {
    XrStructureType type;
    const void *next;
    XrFlags64 layerFlags;
    XrSpace space;
    uint32_t viewCount;
    const XrCompositionLayerProjectionView *views;
} XrCompositionLayerProjection;

typedef struct XrEventDataBuffer {
    XrStructureType type;
    const void *next;
    uint8_t varying[4000];
} XrEventDataBuffer;

typedef struct XrEventDataSessionStateChanged {
    XrStructureType type;
    const void *next;
    XrSession session;
    int32_t state;
    XrTime time;
} XrEventDataSessionStateChanged;

typedef struct XrActionSetCreateInfo {
    XrStructureType type;
    const void *next;
    char actionSetName[64];
    char localizedActionSetName[128];
    uint32_t priority;
} XrActionSetCreateInfo;

typedef struct XrActionCreateInfo {
    XrStructureType type;
    const void *next;
    char actionName[64];
    int32_t actionType;
    uint32_t countSubactionPaths;
    const XrPath *subactionPaths;
    char localizedActionName[128];
} XrActionCreateInfo;

typedef struct XrActionSuggestedBinding {
    XrAction action;
    XrPath binding;
} XrActionSuggestedBinding;

typedef struct XrInteractionProfileSuggestedBinding {
    XrStructureType type;
    const void *next;
    XrPath interactionProfile;
    uint32_t countSuggestedBindings;
    const XrActionSuggestedBinding *suggestedBindings;
} XrInteractionProfileSuggestedBinding;

typedef struct XrSessionActionSetsAttachInfo {
    XrStructureType type;
    const void *next;
    uint32_t countActionSets;
    const XrActionSet *actionSets;
} XrSessionActionSetsAttachInfo;

typedef struct XrActiveActionSet {
    XrActionSet actionSet;
    XrPath subactionPath;
} XrActiveActionSet;

typedef struct XrActionsSyncInfo {
    XrStructureType type;
    const void *next;
    uint32_t countActiveActionSets;
    const XrActiveActionSet *activeActionSets;
} XrActionsSyncInfo;

typedef struct XrActionStateGetInfo {
    XrStructureType type;
    const void *next;
    XrAction action;
    XrPath subactionPath;
} XrActionStateGetInfo;

typedef struct XrActionStateBoolean {
    XrStructureType type;
    void *next;
    XrBool32 currentState;
    XrBool32 changedSinceLastSync;
    XrTime lastChangeTime;
    XrBool32 isActive;
} XrActionStateBoolean;

typedef struct XrActionStateFloat {
    XrStructureType type;
    void *next;
    float currentState;
    XrBool32 changedSinceLastSync;
    XrTime lastChangeTime;
    XrBool32 isActive;
} XrActionStateFloat;

typedef struct XrActionSpaceCreateInfo {
    XrStructureType type;
    const void *next;
    XrAction action;
    XrPath subactionPath;
    XrPosef poseInActionSpace;
} XrActionSpaceCreateInfo;

typedef struct XrHapticActionInfo {
    XrStructureType type;
    const void *next;
    XrAction action;
    XrPath subactionPath;
} XrHapticActionInfo;

typedef struct XrHapticVibration {
    XrStructureType type;
    const void *next;
    XrDuration duration;
    float frequency;
    float amplitude;
} XrHapticVibration;

typedef XrResult (*PFN_xrGetInstanceProcAddr)(XrInstance, const char *, PFN_xrVoidFunction *);

#endif
