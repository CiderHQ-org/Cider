/* vr_openxr.h must match the Khronos OpenXR headers it was copied from. */
#include <stdio.h>
#include "../vr_openxr.h"
#include "vr_openxr_fields.h"

extern const unsigned long khronos_sizes[], khronos_offsets[];
extern const long khronos_constants[];
static const unsigned long sizes[] = {VR_OPENXR_STRUCTS(VR_OPENXR_SIZE)};
static const unsigned long offsets[] = {VR_OPENXR_FIELDS(VR_OPENXR_OFFSET)};
static const char *const size_names[] = {VR_OPENXR_STRUCTS(VR_OPENXR_NAME)};
static const char *const offset_names[] = {VR_OPENXR_FIELDS(VR_OPENXR_FIELD_NAME)};
static const long constants[] = {
    XR_TYPE_GRAPHICS_BINDING_EGL_MNDX, XR_TYPE_SWAPCHAIN_IMAGE_OPENGL_KHR, XR_TYPE_GRAPHICS_REQUIREMENTS_OPENGL_KHR,
    XR_TYPE_EVENT_DATA_SESSION_STATE_CHANGED, XR_TYPE_COMPOSITION_LAYER_PROJECTION_VIEW, XR_TYPE_VIEW_CONFIGURATION_VIEW,
    XR_REFERENCE_SPACE_TYPE_STAGE, XR_SESSION_STATE_EXITING, XR_ERROR_FORM_FACTOR_UNAVAILABLE,
    (long)XR_SWAPCHAIN_USAGE_TRANSFER_DST_BIT, XR_TYPE_EXTENSION_PROPERTIES, XR_TYPE_SPACE_LOCATION,
    XR_TYPE_ACTION_SET_CREATE_INFO, XR_TYPE_ACTION_CREATE_INFO, XR_TYPE_INTERACTION_PROFILE_SUGGESTED_BINDING,
    XR_TYPE_SESSION_ACTION_SETS_ATTACH_INFO, XR_TYPE_ACTIONS_SYNC_INFO, XR_TYPE_ACTION_STATE_GET_INFO,
    XR_TYPE_ACTION_STATE_BOOLEAN, XR_TYPE_ACTION_STATE_FLOAT, XR_TYPE_ACTION_SPACE_CREATE_INFO,
    XR_ACTION_TYPE_BOOLEAN_INPUT, XR_ACTION_TYPE_FLOAT_INPUT, XR_ACTION_TYPE_POSE_INPUT, XR_SESSION_NOT_FOCUSED,
    XR_TYPE_HAPTIC_VIBRATION, XR_TYPE_HAPTIC_ACTION_INFO, XR_ACTION_TYPE_VIBRATION_OUTPUT, XR_FREQUENCY_UNSPECIFIED,
};

int main(void) {
    int failures = 0;
    for (unsigned index = 0; index < sizeof sizes / sizeof *sizes; ++index)
        if (sizes[index] != khronos_sizes[index]) {
            printf("size of %s: %lu, Khronos %lu\n", size_names[index], sizes[index], khronos_sizes[index]);
            ++failures;
        }
    for (unsigned index = 0; index < sizeof offsets / sizeof *offsets; ++index)
        if (offsets[index] != khronos_offsets[index]) {
            printf("offset of %s: %lu, Khronos %lu\n", offset_names[index], offsets[index], khronos_offsets[index]);
            ++failures;
        }
    for (unsigned index = 0; index < sizeof constants / sizeof *constants; ++index)
        if (constants[index] != khronos_constants[index]) {
            printf("constant %u: %ld, Khronos %ld\n", index, constants[index], khronos_constants[index]);
            ++failures;
        }
    if (failures) return 1;
    printf("vr_openxr.h matches the Khronos OpenXR headers\n");
    return 0;
}
