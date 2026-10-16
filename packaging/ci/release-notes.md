Cider 0.25 adds a compatibility warning for Roblox networking updates and repairs initial fullscreen on native Wayland.

- **Roblox 0.743.0.7431134:** add checksum-verified RakNet compatibility for the latest hotfix. Game joining is confirmed on the reporting machine.
- **Connection warning:** if Roblox actually selects a transport other than RakNet, Cider warns that the update broke game compatibility, games might fail or show Error 256, and users should update Cider or wait for a compatibility patch. The warning appears once per launch even when the launcher is hidden or Discord presence is disabled, with log and update-check buttons. An unsupported-client header alone does not trigger it.
- **Native Wayland fullscreen:** apply fullscreen requests made before the native window exists. This repairs the case where Roblox reports fullscreen but the window remains decorated and resizable. The old code reproduces the mismatch in KWin; the fix passes initial fullscreen and repeated toggles at 100% and 150% scaling.

Validation includes the official Roblox executable, all 32 transport/startup-throttle patch combinations, native x86_64 branch checks, 20 native fixtures, 207 Python tests, and the actual GTK warning on a disposable display. Complete executable checksum validation and atomic patching remain in place; unsupported builds are left unchanged.

**Known issue:** the brief freeze after leaving a game remains unresolved and is deferred to a later update.

**Update Cider, then fully close and reopen the launcher before starting Roblox.**

Install the package matching your distribution: `.pkg.tar.zst` for Arch derivatives, `.deb` for Ubuntu 24.04+/Debian 13+, or the binary `.rpm` for current Fedora. Packages include the launcher and prebuilt shims; select either Darling provider in the launcher. CiderDarling runtime updates download separately.

The source archive, Arch recipe and source RPM are attached, with `SHA256SUMS` for verification.
