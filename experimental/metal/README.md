# Native Metal → Vulkan experiment

This is an offscreen rendering prototype. It is excluded from the launcher and
the normal shim build. It does not run the Roblox game through native Vulkan yet.

## Verified result

On 2026-10-03, using an NVIDIA GeForce RTX 3060 Ti, the licensed Darling Metal framework created a Vulkan-backed device,
allocated and mapped a shared buffer, and submitted a command buffer successfully.
The pipeline probe then loaded two **unaltered shaders from the installed client**,
translated their AIR through metal2vulkan, validated the resulting SPIR-V, and
rendered a red quad through Indium's Vulkan renderer. Image readback matched all
256 expected RGBA pixels. The image was cleared blue first, so the result checks
the draw. This rendering and readback use Vulkan directly.

The probe obtains an Indium device from the Objective-C Metal device. The draw
uses Indium's render API directly; it does not establish that all of the Metal
Objective-C encoder methods required by Roblox work.

```text
Native pipeline: Vulkan device NVIDIA GeForce RTX 3060 Ti
Native pipeline: loaded validated current Roblox Metal shaders
Native pipeline: graphics pipeline created and real draw encoded
Native pipeline: Vulkan draw and image readback completed
Native pipeline: 256 / 256 expected red pixels
Native pipeline: PASS real client shaders rendered the expected red quad
Probe exit: 0
```

## Source and licenses

The adapter, cache builder, probes, tests, and build/run scripts were written for
this project and use its MIT license. No code from the separate, unlicensed
reference renderer is included.

