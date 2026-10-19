Quadra 0.32 adds **Metal on Vulkan (experimental)** and includes the prebuilt bridge in the Arch, Debian/Ubuntu and Fedora packages.

Select **Settings → Environment → Game → Renderer → Metal on Vulkan (experimental)** and use the native **Wayland** window backend. Restart Roblox after changing renderers. Packaged installs need no Rust compiler; the first Metal launch upgrades and caches Roblox's shaders.

- Fixes the startup crash caused by Darling treating a Metal layer as a bitmap. Vulkan now presents through the window's own Wayland subsurface.
- Keeps switching back to OpenGL clean by clearing the previous renderer's framework environment.
- Uses immutable host resource borrows and separate temporary files for concurrent shader-cache writers.
- Checks the Vulkan device and LLVM shader upgrader before starting Roblox, with a launcher error if they are unavailable.

Validation: Write a Letter joined and rendered its 3D world, character and UI for 90 seconds, presenting over 600 Vulkan frames on an RTX 3060 Ti with native Wayland. All 2,266 shader libraries and 40 compute kernels passed the shader census. The native regression suite and 236 Python tests passed, as did real AppKit keyboard/captured-mouse checks and exact GPU readback at 1× and 4× MSAA.

**Experimental limits:** longer gameplay, resize/minimize stress, other GPUs and X11 presentation need more testing. VR requires OpenGL or Vulkan/Zink. Flatpak does not include the Metal bridge yet. The intermittent FPS drop (#34) and brief freeze after leaving a game remain under investigation.

Fully close and reopen the launcher after updating. OpenGL remains the default.

Install `.pkg.tar.zst` on Arch derivatives, `.deb` on Ubuntu 24.04+/Debian 13+, or the binary `.rpm` on current Fedora. Darling/CiderDarling runtime downloads remain separate. Source archives and build recipes are attached with `SHA256SUMS`.
