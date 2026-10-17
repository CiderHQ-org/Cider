<p align="center">
  <img src="branding/ciderhq.webp" alt="Cider logo" width="160">
</p>

<h1 align="center">
 Cider, by CiderHQ.
</h1>

 <p align="center"> 
    <a href="https://discord.gg/jCjHYYNq48"> 
      <img src="https://img.shields.io/badge/Discord-join-5865F2?logo=discord&logoColor=white" alt="Discord" width="140"> 
   </a> 
 </p>
 
 <p align="center">
  The Roblox client meant for MacOS, running on Linux through <a href="https://www.darlinghq.org">Darling</a>, a compatability layer for using MacOS applications on Linux.
  
  improved by aubree.wtf and CiderHQ maintainers. with patches and more, Mac O' Blox, now Cider was originally created by narezy. Credits of the base to Cider go to narezy.
</p>

<h1 align="center">
A.I. Disclaimer, do not use Cider if against the usage of A.I.
</h1>

###   Cider uses **Generative A.I.** for the maintaining and addition of features for Cider. Please do NOT complain in the CiderHQ [Discord server](https://discord.gg/jCjHYYNq48) if you are aginst the usage of Generative A.I.

<h1 align="center">
  Description
</h1>

Full graphics* with antialiasing, sound, camera and mouse lock, a session that
survives restarts, and a small launcher with fast flags. Roblox Studio too, in
its Windows version through Wine. English and Russian. Cider is under the GPL v3 license. Do not make Cider proprietary, nor may any derivatives be closed source.
Any derivatives must be also under the GPL v3 license, and cannot remove any copyright notices.
* What we mean by "Full graphics" is that the game is running and largely playable. Due to the nature of OpenGL, we cannot provide maxiumum graphics.

<h1 align="center">
  Migration from Mac O' Blox to Cider
</h1>

