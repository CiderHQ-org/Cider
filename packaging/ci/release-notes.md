Quadra 0.35.p2 repairs Roblox's public download fallback and adds a bug-report flow with required diagnostics.

- **HTTP 403 recovery:** after a primary Roblox denial, keep trying the identical deployment if another official origin returns 404, 408, 429 or a temporary server error. Continue to the Quadra mirror if official alternates are unavailable. Initial non-403 errors and authentication restrictions retain their normal behavior; account and game requests never use the mirror.
- **Live mirror repair:** update the deployed service, which was still running the older implementation without alternate archive origins. A cold cache can now retry AWS/Akamai instead of repeating the primary origin's denial.
- **Bug reports:** [quadrahq.org/report/](https://quadrahq.org/report/) explains how to collect the archive from the failed run and opens the public GitHub report form. The form requires a `.tar.gz` attachment, reproduction steps, expected/actual behavior, Quadra version, renderer and window backend. Screenshots and extra logs are optional.

Validation includes 272 Python tests and native helper checks, mixed HTTP failure regressions, the deployed mirror's script checksum, and a complete 158,362,150-byte public-mirror client installation with forced primary 403 and alternate 503 responses. The embedded Roblox version is checked, the old client is preserved, and temporary downloads are removed.

The new GTX 1060 / Wayland / Zink / MangoHud exit and the RX 6800 loading crash remain undiagnosed: neither supplied log includes a fatal fault address or stack. The Renoir/Metal memory mitigation still needs gameplay confirmation on the affected laptop. This patch does not claim to fix those crashes.

Fully close and reopen Quadra after updating. OpenGL remains the default; VR requires OpenGL or Vulkan/Zink. Native packages include the matching Metal host and framework. Flatpak does not include the Metal bridge yet. Install `.pkg.tar.zst` on Arch derivatives, `.deb` on Ubuntu 24.04+/Debian 13+, or the binary `.rpm` on current Fedora. Darling/CiderDarling downloads remain separate. Source archives, build recipes and `SHA256SUMS` are attached.