| Dependency | Source | License |
| --- | --- | --- |
| Darling Metal | local Darling source, `src/external/metal` | MPL-2.0 |
| Bundled Indium | Darling Metal's `deps/indium` | ISC, notice in `LICENSE.indium` |
| Darling libc++ headers | local Darling source, `src/external/libcxx/include` | Apache-2.0 with LLVM exception |
| Vulkan headers | Vulkan-Headers v1.3.290 | Apache-2.0 or MIT |
| Offline translator | [metal2vulkan](https://github.com/steelbrain/metal2vulkan), Cargo package 0.1.0 | LGPL-3.0-or-later |

`source_pins.json` records content hashes of the exact tested source snapshots.
The local cache has no Git metadata, so these are content pins, not claimed Git
revisions. `source_pins.py` documents and verifies the hash algorithm. The build
also needs Darling's SDK and installed runtime; these are external prerequisites,
not bundled artifacts. Retain upstream notices if distributing those components.

Only a small ISC-licensed patch to Indium is included. It adds a separate storage
buffer descriptor contract for metal2vulkan output, preserves the existing buffer
address contract, fixes a sparse-binding upload overread, checks missing/unaligned
buffer bindings, and keeps descriptor resources alive until commands complete.

No proprietary shader libraries, AIR, generated SPIR-V, cache packets, dependency
copies, or compiled binaries are included in this directory. Generated files live
under the ignored `work/` directory. The installed client and source cache are
read-only inputs.

## Reproduce

Run commands from the repository root. Required tools: Darling's installed runtime
and matching source/SDK, Clang with LLD and Mach-O support, a C++17 host compiler,
Python 3, patch, Rust 1.87 or newer, LLVM's `llvm-dis`, `spirv-val`, and a Vulkan 1.3
driver with timeline semaphores. Tests ran on x86_64 Linux. The default source
locations are the local `quadra-vulkan/src` cache; override `DARLING_SOURCE`,
`DARLING_SYSROOT`, and `VULKAN_HEADERS` if needed.

```bash
bash experimental/metal/run_tests.sh
bash experimental/metal/build.sh

# Build the licensed translator separately, including JSON reflection support.
translator_source="${XDG_CACHE_HOME:-$HOME/.cache}/quadra-vulkan/src/metal2vulkan"
python3 experimental/metal/source_pins.py \
  --darling "${DARLING_SOURCE:-${XDG_CACHE_HOME:-$HOME/.cache}/quadra-vulkan/src/darling}" \
  --vulkan "${VULKAN_HEADERS:-${XDG_CACHE_HOME:-$HOME/.cache}/quadra-vulkan/src/Vulkan-Headers-1.3.290/include}" \
  --translator "$translator_source"
cargo build --release --features serde --manifest-path "$translator_source/Cargo.toml" \
  --target-dir "$PWD/work/metal2vulkan-target"

pack="${XDG_DATA_HOME:-$HOME/.local/share}/QuadraHQ/RobloxPlayer.app/Contents/Resources/shaders/shaders_metal_osx.pack"
python3 experimental/metal/shader_cache.py "$pack" \
  --out work/metal-backend-repro/shader-cache \
  --translator "$PWD/work/metal2vulkan-target/release/metal2vulkan" --index 30 --index 4

python3 experimental/metal/run_probe.py \
  --vertex work/metal-backend-repro/shader-cache/1ddf500da2fdfc95ce7f2220f7c6dd5c77c6a244940d1ea1b5d0eaa836754c15.metallib \
  --fragment work/metal-backend-repro/shader-cache/998c41f6760a5bfdf138976a8da93956f086bbc2375325277c3619b5c4378ec6.metallib
```

The two indices and hashes above belong to the tested client pack with SHA-256
`556ddc723717747495c6b3ddcb627c30c3fa4581be887d2007bc067f6a176310`.
Shader order and inputs can change with a client update. Running the cache builder
without `--index` prints the inventory; the tested pack has 2,178 single-function
libraries: 693 vertex, 1,445 fragment, and 40 compute shaders. Two additional
shaders with texture/sampler reflection were translated during investigation;
full coverage of the pack has not been established.

`build.sh` creates a private Indium copy and refuses to overwrite an existing
copy. Choose a new `MACOBLOX_METAL_WORK` directory for a fresh rebuild and pass
that directory to `run_probe.py --work`. `run_probe.py --device` runs the smaller
device/memory/queue probe. The runner creates its own disposable Darling prefix
and refuses an existing unmarked prefix. `--baseline` can copy an existing stock
**disposable** prefix. It logs to the work directory and shuts down only its own
prefix. Darling namespace setup requires the permissions normally used to run
Darling. Neither probe opens a window or sends desktop input.

The pipeline probe exits immediately after checking GPU completion/readback to
avoid unrelated Darling framework teardown hangs. This is isolated probe behavior.
It does not test framework shutdown or a game's full resource lifecycle.

## Shader ABI safeguards

The cache builder checks Metal entry-point identity, descriptor types against the
actual SPIR-V declarations, descriptor indices, and stage identity. It remaps
vertex and fragment sets to Indium's separate sets and maps `user(locnN)` varyings
to their shared numeric interface locations. SPIR-V validation runs again after
the changes. The runtime adapter accepts only a bounded, versioned cache packet
for the SHA-256 of the requested metallib; malformed data and cache misses fail
explicitly. It also checks that the SPIR-V contains the requested stage, named
entry point, and corresponding function. It never reports successful translation
with an empty shader.

Compute dispatch, push constants, descriptor arrays, function constants, argument
buffers, named varying interfaces, runtime sampler/image specialization, and
imageblocks are currently rejected when present. Storage buffer offsets must
meet the device's alignment requirement. Supporting those cases requires a
defined ABI and backend implementation.

## Work required for gameplay

1. Implement and exercise missing `MTLDeviceInternal` capability/name/resource
   selectors, including texture, sampler, and depth/stencil creation. Add the
   missing Objective-C blit encoder and validate the existing encoders against
   the client's calls. The command-buffer initializer also retains its empty
   `_commandQueue` field instead of the supplied queue.
2. Translate and audit every shader used by real scenes, and implement the
   rejected shader ABI cases above with explicit resource lifetime rules.
3. Complete Indium's stencil attachment, multisampling, texture-view, and render
   pipeline/render-pass compatibility paths. The current source hardcodes one
   sample and throws on stencil attachments and several render-state operations.
4. Implement native window/swapchain presentation. Darling's existing CAMetalLayer
   path shares Vulkan images with OpenGL; the offscreen proof does not use or test
   that path. Native Wayland remains a separate opt-in experiment.
5. Add allocation pooling, pipeline caching, synchronization/error reporting, and
   sustained scene/lifecycle checks before making a playable launcher option.

The successful draw makes the shader/resource bridge reviewable, but these gaps
are substantial engine work. A device-only success or renderer label change
does not establish a playable native Vulkan backend.