Cider is the new, and preferred name for Mac O' Blox. The terminal command and native package
name are **`ciderhq`**, the desktop ID is `org.ciderhq.Cider`, and the website
is [ciderhq.org](https://ciderhq.org).

The source installer moves its old `~/.local/share/MacOBlox` checkout to
`~/.local/share/CiderHQ`. The launcher migrates `~/.config/macoblox` and
`~/.cache/macoblox` to `ciderhq`, and its Darling session files from
`Library/MacOBlox` to `Library/CiderHQ`. Existing Cider data is never replaced.
Settings, Roblox/Studio files and saved sign-in stay available. Internal shim
filenames and `MACOBLOX_*` environment variables retain their compatibility
names. The GitHub repository is now [CiderHQ-org/Cider](https://github.com/CiderHQ-org/Cider).

## Install

Every **Latest** version is a source release. Use the installer below to install or update.

```bash
curl -fsSL https://ciderhq.org/install.sh | bash
```

The installer welcomes you and explains the packages, destination and setup
steps before you begin. It prepares Darling and adds **Cider** to the
app menu. Open it for a first-time guide that downloads Roblox, prepares its
app environment, and explains how to sign in. Existing Roblox installations
open the launcher directly; **Setup guide** in its menu reopens the guide.

Setup offers **Regular Darling** (the default on first install) or
**CiderHQ's CiderDarling**, our Darling variant with threading, CPU detection
and OpenGL fixes. Updates keep your choice. You can also choose explicitly:

```bash
curl -fsSL https://ciderhq.org/install.sh | bash -s -- --darling ciderdarling
curl -fsSL https://ciderhq.org/install.sh | bash -s -- --darling regular
```

Regular Darling keeps the installed-runtime, distro package and pinned upstream
download paths. [CiderDarling](https://github.com/CiderHQ-org/CiderDarling) installs
into `/opt/ciderdarling/<revision>` using sudo. On Arch-based systems, and on
Debian/Ubuntu-based ones with glibc 2.39 or newer (Ubuntu 24.04, Mint 22), the
installer downloads the pinned revision's prebuilt build from CiderDarling's
CI releases, checks it against a pinned SHA-256 and installs the libraries it
uses, in minutes. Elsewhere, when the build does not suit the system's
libraries, or with `--from-source`, it compiles the pinned source instead; the
source build asks for confirmation even with `--yes`. Arch users can also
install `ciderdarling-bin` from the AUR. Its x86_64 build includes OpenGL and
Metal API stubs.
Compilation uses the available CPU threads, capped by memory headroom;
`DARLING_BUILD_JOBS=8` overrides the automatic job count.

CiderDarling uses `~/.ciderdarling` by default; regular Darling uses `~/.darling`.
Sign in again the first time you use the separate prefix. Switching keeps both
prefixes and runtime installations available. An explicit `DPREFIX` overrides
the prefix. The installer saves the client, matching runtime root and prefix
in `~/.config/ciderhq/runtime.json` (or your XDG config directory) after setup
succeeds. Restart the launcher after switching. Flatpak continues to use its
bundled runtime.

Installed runtimes can also be switched in **Settings → Environment → Darling**.
Choose **DarlingHQ's Darling** or **CiderHQ's CiderDarling**, then press
**Apply and restart Cider**. Close Roblox and wait for launcher operations to
finish first. The refresh button detects runtimes installed while Cider was
open. If CiderDarling is missing, select it and click **Install in terminal**.
The separate terminal runs the pinned runtime installer, shows build progress
and handles confirmation and sudo prompts. It stays open when the build
finishes; Cider refreshes the choices and you can apply the switch when ready.
Installing this way keeps the current runtime selection and launcher files.
Custom prefixes are remembered for both choices. Flatpak keeps this selector
read-only because its runtime is bundled.

Cider 0.23 checks for CiderDarling updates automatically at startup and hourly.
When a complete CI binary release is ready, **Settings → CiderDarling** offers
**Update in terminal**. The refresh button checks immediately, and automatic
checks can be disabled in that page. Downloads verify the published checksums;
the update keeps the prefix and sign-in, and applies after restarting Cider.
Each runtime release appears through this update feed without a separate
Cider release or manual announcement.

Cider uses the complete published runtime release, with the revision pinned
in its installer (`CIDER_DARLING_REVISION` in `install.sh`) as the fallback
when no update feed is available. The new version is saved for CiderDarling
with its prefix unchanged, and the active runtime switches to it only if
CiderDarling was already active. An
installation interrupted during `sudo` is detected and removed after asking
(`--replace-incomplete-runtime` skips the question). Build trees are deleted
after a successful build; the build log stays in `~/.cache/ciderhq/installer/`.

While CiderDarling is installed, **Settings → CiderDarling** (also the
*CiderDarling Settings* app menu entry, or `ciderhq --ciderdarling-settings`)
collects its options: renderer and graphics card (shared with Environment →
Game), watchdog thread kicks (`MACOBLOX_KICK=1`, off by default), a runtime trace
(`CIDER_TRACE_FILE`, a private file in the logs folder), a verbose
darlingserver log (`DSERVER_LOG_LEVEL=debug`), diagnostics and the prefix
folder. These apply only while CiderDarling is the active runtime.

Run the same command again to update or uninstall. Updates save local source
changes in `~/.local/share/CiderHQ-backups` (or your XDG data directory) and
keep settings and sign-in. Without a terminal, or for scripts, the choices
are options too:

```bash
curl -fsSL https://ciderhq.org/install.sh | bash -s -- --uninstall
```

Arch package recipes for the stable `ciderhq` release and `ciderhq-git` are
in [packaging/aur](packaging/aur/README.md). They build the shim at package
creation and install system menu entries. The stable recipe is generated from a checksum-verified source archive.
The new package names still need submission to the AUR.

[Native distro packaging](packaging/README.md) also includes a Debian/Ubuntu
overlay and a Fedora/openSUSE RPM spec, with pinned source preparation and
build instructions. These recipes require a full Darling package and have
not yet been built in their target distros.

Installer and launcher updates exclude `website/` and its hosting configuration.
Maintainers publishing the website should run `bash website/build.sh` after
editing `install.sh` to refresh its copy at `website/dist/install.sh`.

Uninstalling keeps both runtime installations and their prefixes, which hold
your Roblox sign-in; `--purge` (or **Uninstall everything** in the menu) deletes
only the selected prefix.

Works on Arch and its relatives (CachyOS, EndeavourOS, Manjaro), Ubuntu 24.04+,
Debian 13, Linux Mint 22 and Fedora with Darling built from source.

<details>
<summary>Install by hand</summary>

**1. Darling and the tools**

Arch, CachyOS, EndeavourOS, Manjaro:

```bash
paru -S darling-bin
sudo pacman -S clang lld unzip pipewire-audio python-gobject gtk4 libadwaita webkitgtk-6.0
```

Debian, Ubuntu, Mint: download `debs_20260608.zip` from the
[Darling release v0.1.20260608](https://github.com/darlinghq/darling/releases/tag/v0.1.20260608)
(the one Cider is tested with), then:

```bash
unzip debs_*.zip -d darling-debs
sudo apt install ./darling-debs/*/*.deb
sudo apt install clang lld unzip pipewire-bin pulseaudio-utils python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 gir1.2-webkit-6.0
```

Fedora and others: build Darling with the
[official guide](https://docs.darlinghq.org/build-instructions.html), then:

```bash
sudo dnf install clang lld unzip pipewire-utils python3-gobject gtk4 libadwaita webkitgtk6.0
```

**2. Cider**

```bash
git clone --filter=blob:none --no-checkout --depth 1 --single-branch --branch main \
  https://github.com/CiderHQ-org/Cider ~/.local/share/CiderHQ
git -C ~/.local/share/CiderHQ sparse-checkout set --no-cone --stdin <<'PATTERNS'
/*
!/website/
!/.github/
!/vercel.json
!/.vercel/
!/.vercelignore
PATTERNS
git -C ~/.local/share/CiderHQ reset --hard HEAD
~/.local/share/CiderHQ/launcher/install.sh
```
</details>

<h1 align="center">
  Frequently Asked Questions
</h1>

<details>
<summary>Hey, this sounds like Gracejuice!</summary>

Grapejuice and Cider are inherently similar because Grapejuice used Wine to run the Windows version of the Roblox client on Linux, while Cider uses Darling with along with added libraries to use the MacOS version of the Roblox client on Linux. Ergo, Grapejuice and Cider use the same methods, though use different versions of the Roblox client.
</details>

<details>
<summary>Is my account safe?</summary>

You sign in inside the Roblox client itself, the launcher and we at CiderHQ **NEVER** see your password since the
session is stored locally, only on your computer, and not on a server. The cookie is located in
`~/.darling/Users/$USER/Library/CiderHQ`. Do not share that folder, it works
like a fancy keycard to your account. We at CiderHQ will never ask for this folder, and anyone asking for this is a phishing attempt and should be reported, not only to the service you're on, but also ping (Don't DM) anyone with the "Cool and awesome" role in the [Discord](https://discord.gg/jCjHYYNq48) and above, so we can "take care (ban)" them from the server, or make a PSA in the [Discord](https://discord.gg/jCjHYYNq48) to make sure they don't get another persons account.
**Sign out** in the settings to delete it.

Cider is ***NOT*** affiliated nor endorsed by the Roblox Corporation, nor any siblings of Roblox. We are not liable for any suspensions of your account by using Cider. 
</details>

<details>
<summary>Hey.. Something doesn't work! </summary>

In the rare, and *scary* event Roblox does not start, the launcher shows the error with a **Copy**
button. Send it to the [Discord](https://discord.gg/jCjHYYNq48). The last
error is also saved in `~/.cache/ciderhq/last-error.txt`.
You can also send things like bug reports (i.e. Camera issues, and rendering bugs [like artifacting].)
</details>

<details>
<summary>How do I sign in?</summary>

Currently, normally logging in will most likely work, though it relies on your distribution. If logging in like this does not work, continue with the following.

Create or log into your Roblox account through a browser, phone, or S[REDACTED]r., then use the Quick Login feature in the login screen. This will show a code.
Go to your browser or something like S[REDACTED]r and click the gear on the top right of your screen, and type in your code. (i.e. C1D3RHQ)
</details>

<details>
<summary>Images or servers do not load</summary>

Some providers make some of Roblox's addresses inaccessible. In Cider's settings, go to DNS, and choose from the dropdown. Your current options are Google (8.8.8.8), Cloudflare (1.1.1.1), Quad9 (9.9.9.9), and your currrent system-wide DNS. Only Cider uses it, The rest of your computer keeps it's current DNS. 

</details>

<details>
<summary>OpenGL and Vulkan rendering</summary>

**OpenGL** is the default and uses Roblox's own OpenGL renderer with the host
OpenGL driver. Cider hides the Metal device so Roblox selects this path.
Client startup was verified on NVIDIA OpenGL 4.1 using the client's GLSL shader
pack.

In **Settings → Environment → Game → Renderer**, choose **Vulkan (Zink,
experimental)** and restart Roblox. This uses [Mesa Zink](https://docs.mesa3d.org/drivers/zink.html)
to run the client's OpenGL renderer through Vulkan on Linux. It requires Mesa
EGL with Zink and a working hardware Vulkan driver. If Mesa EGL or Zink is
missing, source installations on Arch, Debian/Ubuntu and Fedora install the
required packages after you authorize an administrator prompt. The launcher
prefers **run0**; if unavailable, it uses **pkexec**, then **sudo** with a
graphical password helper, then **sudo** in an available terminal. Cancelling
authentication stops installation and keeps the previous renderer selected.
If no supported prompt is available, install the dependencies manually.
Flatpak graphics libraries come from its runtime; update that runtime if they
are missing.
The launcher checks hardware Vulkan support before starting; if that check
fails, select **OpenGL** again.

Vulkan gameplay is experimental. Client startup
and the MangoHud Vulkan overlay have been tested on an RTX 3060 Ti, with GL
tracing disabled. Heavy gameplay and other GPUs still need testing. This uses
the macOS client's OpenGL renderer; Metal and native client Vulkan are separate
backends.

With [MangoHud](https://github.com/flightlessmango/MangoHud) installed, enable
**Settings → Environment → Game → MangoHud overlay** and restart Roblox.
It works with both OpenGL and Vulkan (Zink) and is off by default. You can also
start the source launcher with `MANGOHUD=1 ./launcher/ciderhq-launcher`.
The launcher also forwards `MANGOHUD_CONFIG` and `MANGOHUD_CONFIGFILE` to Roblox.
For the Flatpak, install the matching MangoHud extension with
`flatpak install flathub org.freedesktop.Platform.VulkanLayer.MangoHud//26.08`
for the current experimental recipe. The older 0.19 bundle uses `//25.08`.
</details>

<details>
<summary>Select a laptop's dedicated GPU</summary>

If multiple graphics cards are detected, choose one under
**Settings → Environment → Game → Graphics card**, then restart Roblox.
The choice applies to OpenGL and Vulkan (Zink). **Automatic** uses your desktop
or terminal's GPU selection. The selected card needs a working graphics driver
and must be accessible to the launcher, including inside Flatpak.

Choosing between several proprietary NVIDIA cards with OpenGL requires an
X11 provider selection. Use **Automatic** with
`__NV_PRIME_RENDER_OFFLOAD_PROVIDER`, or choose Vulkan (Zink). A laptop with
one NVIDIA card and an integrated GPU can use the menu with either renderer.
</details>

<details>
<summary>Roblox UI is too small on a high DPI monitor</summary>

Set **Settings → Environment → Game → Roblox UI scale** to **200%** for a
4K display, then restart Roblox. The control accepts 100–400% and keeps the
display's rendering resolution. Adjust it to suit your monitor.

For a manual settings edit, `"dpi_scale": 2.0` in
`~/.config/ciderhq/settings.json` selects 200%. The `resolution` key is not
supported. If you previously added `DFFlagDisableDPIScale`, remove it from your
custom fast flags before testing scaling.

Custom scaling requires a supported client input layout. If the launch log
says **UI scale skipped**, the client keeps its original surface scale.
The scaling handoffs cover pointer movement, clicks and scrolling, including
the mouse position used during first-person lock. Camera motion retains its
original relative deltas.
</details>

<details>
<summary>Error 256 or an unknown connection error when joining a server</summary>

Update Cider and restart Roblox. The launcher applies verified RakNet
compatibility patches for Roblox **0.741.0.7411056**, **0.742.0.7421053**,
**0.743.0.7431129** and **0.743.0.7431134**. Roblox updates can relocate these
patches; saved transport flags alone do not prevent the 0.743 connection failure
under Darling.
The launch log includes **RakNet compatibility** and your **CURRENT Roblox version**.
If compatibility says **unsupported client**, share those lines and the full
launch log so that deployment can be inspected. Unsupported executables are
left unchanged.

Cider also monitors Roblox's actual transport selection during each launch.
If Roblox selects a transport other than RakNet, Cider brings the launcher
forward and warns that games might not work or may show Error 256. The warning
offers **View log** and **Check for updates**; if no Cider fix is available yet,
wait for a compatibility patch. It appears once per launch, including when
Discord presence is disabled. An unsupported-client header alone does not
trigger it.

Restoring an older client backup can trigger Roblox's required-update check.
The launcher follows the deployment requested by the client; downgrading is
not a lasting repair. If the compatibility patch is already applied and the
error persists, the full log is needed to diagnose that connection failure.
</details>

<details>
<summary>Roblox closes or fails at launch</summary>

Enable **Settings → Environment → Diagnostics → Crash diagnostics**, then
restart Roblox and collect the entire new launch log. This optional mode
records fatal signal registers and window-startup call boundaries. It replaces
the client's fatal signal handlers for that run; turn it off after collecting
the log. It cannot capture an external kill or every Darling server failure.

For source installations, the same switch is available as:

```bash
MACOBLOX_DIAGNOSTIC_SIGNALS=1 ./launcher/ciderhq-launcher
```

Source checkouts write launch logs to their `logs/` directory; read-only
packages use `~/.local/share/ciderhq/logs/` by default. For Flatpak,
use `~/.var/app/wtf.aubree.MacOBlox/data/macoblox/logs/`. Also collect
`private/var/log/dserver.log` inside the selected Darling prefix: normally
`~/.darling/`, or `~/.var/app/wtf.aubree.MacOBlox/data/darling/` for Flatpak.

The lifecycle record describes the observed state before cleanup. A final
`Broken pipe` can follow cleanup and does not identify the original failure.

**Collect diagnostics** (launcher menu, or `ciderhq --collect-diagnostics`)
writes one archive with the logs, runtime selection and the game's thread
states. Thread stacks need **Allow freeze diagnostics**
(`MACOBLOX_ALLOW_DEBUGGER=1`) turned on before the game starts. Inherited
`DSERVER_LOG_*` variables are ignored unless `CIDER_KEEP_DSERVER_LOG=1` is
set; launch logs are capped at 200 MB in total, and `dserver.log` is rotated
to `dserver.log.old` past 32 MB while Darling is stopped.

If the log says `app_closed_for_update`, Roblox intentionally closed for a
required client update. Use **Update Roblox** in the launcher's recovery dialog.
The launcher follows the client's reported update channel and installs the
exact deployment it requests. **Settings → Roblox → Update channel** shows the
last reported channel. A restricted channel such as `zbeta` can reject anonymous
update checks; the client's own required-update response supplies the download
instead. Changing a launcher configuration value does not change Roblox's
account enrollment.
</details>

<details>
<summary>No sound with older PipeWire</summary>

PipeWire 1.0.5's `pw-cat` cannot play the launcher's raw audio stream.
Cider uses `pacat` through PipeWire's PulseAudio compatibility server on
these versions. On Mint/Ubuntu/Debian, install it with
`sudo apt install pulseaudio-utils`, then restart Roblox. The source installer
includes this package. The launch log records the playback helper and its
errors.
</details>

<details>
<summary>Git LFS credentials during a Darling source build</summary>

Public source downloads do not need a GitHub login. The installer skips
Darling's optional Swift SDK files from its separate LFS service; the current
Roblox client does not link that runtime. Source-built Darling therefore does
not include Swift SDK support. Build dependencies and installing Darling into
`/usr/local` (regular Darling) or `/opt/ciderdarling/<revision>` (CiderDarling)
still use sudo.
</details>

<details>
<summary>Text disappears while typing</summary>

For a source installation, close the launcher and start it with optional
selection diagnostics:

```bash
MACOBLOX_TRACE_TEXT_INPUT=1 ./launcher/ciderhq-launcher
```

The trace records text lengths, selection ranges and composition state in
the launch log, without recording typed content. It is disabled by default.
</details>

<details>
<summary>Wayland</summary>

**Settings → Environment → Game → Window backend** defaults to **X11 / Xwayland**.
Select **Wayland** to use native windows with OpenGL or Vulkan/Zink. Cider 0.24
repairs startup and game-join freezes, aligns mouse clicks with the cursor, and
keeps the outer window size in sync with the game. Backend changes apply on the
next launch. Cider 0.25 also applies fullscreen requests made before the native
window exists, fixing a mismatch where Roblox reported fullscreen while the
window stayed decorated. Initial fullscreen and repeated toggles are checked
under KWin at 100% and 150% scaling.
</details>

<details>
<summary>VR headsets (experimental)</summary>

Roblox's macOS client still contains Roblox's VR mode; Cider supplies the
OpenXR device the Mac build leaves out. Turn on **Settings → Environment → VR →
VR headset (OpenXR)**, start your OpenXR runtime with the headset connected,
then play. Meta Quest headsets work through [WiVRn](https://github.com/WiVRn/WiVRn);
PC headsets through [Monado](https://monado.freedesktop.org/). The OpenXR loader
must be installed (`openxr` on Arch, `libopenxr-loader1` on Debian/Ubuntu).

The VR home menu, games, head tracking, Touch/Index controllers, vibration and
recentering work. **VR render resolution** trades sharpness for smoothness
(70% of the headset's recommendation by default), and the game window can
mirror both eyes. The headset keeps the refresh rate chosen in the runtime.
Tested on a Quest 2 with WiVRn 26.9. Details are in [docs/VR.md](docs/VR.md).
</details>

<details>
<summary>Roblox Studio</summary>

Press **Roblox Studio** in the launcher. The first time it downloads Wine, DXVK
and Studio (about 800 MB) into its own folder, nothing is installed system-wide.
To sign in, Studio opens the Roblox login in your browser; when the browser asks
how to open the `roblox-studio-auth` link, choose **Roblox Studio (Cider)**.
</details>

<details>
<summary>Flatpak (Discontinued)</summary>

The Flatpak brings Darling along and runs it without root (see
[flatpak/darling-noroot.c](flatpak/darling-noroot.c)), so nothing has to be
installed on the system. Version 0.22Patch1 does not include a Flatpak bundle, as the Flatpak is temporarily discontinued to focus on better function on the native version.
The last testing bundle is available in
[release 0.19](https://github.com/CiderHQ-org/Cider/releases/tag/v0.19):

```bash
flatpak install --user MacOBlox-0.19-x86_64.flatpak
```

It keeps its own Darling prefix, so sign in to Roblox again there. Roblox Studio
is not in the Flatpak yet. The current experimental recipe uses Freedesktop
26.08 and bundles GTK 4, libadwaita, Adwaita icons, PyGObject and WebKitGTK.
Vulkan rendering is disabled in the UI libraries; Roblox keeps its renderer
setting. Graphics drivers and Vulkan layer extensions must match 26.08.
Building the UI libraries, especially WebKitGTK, takes considerably longer
than the previous GNOME runtime recipe. To build it yourself:

```bash
flatpak install --user flathub org.flatpak.Builder org.freedesktop.Platform//26.08 org.freedesktop.Sdk//26.08 org.freedesktop.Sdk.Extension.llvm22//26.08
cd Cider/flatpak
flatpak run --env=FLATPAK_USER_DIR=$HOME/.local/share/flatpak --command=flatpak-builder org.flatpak.Builder --user --install --force-clean build-dir org.ciderhq.Cider.yml
```
</details>

<details>
<summary>How does it work?</summary>

Darling runs macOS programs on Linux. Roblox needs a few things Darling does not
have yet, so Cider adds a small library to the game: it connects the mouse,
sound, OpenGL (or Vulkan via Zink) and network to Linux and fixes bugs along the way. Details are in
[docs/NOTES.md](docs/NOTES.md).
</details>

## Credits

Made by [Narezy](https://github.com/narezy). This version is maintained by
[aubree.wtf](https://aubree.wtf) and maintainers at CiderHQ, with stability + performance fixes, and added features.

Cider is licensed under the [GNU GPL v3](LICENSE). Mac O' Blox, the original code it
is based on, was released by Narezy under the MIT License; that notice is kept in
[LICENSES/MIT-MacOBlox.txt](LICENSES/MIT-MacOBlox.txt).

[Darling](https://www.darlinghq.org) · Tux by Larry Ewing and The GIMP ·
[Comfortaa](https://github.com/alexeiva/comfortaa) font (SIL OFL) ·
[Archivo](https://github.com/Omnibus-Type/Archivo) and
[JetBrains Mono](https://github.com/JetBrains/JetBrainsMono) fonts in the launcher (SIL OFL) ·
icons from [Simple Icons](https://simpleicons.org)

<h2 align="center">
  Cider© 2026 is under CiderHQ via the GNU General Public License, and Roblox® is a registered trademarked of Roblox Corporation. Cider and CiderHQ is not affiliated with, nor endorsed by Roblox Corporation, and any relatives or Roblox Corporation
</h2>
