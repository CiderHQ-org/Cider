# Native distro packages

These are package recipes for Quadra. Each package
builds the shim, native Wayland helper and Metal framework during packaging, installs desktop
and link handlers, and downloads Roblox on first setup. Personal settings and
sign-in are stored in the user's directories. The website and user logs are
excluded. Package updates use the distro's package manager.

| Distro family | Recipe | Derivatives using the same package format |
| --- | --- | --- |
| Arch Linux | [AUR recipes](aur/README.md) | Manjaro, EndeavourOS, CachyOS |
| Debian 13+, Ubuntu 24.04+ | [Debian overlay](debian/control) | Linux Mint 22 and compatible Debian/Ubuntu derivatives |
| Fedora | [RPM spec](rpm/quadrahq.spec) | Nobara and compatible Fedora derivatives |
| openSUSE | [RPM spec](rpm/quadrahq.spec) | Tumbleweed; Leap releases supplying the required UI versions |
| NixOS (x86_64) | [Flake and NixOS module](nix/README.md) | NixOS with flakes enabled |

The release workflow builds Arch, Ubuntu 24.04 and Fedora packages in their
own distro containers, then publishes the packages together after every build
succeeds. The Rust Metal host is built once on Ubuntu 24.04 and checked with
software Vulkan readback before being included in all three packages. It also attaches the immutable source archive and checksums and pins
the stable AUR recipe on main. The recipes do not submit packages to distro
repositories or the AUR.
The `noreply@aubree.wtf` maintainer address is a placeholder: set the real
packaging contact before submitting to a distro.

Quadra 0.37 uses the `quadrahq` package name. The release workflow pins the
source archive checksum and stable AUR recipe after publication. The frozen
Cider 0.30 AUR recipe remains in `aur/ciderhq/`. Use `--local` to package
unreleased source changes.

## Requirements

The Nix package supplies its own Darling runtime and build dependencies;
see its [separate instructions](nix/README.md). The requirements below apply
to the Arch, Debian and RPM recipes.

- x86_64 Linux with glibc. This macOS client and shim do not provide ARM or
  Alpine/musl packages.
- A **full Darling sysroot**, including GUI frameworks and stubs, in the
  build environment. CI stages a verified sysroot; local builds can set
  `DARLING_SYSROOT=/path/to/libexec/darling`. At runtime users choose regular
  Darling or CiderDarling in the launcher. Quadra's package does not force an
  additional regular Darling installation alongside CiderDarling.
- GTK 4.14+, libadwaita 1.5+, WebKitGTK API 6.0, Python/PyGObject/Cairo,
  SDL2 and Wayland. Debian 12 and Ubuntu 22.04's original UI libraries are
  below these requirements.
- Clang, LLD and pkg-config for the native build. Compile on the target distro
  or its build chroot so the helper uses that distro's library versions.
- Rust 1.98+ (cargo/rustc) to build the Metal host. Release CI provides the
  verified prebuilt host through `QUADRA_METAL_HOST_LIBRARY`; Debian uses the
  `pkg.quadrahq.prebuilt-metal` build profile and RPM uses `--with prebuilt_metal`
  for that CI path. Ordinary source builds compile it with Cargo.

The recipes declare a PulseAudio-compatible playback helper, which works
with PipeWire's PulseAudio service too. Native PipeWire playback and MangoHud
are optional. Install the GPU's OpenGL/EGL driver; Vulkan/Zink also needs Mesa
and the appropriate Vulkan driver. Native packages include the Metal bridge
and depend on the Vulkan loader and LLVM shared libraries; users still install
their hardware Vulkan driver. The default renderer remains OpenGL.

## Prepare sources

The release workflow attaches `quadrahq-0.37-source.tar.gz` and pins its
checksum in `release.json`. To package local source edits:

```bash
./packaging/prepare-source.sh "$PWD/work/quadrahq-packages" --local
```

This produces a source archive, Debian and RPM inputs, and a `quadrahq`
PKGBUILD with that archive's checksum. It never installs to the host.


From the Quadra checkout:

```bash
./packaging/prepare-source.sh "$PWD/work/native-packages"
```

