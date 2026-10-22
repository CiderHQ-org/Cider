Quadra 0.35 adds a redesigned launcher and fixes for Roblox downloads, mouse capture and shared GPU memory.

- **Launcher appearances:** Grid is the new default, with square controls, a grid backdrop and a compact dashboard. Choose **Settings → Environment → Interface → Launcher appearance** for Grid, the original GNOME interface, or the dark monochrome style based on aubree.lat. The choice applies immediately and is saved, preserving running sessions, logs and open settings.
- **Roblox update HTTP 403 (#36):** public deployment requests try alternate official metadata and archive servers before the Quadra mirror. Downloads retain channel/version checks and atomic installation. The mirror service source also handles a blocked primary archive origin on a cold cache.
- **Shift Lock and switching windows (#37):** native Wayland keeps centering requests in event order. Wayland and X11 cancel camera-drag capture interrupted by switching windows; button-free Shift Lock can resume when focus returns.
- **Integrated GPU memory (#38):** Quadra M2VK bounds its graphics recommendation by the selected Vulkan device, available heap budget and system RAM headroom on shared-memory GPUs, with a conservative 512 MiB fallback.

This update retains the Quadra M2VK renderer and staged shader preloading from 0.34. OpenGL remains the default. Physical gameplay validation on the AMD Renoir laptop reporting #38 is still needed; the regression models that shared-RAM configuration and exercises actual Vulkan readback separately.

Validation covers launcher regressions, live GTK appearance changes, native Wayland/AppKit input, focused X11 capture checks, Rust host tests and exact 1×/4× MSAA GPU readback. The full optional X11 flood fixture has an existing fallback extra-button failure recorded in BUG_TRIAGE.md.

Fully close and reopen Quadra after updating. Native packages include the matching Quadra M2VK host and Metal framework. VR requires OpenGL or Vulkan/Zink, and Flatpak does not include the Metal bridge yet. Install `.pkg.tar.zst` on Arch derivatives, `.deb` on Ubuntu 24.04+/Debian 13+, or the binary `.rpm` on current Fedora. Darling/CiderDarling downloads remain separate. Source archives, build recipes and `SHA256SUMS` are attached.
