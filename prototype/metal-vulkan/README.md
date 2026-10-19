# Metal on Vulkan (experimental)

A third renderer next to OpenGL and Vulkan (Zink): Roblox's own **Metal** renderer, with every
Metal call run on the host's Vulkan driver. Source builds expose it in
**Settings → Environment → Game → Renderer → Metal on Vulkan (experimental)**.
OpenGL remains the default. Current binary packages do not ship the bridge.

## Why Metal, not "real" Vulkan

RobloxPlayer 0.743.0.7431134 has no Vulkan backend to switch on. Its device factory
(`0x102d75b5c`) makes `DeviceGL` for API 0 and `DeviceMtl` for API 3 and throws
`Unsupported API: %d` for anything else (Vulkan is 4: the "Mode 6 failed: Unsupported API: 4"
seen before). There are no `DeviceVK`/`ContextVK` classes, no `vk*` imports, and no Vulkan
shader pack (only `shaders_glsl3.pack` and `shaders_metal_osx.pack`).

## How it works

```text
RobloxPlayer (guest, Mach-O)            host (ELF)
  Metal calls ──> framework/  ─ C table ─> host/  (Rust) ──> metal2vulkan-runtime ──> Vulkan
                  Metal.framework replacement   libquadra_metal_host.so
                  CAMetalLayer subclass              swapchain on an X11 child window
                                                     or a Wayland subsurface
```

- `quadra_metal.h`: the ABI. The guest loads the host library through Darling's `_elfcalls`
  and gets one function table. Handles are the host's. The host never calls guest code:
  completion and presented blocks run on guest threads.
- `framework/`: `Metal.framework`, loaded in place of Darling's with `DYLD_FRAMEWORK_PATH`.
  Exports the classes and functions RobloxPlayer binds (`MTLRenderPassDescriptor`,
  `MTLRenderPipelineDescriptor`, `MTLTextureDescriptor`, `MTLSamplerDescriptor`,
  `MTLDepthStencilDescriptor`, `MTLVertexDescriptor`, `MTLCompileOptions`, `MTLCaptureManager`,
  `MTLCreateSystemDefaultDevice`, `MTLCopyAllDevices`). Unknown selectors are logged once
  (`[Quadra Metal] missing -[...]`) and answered with zeros. `CAMetalLayer` is taken over at run
  time by a subclass, without linking QuartzCore, which links Metal. Roblox's
  `Resources/builtins.shaders` (Metal source, which cannot be compiled on Linux) are emulated:
  its three upload kernels run as buffer-to-texture blits.
