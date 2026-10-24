# Metal on Vulkan (experimental)

This checkout uses QuadraM2VK's `development` branch, based on upstream `a2c440b`,
and requires guest/host ABI **2**. Build and deploy the framework and host library together.
The original Quadra dependency was `720ef1c`; its recorded gameplay evidence below does
not qualify this modified build. The preceding `0b73dd0` bridge passed an authored RTX 3060 Ti
native Wayland lifecycle test, and the user reported that home and minimum-graphics stalls
were gone. First-visit area hitches remain under investigation. The increased warm-state
limit below has software Vulkan coverage; hardware testing and longer guest lifetime
qualification remain open for this candidate.

A third renderer next to OpenGL and Vulkan (Zink): Roblox's own **Metal** renderer, with every
Metal call run on the host's Vulkan driver. Native 0.32 packages and source builds expose it in
**Settings → Environment → Game → Renderer → Metal on Vulkan (experimental)**.
OpenGL remains the default. Native packages ship the bridge; Flatpak does not yet.

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
- `host/`: the local QuadraM2VK fork of [steelbrain/metal2vulkan](https://github.com/steelbrain/metal2vulkan) 0.2's runtime
  (GPL-2.0-or-later OR LGPL-3.0-or-later) behind the C table, plus
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
  - runtime-sized StructuredBuffers represented as one-element array wrappers lose the old
    `air.buffer_size` hint. Keeping it clips Vulkan descriptors to one instance record, so
    instance uploads overwrite that record and leave most models invisible;
  - the text is reassembled as current bitcode.

  `normalize_metallib` then inserts the empty extended header that format 2.7 has. Results are
  cached by SHA-256 in `$MACOBLOX_METAL_SHADER_CACHE/air-upgrade-v3`. Entries carry a
  length, source identity and checksum; rejected entries are rebuilt. Upgrade and preload
  namespaces each have a 512 MiB disk budget. Unavailable cache storage uses bounded
  in-memory runtime caching so a cache directory failure need not stop the renderer.

## Shader preloading and diagnostics

**Settings → Environment → Game → Shader preloading** is enabled by default for Metal.
The launcher prepares the installed client's shader libraries, including on the first
launch. This uses the existing library loader to normalize/cache legacy AIR and validate
containers; it does not guess unseen render states or compile every shader into a pipeline.
The first session learns successful render and compute pipeline descriptions locally;
later launches preload those descriptions for the installed client version. New shaders
and new render-state combinations can still compile during play. Client shaders and
cache contents stay on this machine and are not included in diagnostic exports.

**Prepare client shader libraries** and **Preload local textures and fonts** can be changed
separately under Shader preloading. Progress identifies library preparation, learned pipelines
and local resources. Resource warming reads bundled textures, fonts and models into the OS
file cache; it does not allocate their GPU textures, decode them, or download world assets.

The launcher shows **Skip and play**. Skipping, a 20-second interval without progress, or
reaching the 120-second helper timeout ends the helper before launch and skips the game's
additional warmup. Memory pressure does the same: the launcher samples host/cgroup headroom
and helper RSS every 250 ms, with 768 MiB reserved and a helper RSS threshold of the smaller
of 1.5 GiB and one quarter of initially available memory (512 MiB when unknown). These are
sampled host-memory limits rather than exact VRAM or instantaneous allocation caps.
Process-group cleanup includes descendants even after the helper leader exits.

Library preparation validates RBXS v11 ranges before reading them, uses at most 4096 unique
payload ranges and 128 MiB of input from a pack no larger than 256 MiB, deduplicates identical
Metal containers, and releases each library immediately. A missing/unsupported library is
nonfatal; the game can still use its normal loading path. The helper reuses one Vulkan device
for library preparation and pipeline replay through an optional host export, keeping ABI 2.
Resource warming scans at most 8192 entries/4096 files, skips symlinks and special files, and
reads at most 128 MiB over three seconds with a smaller cap under memory pressure. Only
bundled asset file types are selected; settings, cookies and downloaded caches are excluded.

The helper handles at most 4096 recorded pipelines. The game's own Vulkan device can
retain up to 256 warm pipeline states on a host with enough available memory, with a
128 MiB source-weight limit. The count uses at most a quarter of available host/cgroup
memory, an estimated 8 MiB per state, and 768 MiB of headroom. Unknown memory availability
keeps the previous 64-state limit. Driver allocations are not directly measured, so this
is a count limit rather than an exact memory cap. It checks a
five-second deadline and host memory pressure between creations; an individual driver
call can exceed that deadline. This preserves actual Vulkan objects for early pipeline
reuse while keeping warmup work off the gameplay worker pool. CPU/cgroup memory limits
also cap pipeline compilation concurrency.

**Metal performance diagnostics** is off by default. When enabled, bounded JSONL logs
record compilation, buffer creation/initial-data upload, texture creation/region upload,
encoder lifetime, acquire/present, submit/wait, cache counts and live
allocation snapshots, at most once per second on commit and on final device release.
Recent timing percentiles cover up to 512 samples. `MACOBLOX_METAL_GPU_TIMESTAMPS=1`
additionally requests GPU spans while diagnostics is enabled. Encoder lifetime includes
time spent by the caller; these observations are not a frame-time or FPS measurement.
`currentAllocatedSize` now uses per-device live allocator bytes; reserved/imported bytes
are separate. Vulkan driver allocations and wrapped external images are excluded.
Working-set recommendations use device-local heap budgets where available: a discrete card's
largest device-local heap counts once (without Resizable BAR the driver lists a 256 MiB window
onto VRAM as a heap beside it), and a unified-memory GPU's heaps all count (an APU's small VRAM
carve-out beside the system memory it also maps). `MACOBLOX_VRAM_BYTES` can only lower the answer.

