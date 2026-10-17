Cider 0.30 adds experimental VR: Roblox's own VR mode on a headset, through your OpenXR runtime.

- **VR headsets (experimental):** the macOS Roblox client still contains Roblox's VR mode, and Cider now supplies the OpenXR device it was missing. Meta Quest headsets work through WiVRn, PC headsets through Monado. The VR home menu, games, head tracking, Touch/Index controllers, vibration and recentering work. Turn it on in **Settings → VR**, start the runtime with the headset connected, then play. Render resolution and a desktop mirror are adjustable; the headset keeps the refresh rate chosen in the runtime. Needs the OpenXR loader (`openxr` on Arch, `libopenxr-loader1` on Debian/Ubuntu). Tested on a Quest 2 with WiVRn 26.9 at a steady 72 Hz.
- **Native Wayland typing:** chat and search no longer insert a key twice, and Ctrl shortcuts (select all, copy, cut, paste, word navigation and deletion) work again.

Validation includes the vendored OpenXR ABI against the Khronos headers, the shim's client lookups against Roblox 0.743.0.7431134, a native OpenXR session test with controllers and vibration, the launcher's runtime discovery, and in-headset play with recordings.

**Known issue:** the brief freeze after leaving a game remains unresolved.

**Update Cider, then fully close and reopen the launcher before starting Roblox.**

Install the package matching your distribution: `.pkg.tar.zst` for Arch derivatives, `.deb` for Ubuntu 24.04+/Debian 13+, or the binary `.rpm` for current Fedora. Packages include the launcher and prebuilt shims; select either Darling provider in the launcher. CiderDarling runtime updates download separately.

The source archive, Arch recipe and source RPM are attached, with `SHA256SUMS` for verification.