- `host/`: [steelbrain/metal2vulkan](https://github.com/steelbrain/metal2vulkan) 0.2's runtime
  (GPL-2.0-or-later OR LGPL-3.0-or-later; pinned to `720ef1c`) behind the C table, plus
  presentation (`src/present.rs`) and the AIR upgrade (`src/air.rs`).
- Shaders: Roblox's metallibs are format 2.2 with LLVM bitcode of module version 1 and Metal
  2.2-era AIR call forms, all of which metal2vulkan 0.2 refuses. `src/air.rs` upgrades each
  library once:
  - the host's libLLVM (Mesa's dependency) reads the old bitcode through its C API and prints
    it as IR text;
  - the calls get their current forms: texture samples, gathers, reads and writes gain the
    access operand (taken from the entry's argument metadata), samples gain `min_lod_clamp`,
    and these return `{texel, i8}`; atomics gain their `volatile` flag; `air.render_target`
    gains its index;
  - the text is reassembled as current bitcode.

  `normalize_metallib` then inserts the empty extended header that format 2.7 has. Results are
  cached by SHA-256 in `$MACOBLOX_METAL_SHADER_CACHE/air-upgrade-v1`.

## Status

- Roblox accepts the device: `[FLog::Graphics] Metal renderer: NVIDIA GeForce RTX 3060 Ti`.
- All 2,266 shader libraries of the pack decode through metal2vulkan's AIR front end, and all
  40 compute kernels compile to Vulkan pipelines (`pack_census --compute`). Upgrade cost:
  about 1.7 ms per library, about 4 s for the whole pack once.
- Verified 2026-10-19 with Roblox 0.743.0.7431134, CiderDarling `b0fcb070`, native
  Wayland (a private KWin compositor using GPU rendering), NVIDIA RTX 3060 Ti:
  login and signed-in home render correctly; Write a Letter (`8425637426`) joins
  and draws its 3D world, character and UI. More than 600 Vulkan frames presented
  successfully during the 90-second test, without Metal API refusal messages.
- Fixed the paused prototype's startup crash in Darling's
  `-[CARenderer _renderLayer:z:currentTime:]`: `QMMetalLayer` returns nil contents,
  and the shim excludes it from the GL bitmap compositor. Vulkan presents its
  pixels directly through the native subsurface. Other CALayers still composite.
- The real C ABI GPU test verifies every RGBA texel after render clears and
  texture-to-buffer readback, both at 1 sample and with 4× MSAA resolve.
- Shared host handles use immutable Rust borrows; only thread-confined encoders
  receive mutable borrows. Concurrent AIR cache writers use separate temporary
  files before atomic replacement. Switching renderers clears the previous
  Darling session's Metal framework environment.
- Still experimental: longer gameplay, resize/minimize stress, visibility-query
  correctness, other GPUs and X11 presentation need testing. VR is disabled for
  Metal because Quadra's VR bridge attaches to the OpenGL renderer.
- The X11 window backend stalls on this desktop (niri with xwayland-satellite) about 0.3 s
  into launch for OpenGL too: the main thread waits in a darlingserver call. This is not
  related to Metal. Native Wayland works.

## Layout

| Path | What |
|---|---|
| `quadra_metal.h` | Guest/host ABI |
| `framework/` | `Metal.framework` (Objective-C, no SDK headers, like the shim) |
| `host/src/lib.rs` | The table over metal2vulkan-runtime |
| `host/src/present.rs` | `CAMetalLayer` drawables: Vulkan swapchains, presenter thread |
| `host/src/air.rs` | Old AIR upgrade through libLLVM |
| `host/examples/pack_census.rs` | Every library of a pack as the game loads them (`--compute`: kernels too) |
| `host/examples/air_census.rs` | AIR decode of `.bc` files |
| `build.sh` | Builds `build/metal/Metal.framework` and `build/metal/libquadra_metal_host.so` |
| `../../launcher/macoblox/{core,graphics}.py` | Lazy build, host device validation and renderer environment |
| `../../wayland_{bridge.h,host.cpp,appkit.m}` | Wayland helper ABI 4, native Metal subsurfaces |
| `../../tests/metal_host_test.c` | GPU clear, MSAA resolve and exact readback through the C ABI |
| `tools/run_metal_test.py` | Starts the repository's launcher session (web bridge included) without saving settings |
| `tools/maps_watch.sh` | Saves RobloxPlayer's `/proc/<pid>/maps` while it runs, for crash addresses |
| `tools/air_upgrade_prototype.py` | The first, text-only version of the AIR upgrade (llvm-dis/llvm-as) |

## Running it again

```sh
prototype/metal-vulkan/build.sh            # needs clang, lld, Rust 1.98+
# The repository is its own data folder when run from source: give it a client.
rsync -a --exclude Contents/MacOS/ClientSettings ~/.local/share/QuadraHQ/RobloxPlayer.app/ RobloxPlayer.app/
QM_DIAG=1 python3 -I prototype/metal-vulkan/tools/run_metal_test.py wayland 60 metal
cargo run --release --manifest-path prototype/metal-vulkan/host/Cargo.toml --example pack_census -- \
    RobloxPlayer.app/Contents/Resources/shaders/shaders_metal_osx.pack --compute
clang -O2 -Wall -Wextra tests/metal_host_test.c -ldl -o /tmp/quadra-metal-host-test
/tmp/quadra-metal-host-test build/metal/libquadra_metal_host.so
```

The test script sets `renderer=metal`, turns VR, MangoHud and Discord off, and never writes
`settings.json`. Logs go to `logs/` in the repository. The host library reads
`MACOBLOX_METAL_PRESENT_MODE` (`fifo`, `mailbox` or `immediate`) and `MACOBLOX_METAL_LIBLLVM`
(an explicit libLLVM).

## Licenses

Everything here was written for Quadra (GPL-3.0-only). metal2vulkan is a Cargo dependency
(GPL-2.0-or-later OR LGPL-3.0-or-later). No code from spidercraft's port or its continuation
(github.com/georgenoob1234/Roblox-Mac-Linux-Port, no license) is included. That continuation
handles the same old-AIR forms with a patch to metal2vulkan 0.1 and an offline SPIR-V cache.
