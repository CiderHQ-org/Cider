/* Every vendored OpenXR struct and the fields vr_xr.c touches. */
#define VR_OPENXR_STRUCTS(S) \
    S(XrPosef) S(XrFovf) S(XrRect2Di) S(XrApplicationInfo) S(XrInstanceCreateInfo) S(XrExtensionProperties) \
    S(XrSystemGetInfo) S(XrGraphicsRequirementsOpenGLKHR) S(XrGraphicsBindingEGLMNDX) S(XrSessionCreateInfo) \
    S(XrSessionBeginInfo) S(XrReferenceSpaceCreateInfo) S(XrViewConfigurationView) S(XrSwapchainCreateInfo) \
    S(XrSwapchainImageOpenGLKHR) S(XrSwapchainImageWaitInfo) S(XrFrameState) S(XrFrameEndInfo) \
    S(XrCompositionLayerBaseHeader) S(XrViewLocateInfo) S(XrViewState) S(XrView) S(XrSpaceLocation) \
    S(XrSwapchainSubImage) S(XrCompositionLayerProjectionView) S(XrCompositionLayerProjection) \
    S(XrEventDataBuffer) S(XrEventDataSessionStateChanged) \
    S(XrActionSetCreateInfo) S(XrActionCreateInfo) S(XrActionSuggestedBinding) S(XrInteractionProfileSuggestedBinding) \
    S(XrSessionActionSetsAttachInfo) S(XrActiveActionSet) S(XrActionsSyncInfo) S(XrActionStateGetInfo) \
    S(XrActionStateBoolean) S(XrActionStateFloat) S(XrActionSpaceCreateInfo) S(XrHapticActionInfo) S(XrHapticVibration)
#define VR_OPENXR_FIELDS(F) \
    F(XrPosef, position) F(XrApplicationInfo, engineName) F(XrApplicationInfo, apiVersion) \
    F(XrInstanceCreateInfo, applicationInfo) F(XrInstanceCreateInfo, enabledApiLayerCount) \
    F(XrInstanceCreateInfo, enabledExtensionNames) F(XrExtensionProperties, extensionVersion) \
    F(XrSystemGetInfo, formFactor) F(XrGraphicsRequirementsOpenGLKHR, maxApiVersionSupported) \
    F(XrGraphicsBindingEGLMNDX, getProcAddress) F(XrGraphicsBindingEGLMNDX, context) \
    F(XrSessionCreateInfo, systemId) F(XrSessionBeginInfo, primaryViewConfigurationType) \
    F(XrReferenceSpaceCreateInfo, poseInReferenceSpace) F(XrViewConfigurationView, recommendedImageRectHeight) \
    F(XrSwapchainCreateInfo, format) F(XrSwapchainCreateInfo, mipCount) F(XrSwapchainImageOpenGLKHR, image) \
    F(XrSwapchainImageWaitInfo, timeout) F(XrFrameState, predictedDisplayPeriod) F(XrFrameState, shouldRender) \
    F(XrFrameEndInfo, environmentBlendMode) F(XrFrameEndInfo, layers) F(XrCompositionLayerBaseHeader, space) \
    F(XrViewLocateInfo, displayTime) F(XrViewLocateInfo, space) F(XrViewState, viewStateFlags) F(XrView, fov) \
    F(XrSpaceLocation, pose) F(XrSwapchainSubImage, imageRect) F(XrSwapchainSubImage, imageArrayIndex) \
    F(XrCompositionLayerProjectionView, subImage) F(XrCompositionLayerProjection, viewCount) \
    F(XrCompositionLayerProjection, views) F(XrEventDataBuffer, varying) F(XrEventDataSessionStateChanged, state) \
    F(XrEventDataSessionStateChanged, time) F(XrActionSetCreateInfo, localizedActionSetName) \
    F(XrActionSetCreateInfo, priority) F(XrActionCreateInfo, actionType) F(XrActionCreateInfo, subactionPaths) \
    F(XrActionCreateInfo, localizedActionName) F(XrInteractionProfileSuggestedBinding, suggestedBindings) \
    F(XrSessionActionSetsAttachInfo, actionSets) F(XrActionsSyncInfo, activeActionSets) \
    F(XrActionStateGetInfo, subactionPath) F(XrActionStateBoolean, lastChangeTime) F(XrActionStateBoolean, isActive) \
    F(XrActionStateFloat, changedSinceLastSync) F(XrActionStateFloat, isActive) F(XrActionSpaceCreateInfo, poseInActionSpace) \
    F(XrHapticActionInfo, subactionPath) F(XrHapticVibration, frequency) F(XrHapticVibration, amplitude)
#define VR_OPENXR_SIZE(type) sizeof(type),
#define VR_OPENXR_OFFSET(type, field) __builtin_offsetof(type, field),
#define VR_OPENXR_NAME(type) #type,
#define VR_OPENXR_FIELD_NAME(type, field) #type "." #field,