This downloads the checksum-verified Quadra release and places the Debian
overlay and RPM inputs in a new output directory. It requires `curl`, `tar`
and `sha256sum`. To use an already downloaded release archive:

```bash
./packaging/prepare-source.sh "$PWD/work/native-packages" /path/to/quadrahq-0.37-source.tar.gz
```

The output directory must not already exist. Arch builds use their own AUR
recipes and do not require this preparation step. Interrupted preparations
remove their temporary files and leave the requested output directory free
for a retry.

## Debian / Ubuntu / Mint

Stage a full Darling sysroot in the build environment first.
Then install the packaging tools and native development dependencies:

```bash
sudo apt install build-essential debhelper dh-python python3 clang lld \
  pkg-config libsdl2-dev libwayland-dev
cd work/native-packages/Quadra-0.37
dpkg-buildpackage -b -us -uc
```

Build dependencies are checked by `dpkg-buildpackage`; `DARLING_SYSROOT` supplies the macOS libraries. Binary packages appear
one directory above the source directory. Install using `apt`, which resolves
dependencies from the configured repositories:

```bash
sudo apt install ../quadrahq_0.37-1_amd64.deb
```

The recipe uses debhelper for Python bytecode and desktop/icon/MIME cache
integration. Builds do not launch Roblox or run tests.

To create an unsigned Debian source package, run `dpkg-source -b .` from that
source directory. Keep its `.dsc`, `.debian.tar.xz` and original release
archive together. Creating a source package does not compile a binary package.

## Fedora / openSUSE

Install a full Darling RPM and the `BuildRequires` in the spec first.
For Fedora, the package tools and native build libraries are:

```bash
sudo dnf install rpm-build clang lld gcc-c++ python3 pkgconf-pkg-config \
  SDL2-devel wayland-devel
```

For openSUSE:

```bash
sudo zypper install rpm-build clang lld gcc-c++ python3 pkg-config \
  libSDL2-devel wayland-devel
```

From the checkout, build with the prepared RPM inputs:

```bash
rpmbuild --define "_topdir $PWD/work/native-packages/rpm" \
  -ba work/native-packages/rpm/SPECS/quadrahq.spec
```

The spec selects openSUSE's typelib package names using `suse_version` and
Fedora's GTK/WebKit package names otherwise. Native dependencies are also
generated from the ELF helper. Output is in `rpm/RPMS/x86_64/`; install the
result using `dnf install ./package.rpm` or `zypper install ./package.rpm`.
Use the target distro's build tools; defining `suse_version` on another
distro does not make its binaries an openSUSE build.

For a source RPM only, use `-bs` instead of `-ba`. The resulting `.src.rpm`
contains the source archive, payload installer and spec for a target-distro
rebuild. It is not an installable application RPM.

## Updating the recipes

For a new release, update the version and checksum in `release.json`,
the Debian changelog, the RPM `Version` and changelog, and the AUR recipes.
Increment the Debian revision / RPM release / AUR `pkgrel` for packaging-only
changes. Keep the release source archive immutable and regenerate AUR
`.SRCINFO` with `makepkg --printsrcinfo`.

Dependency names were checked against the official
[Debian WebKit package](https://packages.debian.org/trixie/gir1.2-webkit-6.0),
[Debian SDL development package](https://packages.debian.org/trixie/libsdl2-dev)
and [Fedora WebKit package](https://packages.fedoraproject.org/pkgs/webkitgtk/).
The openSUSE names follow its official
[GTK 4](https://api.opensuse.org/public/source/openSUSE:Factory/gtk4/gtk4.spec),
[libadwaita](https://api.opensuse.org/public/source/openSUSE:Factory/libadwaita/libadwaita.spec),
[WebKitGTK](https://api.opensuse.org/public/source/openSUSE:Factory/webkitgtk/webkitgtk.spec)
and [PyGObject](https://api.opensuse.org/public/source/openSUSE:Factory/python-gobject/python-gobject.spec)
specs. Its optional playback helper is supplied by
[pipewire-tools](https://manpages.opensuse.org/Tumbleweed/pipewire-tools/pw-cat.1.en.html).
