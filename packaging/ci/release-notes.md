Quadra 0.31 adds automatic recovery for blocked Roblox downloads and fixes right-drag mouse capture. It is the first release under the Quadra / QuadraHQ name at [quadrahq.org](https://quadrahq.org); the logo stays the same.

- **Roblox download HTTP 403 ([#36](https://github.com/CiderHQ-org/Cider/issues/36)):** Quadra tries Roblox first, then retries a denied public version check or macOS client download through the Quadra cache on `korona`. The same channel and upload are preserved. Account and game traffic stay on Roblox. Incomplete downloads leave the installed client intact.
- **RMB + LMB capture ([#35](https://github.com/CiderHQ-org/Cider/issues/35)):** pressing left-click during captured right-drag camera movement now preserves right-drag motion. Either button can be released first without leaving the motion stream misclassified. Verified through real Darling AppKit in a private Wayland compositor.
- **FPS-drop diagnostics ([#34](https://github.com/CiderHQ-org/Cider/issues/34)):** a severe sustained FPS drop now leaves one automatic log marker even when verbose FPS logging is off. **The intermittent 60-to-15 FPS drop remains undiagnosed; this release does not claim to fix it.** Collect diagnostics while a drop is happening.
- **Quadra migration:** the command/package name is `quadrahq`, and the app ID is `org.quadrahq.Quadra`. Existing Cider and MacOBlox settings, cache and Darling session files migrate without replacing existing Quadra data. CiderDarling runtime identifiers and the current GitHub repositories remain compatible.

Validation: 233 Python tests and the native regression suite passed; the shim built successfully; the mouse-button sequence passed through real AppKit; and a complete client update succeeded through the deployed HTTPS mirror after forced primary HTTP 403s, preserving the previous client backup.

**Known issues:** the random FPS drop and the brief freeze after leaving a game remain under investigation.

Update Quadra, then fully close and reopen the launcher before starting Roblox.

Install the package matching your distribution: `.pkg.tar.zst` for Arch derivatives, `.deb` for Ubuntu 24.04+/Debian 13+, or the binary `.rpm` for current Fedora. Packages include the launcher and prebuilt shims; select either Darling provider in the launcher. CiderDarling runtime updates download separately.

The source archive, Arch recipe and source RPM are attached, with `SHA256SUMS` for verification.