Presentation defaults to mailbox when the surface supports it, keeping vblank synchronization
while replacing obsolete queued frames. It falls back to FIFO when mailbox is unavailable.
`MACOBLOX_METAL_PRESENT_MODE=fifo` retains FIFO explicitly; `mailbox` and `immediate` select
the other policies. Mailbox requests at least the surface's minimum image count plus one,
within its advertised maximum. AppKit's layer mutex is released before image acquisition,
with the layer retained across that wait. The presenter queue holds at most 16 pending
drawables; a rejected enqueue retires its chain instead of blocking a runtime callback.

Diagnostics include `presentation` counters for acquired images, timeouts, cancellations,
swapchain rebuilds/modes and failed presents, plus `present_queue_delay` timings. These are
host WSI observations, not proof of when pixels reached the display. A failed present retires
its chain so an unconsumed acquisition cannot silently exhaust the image pool. Surface alpha
mode and image count selection follow the driver's advertised capabilities.

The policy follows [CAMetalLayer display synchronization](https://developer.apple.com/documentation/quartzcore/cametallayer/displaysyncenabled)
and [Vulkan present modes](https://docs.vulkan.org/refpages/latest/refpages/source/VkPresentModeKHR.html).
The authored `tests/metal_present_test.c` exercises a native Wayland render surface while
visible, covered by an opaque sibling, restored and resized. Its native driver/compositor
results must be collected separately from the software offscreen tests.

Native helpers can call `quadra_metal_host_preload` and
`quadra_metal_host_diagnostics`; these optional exports do not change guest ABI 2.

## Tuning, memory pressure and hardware reports

Settings -> Environment -> Quadra M2VK sets these for the next launch; the host reads them
from the environment, and an unset, empty or misspelled value is the default:

| Variable | Values | Effect |
| --- | --- | --- |
| `MACOBLOX_METAL_ACCURACY` | `fast` (default), `textures`, `exact` | `textures` keeps Metal's BC1-BC5 decode in a twin where the driver's is not measured to match; `exact` is every exact form (`DevicePolicy::exact_answers`) |
| `MACOBLOX_METAL_PRESENT_MODE` | empty (automatic), `mailbox`, `fifo`, `immediate` | the swapchain's present mode where the surface offers it |
| `MACOBLOX_METAL_MEMORY_PRIORITY` | `0` | leaves memory priority and pageable memory off |
| `MACOBLOX_METAL_COMPILE_THREADS` | 1-32 (default from CPUs and memory) | pipeline compilations at once |
| `MACOBLOX_METAL_WARM_STATES` | 0-1024 (default 256) | the most learned states kept warm, within a quarter of the available memory |
| `MACOBLOX_VRAM_BYTES` | bytes | a cap on the graphics memory the game is told it has |

The runtime enables `VK_EXT_memory_priority` and `VK_EXT_pageable_device_local_memory` on a device
that has them and gives its blocks priorities (render targets and buffers above pooled textures).
On the RTX 3060 Ti (8 GiB, 615.78.08) it made 9,216 MiB of `Private` buffers where the same runtime
without them failed at 7,168 MiB with an out-of-device-memory error: a card short of video memory
demotes textures instead of failing an allocation. The launch log's `[Quadra Metal] gpu:` line states the
vendor and device IDs, driver, whether the runtime has measured that exact combination, the driver
defects it assumes and the optional extensions taken; a problem report should include it.

Before a launch, the launcher's probe opens the device and runs `quadra_metal_host_self_test`
(a fill of host memory copied through device-local memory and read back). If either fails, the launch
uses OpenGL once and says why (the saved renderer is unchanged; the "Fall back to OpenGL" switch turns
this off). `quadrahq --hardware-report --graphics` adds the host's view of the GPU, from
`quadra_metal_host_identity`, under `m2vk`: the single file to send for an AMD, Intel or other
NVIDIA GPU.

A presenter that waits a second for an image and finds none logs, once per distinct state, how many
images the game holds and how many presents are queued, with the swapchain's age and the time since
a present last returned.

## Baseline evidence and qualification

The gameplay and hardware results in this section were recorded by the original Quadra
bridge. Recheck them with the modified framework and host before distributing this build.

- Roblox accepts the device: `[FLog::Graphics] Metal renderer: NVIDIA GeForce RTX 3060 Ti`.
- All 2,266 shader libraries of the pack decode through metal2vulkan's AIR front end, and all
  40 compute kernels compile to Vulkan pipelines (`pack_census --compute`). Upgrade cost:
  about 1.7 ms per library, about 4 s for the whole pack once.
- Verified 2026-10-19 with Roblox 0.743.0.7431134, CiderDarling `b0fcb070`, native
  Wayland (a private KWin compositor using GPU rendering), NVIDIA RTX 3060 Ti:
  login and signed-in home render correctly; Write a Letter (`8425637426`) joins
  and renders the spawn house's walls, windows, floor and doorway, with its character
  and UI. Verified after dismissing the rules dialog in a 110-second session, with
  more than 600 Vulkan frames presented and no Vulkan validation errors.
- Fixed the paused prototype's startup crash in Darling's
  `-[CARenderer _renderLayer:z:currentTime:]`: `QMMetalLayer` returns nil contents,
  and the shim excludes it from the GL bitmap compositor. Vulkan presents its
  pixels directly through the native subsurface. Other CALayers still composite.
- The real C ABI GPU test verifies every RGBA texel after render clears and
  texture-to-buffer readback, both at 1 sample and with 4× MSAA resolve.
- A self-authored legacy AIR regression assembles a metallib, upgrades it, and checks
  all 64 records after a GPU scatter upload. It runs in the Metal host CI job:
  `cargo test --locked --release --manifest-path prototype/metal-vulkan/host/Cargo.toml --lib -- --include-ignored`.
  The actual client's full-instance upload and transform-update kernels also passed
  exact readback of 64 records on the RTX 3060 Ti after this repair.
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

Place the reviewed fork at `vendor/metal2vulkan` before building. A source checkout or a
symlink works; all three product crates must come from the same revision. For the offline
source archive, from the Quadra repository root:

```sh
mkdir -p vendor/metal2vulkan
tar -xzf /path/to/metal2vulkan-source.tar.gz --strip-components=1 -C vendor/metal2vulkan
```

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
`MACOBLOX_METAL_PRESENT_MODE` (`fifo`, `mailbox` or `immediate`), `MACOBLOX_METAL_LIBLLVM`
(an explicit libLLVM; by default a libLLVM the process already maps, then the newest 15 or later) and
the tuning variables above.

## ABI 2 behavior

- Host texture reads and writes validate their exact format/block/pitch footprint before
  constructing a Rust slice. A zero-byte operation accepts a null pointer; a nonempty
  source must be readable for the queried span. Readback also checks the supplied capacity.
- The first runtime encoder failure and a refused commit remain on the command buffer.
  Status and both waits return `QM_STATUS_ERROR` for a rejected commit.
- `dispatchThreads` preserves the requested invocation count, including a partial final
  group. Dynamic threadgroup memory, fences, buffer/texture residency and explicit barriers
  are forwarded. Heap residency remains unsupported by this bridge.
- Render bulk buffer, texture and sampler bindings use bounded arrays and one host call per
  range. Compute inline byte storage is reused while preserving the immediate copy contract.
- Encoder storage is boxed separately, so the largest encoder no longer determines the
  allocation size of every buffer, texture and other host handle.
- Guest completion workers retire after an idle interval and restart when needed. Scheduled
  waits observe the host's scheduled transition; completion waits include guest handlers.
- Swapchain images retain an owner through texture views and submitted GPU use. Acquisition
  and presentation do not share a state mutex across their blocking driver calls. Unused
  drawables retire their swapchain on the next acquisition when individual image release is
  unavailable; this conservative fallback can stall during cancellation/resize.
- Supported native BC1–BC5 textures use the device's compressed decoder by default, avoiding
  extra decoded images and their update work. Native results can differ from Metal. Rust
  consumers can select `DevicePolicy::exact_answers()` or `BlockDecodePolicy::Exact` to keep
  the fitted decode; ABI 2's reserved device options do not expose this policy yet. Unsupported
  formats retain their existing emulation.

The authored regressions are `tests/metal_fork_test.c`, `metal_dispatch.ll`, `metal_draw.ll`
and `assemble_metal_test.py`. They contain no client shaders. Compile the test with
`-ldl -lpthread -lX11`, assemble `metal_dispatch.ll`, then run it with the host library and
generated metallib paths. `--offscreen` explicitly skips WSI; without it a working X11
display is required. Use Vulkan validation and an outer timeout. `tests/metal_perf.c`
compares the original ABI 1 bridge and this ABI 2 build on the same authored workload.

## Licenses

Everything here was written for Quadra (GPL-3.0-only). metal2vulkan is a Cargo dependency
(GPL-2.0-or-later OR LGPL-3.0-or-later). No code from spidercraft's port or its continuation
(github.com/georgenoob1234/Roblox-Mac-Linux-Port, no license) is included. That continuation
handles the same old-AIR forms with a patch to metal2vulkan 0.1 and an offline SPIR-V cache.
