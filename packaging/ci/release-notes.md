Cider 0.23patch2 repairs startup on older Darling installations and improves runtime update recovery.

- Repair the recursive sincos math wrappers in the old 4312 runtime, including float/double and pi variants.
- Preserve a live Roblox process when the Darling shell frontend disconnects with Error Code 1.
- Add **Use previous CiderDarling and restart**, keeping the current prefix and sign-in.
- Resume interrupted runtime downloads and verify cached downloads before reuse.
- Add **Collect hardware report** and `ciderhq --hardware-report --graphics`, plus numeric text-input tracing for duplicate typing.
- Keep the crash handler available when freeze diagnostics are enabled.

The old-library math regression passes with the production shim. Launcher regressions and all three distro builds must succeed before this release publishes. This release does not claim the remaining Claire Zink crash, duplicate-typing report or KDE native Wayland sizing report is resolved; affected-machine retesting is still needed.

Install the package matching your distribution: `.pkg.tar.zst` for Arch derivatives, `.deb` for Ubuntu 24.04+/Debian 13+, or the binary `.rpm` for current Fedora. Packages include the launcher and prebuilt shims; select either Darling provider in the launcher. CiderDarling runtime updates download separately.

The source archive, Arch recipe and source RPM are attached, with `SHA256SUMS` for verification.
