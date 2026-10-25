# Studio Vulkan layer

Roblox Studio's Vulkan renderer under Wine sees `VK_ERROR_OUT_OF_DATE_KHR` and
`VK_SUBOPTIMAL_KHR` from the host driver, which it does not handle. This
Vulkan layer turns a suboptimal swapchain into success and an out-of-date one into
`VK_ERROR_SURFACE_LOST_KHR`, which Studio does answer by creating the swapchain again.
It only matters for **Settings -> Studio -> Renderer -> Vulkan**.

`build_debug_shim.sh` builds it as `libquadra-studio-layer.so` when the Vulkan
headers are installed (it is optional: without it the renderer still starts, it
just keeps the problem). `studio.py` writes the layer manifest and enables it
through the loader's `VK_LAYER_PATH` and `VK_INSTANCE_LAYERS` when Studio starts.

## Origin and licences

- `quadra_studio_layer.cpp` is Vinegar's `layer/vinegar_layer.cpp`
  (https://github.com/vinegarhq/vinegar, GPL-3.0; written by tunis, workaround by
  V3L0C1T13S) with the names changed. It is based on Baldur Karlsson's
  `sample_layer`, whose BSD 2-Clause licence is kept in the file header.
- `vk_layer.h` is the Khronos/Valve/LunarG layer interface header (Apache-2.0),
  unchanged.
