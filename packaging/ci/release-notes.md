Cider 0.23patch1 is a small follow-up to 0.23.

- **Discord Rich Presence** now uses CiderHQ's own Discord application with
  the Cider logo, shows the Cider version on hover, and adds **Get Cider** and
  **Game page** buttons. It also clears itself again shortly after a game
  ends, to keep the status from sticking in Legcord and Vesktop.
- **Install in terminal** (CiderDarling) now finds kitty, Alacritty, foot,
  WezTerm, Ghostty, Konsole and other terminals itself, fixing "Unable to find
  terminal required for application" on systems without `xdg-terminal-exec`.
- Cider is now licensed under the **GNU GPL v3**. The original Mac O' Blox
  MIT notice is kept in `LICENSES/MIT-MacOBlox.txt`.

Install the package for your distro:

- Arch Linux, CachyOS and compatible derivatives: the `.pkg.tar.zst` package
  with `sudo pacman -U ./ciderhq-*.pkg.tar.zst`.
- Ubuntu 24.04+, Debian 13+ and compatible derivatives: the `.deb` package
  with `sudo apt install ./ciderhq_*.deb`.
- Current Fedora and compatible derivatives: the binary `.rpm` package
  with `sudo dnf install ./ciderhq-*.x86_64.rpm`.

Arch and RPM packages are versioned `0.23.patch1` so package managers treat
them as an upgrade from 0.23. Source installs update from the launcher as usual.

The source archive, AUR recipe and source RPM are also attached. `SHA256SUMS`
records every attached package and source archive.
