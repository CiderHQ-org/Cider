Cider 0.24p1 fixes Error 256 when joining games after Roblox updated to 0.743.

- Add verified transport compatibility for **Roblox 0.743.0.7431129**. The updated client moved the networking code and selected RbxTransport despite the saved flags. Cider now applies the inspected RakNet fixes for this build, including both shared-config and legacy dummy-connection paths.
- Keep the cursor visible while holding right-click to move the camera on Wayland and X11/Xwayland. Releasing right-click or losing focus clears the cursor override; existing Shift Lock and first-person cursor behavior is preserved.

The reporter confirms game joining works on Roblox 0.743 after the fix. Validation includes the official executable, all 32 transport/startup-throttle patch combinations, native x86_64 branch checks, 20 native fixtures and 199 Python tests. Complete executable checksum validation and atomic patching remain in place; unsupported builds are left unchanged.

**Update Cider, then close and reopen the launcher before starting Roblox.**

Install the package matching your distribution: `.pkg.tar.zst` for Arch derivatives, `.deb` for Ubuntu 24.04+/Debian 13+, or the binary `.rpm` for current Fedora. Packages include the launcher and prebuilt shims; select either Darling provider in the launcher. CiderDarling runtime updates download separately.

The source archive, Arch recipe and source RPM are attached, with `SHA256SUMS` for verification.
