Cider now discovers complete CiderDarling CI releases automatically. Available
runtime updates appear in Settings → CiderDarling and install in a separate
terminal with download progress and sudo prompts. Regular Darling remains a
runtime choice, and each runtime keeps its own prefix and Roblox sign-in.

This release also fixes game joins freezing in Darling's exp10 math wrappers,
adds freeze diagnostics and CiderDarling controls, and includes the recent
launcher, logging and session fixes.

Install the package for your distro:

- Arch Linux, CachyOS and compatible derivatives: the `.pkg.tar.zst` package
  with `sudo pacman -U ./ciderhq-*.pkg.tar.zst`.
- Ubuntu 24.04+, Debian 13+ and compatible derivatives: the `.deb` package
  with `sudo apt install ./ciderhq_*.deb`.
- Current Fedora and compatible derivatives: the binary `.rpm` package
  with `sudo dnf install ./ciderhq-*.x86_64.rpm`.

Choose an installed Darling runtime or install CiderDarling from the launcher.
Roblox is downloaded on first setup. Packages install Cider's launcher and
compatibility shims; the runtime update downloads are separate.

The source archive, AUR recipe and source RPM are also attached. `SHA256SUMS`
records every attached package and source archive.
