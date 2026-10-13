Cider 0.24 fixes native Wayland startup and game-join freezes, mouse positioning, and window resizing.

- Skip unsupported Darling HID discovery and Apple platform service queries that blocked startup and game joining. SDL supplies keyboard and mouse input.
- Align clicks with the visible cursor and preserve consistent window coordinates after resizing.
- Resize the parent Wayland buffer and commit window geometry so the outer border follows the game image.
- Rename the launcher backend option to **Wayland**, removing its experimental label. Select it under **Settings → Environment → Game → Window backend**; changes apply on the next launch.

Roblox joining, aligned clicks and border resizing are confirmed on the local niri/NVIDIA setup. Native OpenGL and Vulkan/Zink regression fixtures verify core/compatibility rendering, pointer conversions and actual parent-buffer commits through fullscreen and restore. Launcher regressions and all three distro package builds must pass before publication. Separate Zink crash and duplicate-typing reports remain under investigation.

Install the package matching your distribution: `.pkg.tar.zst` for Arch derivatives, `.deb` for Ubuntu 24.04+/Debian 13+, or the binary `.rpm` for current Fedora. Packages include the launcher and prebuilt shims; select either Darling provider in the launcher. CiderDarling runtime updates download separately.

The source archive, Arch recipe and source RPM are attached, with `SHA256SUMS` for verification.
