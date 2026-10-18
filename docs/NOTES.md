# MacOBlox

Roblox Client for macOS (x86_64) on Linux via Darling. As of
2026-09-23: The main menu, login (Quick Login), avatar, and games are working.

## Launch

Launcher: `launcher/install.sh` adds the “Mac O Blox” entry to the Applications menu
and the `macoblox` command. That includes game launching, fast flags, and DNS specifically for Roblox,
Camera sensitivity, client update, diagnostics. The settings are located in
`~/.config/macoblox/settings.json`, logs in `logs/`.

Priorities: Darling runs with a nice value of −4, while darlingserver, the Darling daemons, and
pw-cat inherits the launcher's nice value (+10 if the desktop launches it that way) and
They remain idle while the game uses all the cores. The launcher starts darlingserver with
daemons to -5 and pw-cat to -11, as far as RLIMIT_NICE allows.

## What does the shim (build/libMacOBloxShims.dylib) do?

`build_debug_shim.sh` is built from:

- `libMacOBloxShims.m` — AppKit/GL/input: returns the GL context after
  CALayerContext, macOS-style mouse button numbers, mouse capture for the camera,
  cursors, missing methods for NSEvent/NSTextView/NSButton/CNContactStore,
  a cookie saved to disk (`~/Library/MacOBlox/Cookies.plist` inside
  the Darling prefix), hiding the menu bar, window icon.
- `missing_symbols.c` — functions that Roblox imports but Darling does not.
- `net_trace.c` — reliable UDP reception and a watchdog for frozen RakNet threads.
- `darling_fixes.c` — mutexes without Darling wake-up losses; `usleep` and
  `nanosleep` run directly on Linux (in Darling, each one involves two requests to `darlingserver`).
- `memory_stats.c` — system and game memory (`phys_footprint` for “Mem”).
- `thread_kick.c` — “kick” (SIGURG) for threads stuck waiting for Darling:
  UDP watchdog and long mutex waits; the location of the deadlock is logged.
- `xfixes_raw.c` — hiding the cursor via XFixes over its own X11 socket.
- `dns_override.c` — DNS for Roblox via the launcher’s local proxy.
- `xattr_compat.c`, `exit_compat.c` — from previous stages.

The `MACOBLOX_*` variables (tracing, DNS, sensitivity) are set by
the launcher. `run_debug.sh` is still there for manual debugging.

## Important Note About Darling

Do not delete or modify files in `~/.darling` from the host while
darlingserver is running: the Darling overlay will stop showing new files to the host.
Delete files from within the shell (`darling shell rm ...`) or while the server is stopped.

## History

## Diagnostic Run

From a regular Linux terminal:

```bash
cd Quadra
./run_debug.sh
```

The script compiles the library from `libMacOBloxShims.m` in `build/`, launches
the client from the project folder within an existing Darling prefix, and writes
the output to a separate file in `logs/launch-*.log`. Arguments are passed to the client.
The launch itself requires a running Darling outside the restricted Codex environment.
The launch script has not yet been tested in a running Darling instance.

Build only: `./build_debug_shim.sh`. You can set `DARLING_SYSROOT`.
The old libraries in the root directory and inside `.app` are preserved; the new one is selected
via `DYLD_INSERT_LIBRARIES` and `DYLD_LIBRARY_PATH`.

## Changes 2026-09-21

- Fixed the signature for intercepting `NSWindow initWithContentRect:…`:
  the rectangle is passed by value, and the flag uses the x86_64 BOOL ABI.
  Signature: https://developer.apple.com/documentation/appkit/nswindow/init(contentrect:stylemask:backing:defer:)
- Removed the call to the assumed `what()` method for arbitrary C++ exceptions.
  A discarded object does not necessarily have a virtual function table.
- Separate scripts for building and diagnostic runs have been added.
- The source code and old library are stored in `backups/before-codex-20260921/`.
- Cross-compilation was successful; shell script syntax has been verified.
- The Codex environment launch test stops in Darling before Roblox starts:
  `binary is not setuid root, which is mandatory`. In this environment, the owner
  of the system binary is listed as nobody. This does not prove that the
  installation on the host is broken and is not a reason to change system permissions.

## Changes 2026-09-26

Verified using a test suite under Darling (network, mutexes, waits, sound,
cookies); the old build fails the new tests, while the new one passes them all.

- Timeout waits in Darling return 0 instead of ETIMEDOUT (100 ms
  wait — 0 after 100 ms). Therefore, the wait intervals in `darling_fixes.c`
  never increased (each 50-ms interval — a request to darlingserver), and
  the caller never saw a timeout. Now, the elapsed time is determined by the clock;
  for `pthread_cond_timedwait_relative_np` (which Roblox imports), the time
  of segments already waited out is subtracted; otherwise, waits longer than a second
  would never end.
- kqueue: Roblox closes sockets using `close$NOCANCEL` without EV_DELETE, and
  the socket entry remained: the next socket with the same number received
  events from the old owner (the thread loops, a use-after-free is possible in
  Asio). `close`/`close$NOCANCEL` have been intercepted; entries are checked against the inode.
- The “is there data” check is now done via `poll` instead of `recv(MSG_PEEK)`:
  any receive operation, even a peek, triggers a socket error (ICMP “port unreachable”),
  and after that, `recv(MSG_DONTWAIT)` on a blocking socket would hang indefinitely.
- UDP watchdog ping—only for network sockets (AF_INET/AF_INET6), not for
  local pairs where threads wake each other up; a thread waiting on a mutex
  is checked again before the ping.
- Cookies: `cookiesForURL:` Darling ignores the URL, and `setCookies:forURL:…`
  does nothing. Storage is now managed internally: domain, path, Secure, and expiration
  are checked (login credentials no longer leak to third-party hosts or via HTTP), the new
  value replaces the old one, file writing is atomic, set to 0600 immediately; session
  cookies are in memory only; a foreign domain in Set-Cookie is rejected.
- Event queue: “no event” — type 100, same as in Darling (NSApplication
  compares it to 0x64). Type 13 was a real event at point (0,0).
- Keys: On FocusOut, the table of pressed keys is reset (Alt+Tab with
  W held down no longer leaves it “pressed” for CGEventSourceKeyState).
- Mouse capture: while our warp is running, movement events are not merged; if
  movement from the warp never arrives, centering resumes after 8
  events (previously it was disabled until the end of capture).
- The XFixes stream sleeps on the pipe instead of polling every 5 ms via usleep
  Darling (400 requests to darlingserver per second); it starts at launch.
- getaddrinfo: pause between attempts without blocking, retry only in case of
  temporary errors, waiting via direct Linux sleeps.
- Exception handlers, `makeCurrentContext`, `flushBuffer`: `getenv` and `dlsym` are called once,
  rather than for every `throw` or frame (Lua errors in games are C++ exceptions).
- Shaders: the Mesa fix applies to all shaders (not just the
  first 8192); source code is stored only with `MACOBLOX_TRACE_GL=1`.
- `fast_libc.c`: SSE loops instead of `rep movsb/stosb` where those are slower
  (short copies, 4K aliasing, more L2), fast memchr/strlen/strcmp,
  memset_pattern4/8/16 have been reimplemented.
- `MACOBLOX_*=0` flags now mean “disabled.”

## Changes September 26, 2026, evening: locks without darlingserver

- In Darling, mutexes and conditional variables (psynch) are waited on via
  darlingserver: every capture under load, every wait, and every signal is
  a request to the server (40% of the game’s CPU usage); wake-ups are lost, and conditional
  variables break (the timeout arrives as a wake-up, the counters
  diverging, followed by “psync_cvwait; invalid sequence numbers” and EINVAL on
  every wait—12,874 times in 7 minutes in the server log).
- Now, in `darling_fixes.c`, a busy mutex waits on a Linux futex (the table
  at the mutex’s address, woken by `pthread_mutex_unlock`), while the condition variables
  are separate: a queue of waiters, each with its own futex; a signal wakes exactly one,
  a broadcast wakes exactly the number of waiters, and process signals do not interrupt the wait.
  Conditional variables created by Darling itself (tag ‘COND’/0x434F4E45,
  process-shared) remain its own. “Queue” test: 13.6 s and 18.5 s CPU
  darlingserver → 0.13 s and 0.04 s.
- `PTHREAD_MUTEX_USE_ULOCK=1` (libpthread mode using ulock) is not suitable:
  its condition variables call `__ulock_wait2` (syscall 544), which is not
  present in Darling—the process crashes on the first wait.
- Launcher: “Restart Darling” stops the entire container (launchd and
  daemons—which are not children of darlingserver and remained orphaned with ~250 MB), and upon
  startup, it terminates Darling processes without a running server and waits until
  the previous game closes (otherwise, both would share the same server and crash together).

## Changes 2026-09-27

- New launcher interface (PR #1 by TinyTosha) with refinements: a sidebar
  with a fallback option for libadwaita < 1.9, an FPS limit as a launcher setting
  (the launch script writes FramerateCap to GlobalBasicSettings_13.xml already inside
  Darling before the game starts), and launcher updates are now fast-forward only.
- Thread stacks (`darling_fixes.c`): Darling allocates 512 KB to a thread if the creator
  did not request more; the NVIDIA shader compiler used to overflow such a stack. Now
  the minimum is 8 MB, as in Linux, including threads without attributes and GCD worker threads
  (Darling creates them via `darling_thread_create` from the elfcalls table, which is
  wrapped). GCD worker threads did not reset the stack upon reuse
  (Darling jumps into `_start_wqthread` with the old stack pointer: +140 KB for
  every 250 tasks); the `start_wqthread` pointer in `__common` libsystem_kernel
  has been replaced with a jump that starts at the top of the stack.
- `CGDisplayScreenSize` (`gpu_info.c`): Darling returned the size in pixels as
  millimeters, and 0x0 for an unknown display ID; Roblox divides the width in pixels
  by it without checking (DPI = infinity), which caused
  infinite recursion in `updateSurfaceLuaApp` for a user on Fedora KDE. The size is now set to 96 DPI.
- Embedded Roblox web pages (password login with CAPTCHA, purchases, links):
  `web_bridge.m` replaces WKWebView with placeholders that use a Unix socket
  (`MACOBLOX_WEB_SOCKET`, JSON line-by-line) to the launcher window running
  WebKitGTK 6.0 (`launcher/macoblox/web.py`). Cookies are passed back and forth, so
  the client remains logged in after signing in on the page. The protocol and some of the code are from the
  spidercraft port (Roblox Mac Linux Port), with their permission. The replacement is applied only
  when the launcher is listening on the socket; without WebKitGTK, everything works as before. Site data is stored in
  `~/.config/macoblox/web`; clicking “Log Out” deletes it.
- New application ID `wtf.aubree.MacOBlox` (Flatpak, .desktop, MIME, launcher,
  packages); installers remove the old `xyz.narez.*` files. Version 0.15.
- Microphone for voice chat (`audio_hal.c`): Roblox treats the AUHAL unit as
  WebRTC—enables input on bus 1 (`kAudioOutputUnitProperty_EnableIO`),
  sets the client format (scope 2, element 1, typically 48 kHz mono float32), and
  the input callback (2005), within which `AudioUnitRender` retrieves frames.
  The shim reads float32 from the second FIFO (`MACOBLOX_AUDIO_INPUT_FIFO`, in 10 ms blocks
  into a ring buffer) and calls the callback for each block; `AudioUnitRender` on bus 1 outputs
  frames in the client’s format (float32/int16, interleaved or not). Recording on the host
  continues only as long as the game is listening: at startup, the shim writes the file `<fifo>.request`
  (“frequency, channels”), and the launcher (`HostAudio._keep_recording`, once per tick
  keep_playing) launches `pw-cat --record` (or `pacat`) with the Communication role;
  when stopped, the file is deleted and recording ends. `AVCaptureDevice
  authorizationStatusForMediaType:` and `requestAccessForMediaType:` (not present in Darling)
  return “allowed.” Verified by a test client in Darling: 290 callbacks in
  3 seconds, RMS 0.353 from a tone of 0.5 (0.354 was expected). In Darling, the process with the shim
  crashes after returning from `main` (and in the build before the microphone as well)—a separate
  exit issue that does not affect gameplay.
- Raw mouse motion for the lock (`raw_mouse.c`, "Raw motion" in the shim): the
  camera deltas during mouse lock come from XInput 2 raw events (device
  counts, before pointer acceleration, at the mouse's report rate; warps make
  none) instead of Darling's position-based deltas. Selected on the event
  loop's connection at the first X event after the lock (XISelectEvents from
  the host libXi through elfcalls), one mouse event per raw event merged with
  the last queued one; MotionNotify only keeps the pointer within 100 px of
  its anchor and is not delivered. Falls back to pointer deltas when XI2 is
  missing or no raw event arrives while the pointer moves. Launcher switch
  "Raw mouse input" (MACOBLOX_RAW_MOUSE=0). After spidercraft's RbxRawMotion.
  Verified in Darling against Xvfb: raw deltas equal the xdotool moves; the
  in-game camera is to be checked by hand. MACOBLOX_TRACE_XEVENTS=1 logs the
  first 80 X events reaching postXEvent:.
- Flatpak: “Cannot determine your user name” on startup. `darling` retrieves the
  username via `getpwuid(geteuid())`, and darling-noroot.so returns
  euid 0; there is no root entry in the Flatpak sandbox’s /etc/passwd, and the fallback
  `getlogin()` requires a loginuid, which some display managers do not set
  (darling#715). Now `getpwuid(0)` in darling/darlingserver returns the entry
  for the actual user.

## Changes 2026-10-01: the launcher as a desktop

The launcher's interface is redone after aubree.wtf (`launcher/macoblox/theme.py`
holds the look, `app.py` the new shell; every settings page keeps its widgets):

- Dark monochrome, square corners, no hue: state is filled against hollow,
  brightness, and a text label. Archivo for the interface, JetBrains Mono for
  titles and small facts; both ship in `launcher/macoblox/assets/fonts`
  (SIL OFL, cut down to the weights used) and are registered with Pango at
  start, so nothing is installed on the system.
- A top bar (`macoblox@darling`, the game's state, the time in the running
  game, a clock, the window buttons) over a "desktop": the play window and
  the menu window on the left, the open page in a window on the right
  (console, settings with its three tabs, mods, logs, info). Below 860 px
  the windows stack in one scrolling column, as on the site.
- The console replaces the old status page: each line is a check made just
  now (tools, Roblox, shim, Darling, sound, sign-in window, account), set as
  the unit lines of a boot console.
- The backdrop (`theme.Backdrop`) is a line field in the manner of the
  site's topology wallpaper: points follow a smooth flow field and leave
  marks in a grey bitmap shown as a texture. It draws in for about eight
  seconds (2 ms per 40 ms tick) and then stops; with animations turned off
  in the system it appears finished.
- The log viewer's highlighting is monochrome too (level by brightness and
  weight). The old sidebar and its `show_sidebar` setting are gone.
- For screenshots: `MACOBLOX_PAGE` (play, env, roblox, flags, mods, logs,
  info) and `MACOBLOX_WINDOW_SIZE=WxH`.

## Changes 2026-10-01, evening: a report from another Darling build

A user's game died at start with `-[RBXWindow setTitlebarAppearsTransparent:]:
unrecognized selector`; the log began with "Validation layer requested but
not available" and Mesa's "Failed to create /Volumes for shader cache", and
had `NSApplication got exception: -[MTLDev...` before the crash.

- Roblox prefers Metal and only uses OpenGL when it finds no Metal device.
  On the tested Darling release (and here, NVIDIA) `MTLCreateSystemDefaultDevice`
  returns nil, which is the only reason OpenGL ran. That user's Darling
  returned a device, Roblox started its Metal renderer, and Darling cannot
  carry it. `gpu_info.c` now interposes `MTLCreateSystemDefaultDevice` (nil)
  and `MTLCopyAllDevices` (empty array); `MACOBLOX_METAL=1` keeps Darling's
  answer for the Vulkan work. The interposers are verified to be called; a
  Darling that returns a device could not be reproduced here.
- `setTitlebarAppearsTransparent:`, `setTitleVisibility:` and their getters
  are missing from Darling's NSWindow (also in the tested release; Roblox
  only reaches them on the Metal path). The shim adds them where missing.
- The launch log's second line is now `Darling: <darling --version>`.
- Mesa's shader cache: `MESA_SHADER_CACHE_DIR` carried the guest prefix
  `/Volumes/SystemRoot`, but Mesa is a host library and sees host paths, so
  the cache stayed off on every Mesa system. Tested under Darling with
  llvmpipe: with the prefix "Failed to create /Volumes", no files; with the
  plain host path the cache fills.

## Changes 2026-10-03: input, stalls, graphics, and GNOME interface

- Restored the GNOME/libadwaita sidebar, header bars, preferences and standard
  styling from before the custom desktop layout. The launcher follows the
  system appearance and does not load the custom theme or its fonts.
- Camera capture still hides the hardware pointer for Xwayland's relative
  motion. `cursor_overlay.c` displays the current cursor in an input-transparent
  child window at the lock position, preserving its pixels and hotspot. AppKit
  hide/unhide requests control the visible copy independently. Focus loss
  releases capture and removes the copy. All X requests run on the cursor
  worker; its notification pipe is nonblocking and close-on-exec.
- Input queue, network-watch and GL bookkeeping locks sleep on a Linux futex
  after a short spin, so a preempted owner does not leave competing threads
  spinning indefinitely. The shim builds with optimization and frame pointers.
- Normal shader compilation no longer immediately queries `GL_COMPILE_STATUS`:
  that query forces asynchronous driver compilation to finish. The extra check
  and first-failed-source capture are now enabled only with `MACOBLOX_TRACE_GL=1`.
  NVIDIA gets a persistent host shader-cache path, like Mesa already did.
- Preserve one `glGetError` query after AppKit's first `glDrawArrays` call when
  tracing is off. Without it, isolated startup repeatedly aborts before Roblox
  initializes its renderer, with both optimized and unoptimized shim builds.
  The dump shows a null call from an NVIDIA GL worker followed by Darling's
  signal handler aborting on that native thread. One query lets startup proceed;
  its underlying driver/runtime interaction remains unresolved. It adds no
  repeated driver queries to normal draws. Full GL tracing stays optional.
- Claire's GTX 1060 log (580.178.04) and `5070tiuser.log` (which identifies its
  GPU as RTX 5070, 615.71.09) both contain `GrassVSUnified` failures with C7011,
  implicit int-to-uint conversion. A copied client's isolated startup captured
  the actual failing source: `CB3[(_500 & 63u) * 1 + 0]`. The earlier workaround
  matched only a particular CB12 expression and missed Grass's CB3 indices.
  Generated array indices mix unsigned values with signed `1` and `0`, which
  GLSL 1.50 forbids. `shader_compat.c` removes the redundant ` * 1 + 0` at the
  end of an array index, preserving both signed and unsigned indices without
  casts. All 897 extracted sources from client 0.741.0.7411056 compile with
  this correction on NVIDIA 615.71.09, including the 39 CB12 vertex sources
  that fail unchanged. The second
  report also contains a `HeightmapDebugPS` uniform-parser failure and
  unavailable `DefaultUnifiedPlasticVS`/`DefaultUnifiedFlatOpaqueVS` variants.
  These are separate unresolved errors; shader compilation alone does not
  establish that all box artifacts are fixed.
- Claire's log has repeated five-second timeouts for silver/pulsar/gold pixel
  beacons. The existing exclusion now includes gold and correctly matches
  subdomains, case and a trailing DNS dot. Other Roblox hosts stay unchanged.
- An optional launcher renderer uses host Mesa Zink (OpenGL over Vulkan),
  selecting Mesa's EGL vendor explicitly even on proprietary NVIDIA. A separate
  process probes both compatibility and 4.1 core contexts before starting
  Darling, rejects software Vulkan devices, and reports a useful error instead
  of silently using CPU rendering. Driver settings are passed into the guest
  shell too. Metal remains disabled. See [Mesa's Zink documentation](https://docs.mesa3d.org/drivers/zink.html)
  and [NVIDIA's shader-cache settings](https://http.download.nvidia.com/XFree86/Linux-x86_64/555.58/README/openglenvvariables.html).
- Verified the default native OpenGL path with a copied client, tracing
  disabled and Metal hidden. Roblox reported NVIDIA OpenGL 4.1 on the RTX
  3060 Ti; a temporary file-access probe observed `shaders_glsl3.pack` through
  `fopen` and `open$NOCANCEL`, with no Metal shader-pack access observed during
  startup. This confirms selection of Roblox's own OpenGL renderer. The
  probe, client copy and log remained in `/tmp`.
- Inspected the supplied [Roblox-Mac-Linux-Port](https://github.com/georgenoob1234/Roblox-Mac-Linux-Port/tree/99526af60e0791e0467bc6b2632d9e4fba481104)
  reference. Its locked-cursor layer confirms the need for a visible software
  cursor while the Xwayland pointer is hidden. Its experimental Metal-to-Vulkan
  renderer depends on a separate Darling/Indium build and translator, so it is
  not a drop-in backend for this runtime. No code was copied from it.
- Tested the macOS client with `FFlagDebugGraphicsPreferVulkan=True` and its
  OpenGL preference disabled in a copied `ClientAppSettings.json`. It still
  selected NVIDIA OpenGL. Roblox's [GraphicsMode enum](https://create.roblox.com/docs/reference/engine/enums/GraphicsMode)
  includes Vulkan (6), but this test did not enable that backend. The installed
  bundle contains GLSL and Metal shader packs, and imports OpenGL and Metal.
- The preference-flag test above does not set `RenderSettings.GraphicsMode`.
  Subsequently tested the serialized setting directly: a `RenderSettings`
  item named `Rendering` with `<token name="GraphicsMode">6</token>` in the
  disposable prefix's `~/Library/Roblox/GlobalSettings_13.xml`, followed by a
  full client restart. An injected file-access probe covered `open`,
  `open$NOCANCEL`, `fopen` and the client's imported `fopen$DARWIN_EXTSN`.
  A guest `/bin/cat` positive control read the exact XML successfully; Player's
  startup produced no access to that advanced-settings file and still selected
  NVIDIA OpenGL 4.1. `NoGraphics` (9) also left rendering enabled as a control.
  This saved-setting route therefore did not configure Player's rendering API
  in client 0.741.0.7411056. Roblox's [property documentation](https://create.roblox.com/docs/reference/engine/classes/RenderSettings#GraphicsMode)
  describes Studio rendering settings, PluginSecurity access, a Studio restart
  requirement, and fallback to Automatic for unsupported modes. Device RTTI in
  the tested binary includes GL and Metal types, with no Vulkan device type
  found; this is consistent with the packaged GLSL/Metal assets but is not a
  complete backend audit. Test files and probes stayed in `/tmp`, and each
  settings file was restored after the run.
- Built [metal2vulkan](https://github.com/steelbrain/metal2vulkan/tree/43c46ac)
  in `/tmp` and translated one fragment AIR module extracted from this client's
  Metal pack. It emitted reflection and SPIR-V that passed its Vulkan 1.2
  validator in 0.02 seconds, within a 500 MiB process address-space limit.
  No shader source was added to this repository. This is shader translation
  evidence only; implementing Metal objects, commands, resource bindings,
  synchronization and presentation is separate work, and correct pixels have
  not been verified for this translation.

Validation: full Mach-O shim/framework cross-build; native contention and
pipe-saturation tests; shader and telemetry regressions; launcher graphics
tests; Xvfb cursor tests (pixels, hotspot, input shape, visibility, unlock,
window destruction); visual inspection of the restored GTK pages. The real
NVIDIA shader test passed for all 897 extracted client sources. The host Zink
probe returned RTX 3060 Ti hardware rendering for both context types. In an
isolated Darling prefix, AppKit context creation and dynamically resolved
shader submission/compilation passed with both native NVIDIA OpenGL and Zink.
The copied client also reached its sign-in screen through Zink with GL tracing
off. MangoHud's Vulkan layer was present in the client, its window displayed
ZINK / Vulkan / RTX 3060 Ti, and it recorded frame data for ten seconds. The
roughly 60 FPS sign-in screen is not a heavy-gameplay benchmark; the CSV has
initial outliers and idle presentations, so its summary is not used to claim
an overall performance improvement.
Live gameplay, Xwayland camera capture, intermittent freezes and the reported
box artifacts still need a retest on the affected systems. The supplied
MicroProfiler image shows about 144 FPS at capture time, not a long freeze;
it does not identify the cause of the intermittent pauses.

Run the non-GUI regressions with `bash tests/run.sh`. Optional X11 tests and
their build commands are documented at the top of `tests/cursor_overlay_test.c`
and `tests/shader_driver_test.c`. The optional Darling integration check is
`tests/darling_gl_test.m`.

### Release 0.17 follow-up

- Added a persistent, default-off MangoHud switch in the Game settings.
  Vulkan uses its implicit layer; native OpenGL loads the host EGL overlay
  hooks through Darling's ELF bridge, including context cleanup. Regular
  host preloading did not reach Player, while guest preloading selected
  llvmpipe on the tested NVIDIA system. The direct hook displayed the overlay
  while preserving the NVIDIA renderer. MangoHud configuration variables and
  the existing terminal activation remain supported. See [MangoHud's EGL hooks](https://github.com/flightlessmango/MangoHud/blob/master/src/gl/inject_egl.cpp).
- Removed `-g` from the shim link command after a user reported Clang failing
  to spawn `dsymutil` on Linux. Optimization and frame pointers remain enabled;
  normal builds no longer require Apple's debug-symbol tool.

### Camera-lock report after 0.17

A report from the older 0.16 build contained 8,395 repetitions of
`-[RBXWindow windowHandle]: unrecognized selector` during mouse input.
The camera-lock and custom-cursor hooks mistakenly requested an X11 handle
from the Cocoa window. Resolve its `platformWindow` first, checking both
selectors before using the native handle. This fixes the repeated exceptions
that prevented capture from becoming active. The report has no fatal signal
or crash stack, so it does not establish the cause of the separately reported
crash at the end of the launch.

`tests/darling_cursor_lock_test.m` exercises a real Cocoa/platform window pair
in a disposable Darling prefix. Before the fix its first camera lock raises
the reported exception; after the fix 100 lock/unlock cycles complete with
exit status 0. The test is optional because it needs Darling and a display.

### Vulkan dependency installation

Selecting Vulkan checks for Mesa's EGL vendor manifest and the Zink DRI
library. Missing components trigger package installation on a worker thread,
using fixed package arguments through `run0` and its polkit prompt. If `run0`
is unavailable, use `pkexec`, then `sudo -A` with a graphical askpass helper,
then `sudo` in an available terminal. Configured `SUDO_ASKPASS` helpers and
common KDE, SSH and GNOME helpers are detected; terminal fallbacks include
GNOME Terminal, Konsole, Xfce Terminal, Kitty, Alacritty, Foot and Xterm.
Terminal commands wait for installation to finish. The launcher
does not collect passwords or retry authentication after cancellation or
failure. All commands use argument lists, without a privileged shell. Arch uses
`mesa`/`vulkan-icd-loader`; Debian and Ubuntu use `libegl-mesa0`,
`libgl1-mesa-dri` and `libvulkan1`; Fedora uses `mesa-libEGL`,
`mesa-dri-drivers` and `vulkan-loader`. The launcher rechecks the files after
installation and saves the Vulkan selection only on success. Cancelled
authentication or an unsuccessful install restores the previous selection.
Starting with an existing Vulkan selection also checks these dependencies
before constructing the renderer environment. Packages already installed do
not trigger a prompt. Flatpak graphics libraries belong to its runtime, so
this system package installer does not run inside Flatpak.

Validation: the 19 Python tests and native regression suite pass. The optional
GTK test verifies that cancellation preserves OpenGL and a successful install
saves Vulkan. Konsole and Kitty were also exercised with an unprivileged test
child under Xvfb: both supplied a terminal and waited for completion. Package
installation and authentication are mocked in these tests; no host graphics
packages were changed.

Native Wayland was initially deferred and saved in `work/wayland-prototype`.
The October 3 work below promotes that progress to an explicit experimental
option; X11/Xwayland remains the default.

## Repairs 2026-10-03

The affected installation uses client 0.741.0.7411056, NVIDIA RTX 3060 Ti,
driver 615.71.09, and a Wayland desktop with Xwayland. Findings came from the
latest launch log, the browser crash's system core, source inspection, and
isolated Darling runs. The user's installed login and Darling prefix were
not used as test containers. Authenticated tests used authorized copies in
`/tmp`.

### Input freezes and lost mouse lock

- Raw mouse reports called Darling's synchronous modifier-state query on
  every report. Its unbounded X event drain could also keep processing new
  mouse reports without returning to the game. Cache modifiers from ordered
  key/button events, query on focus activation, accumulate motion deltas, and
  return after at most 128 events or 2 ms. Preserve key/button transitions,
  the last core motion in a batch, and every raw delta.
- Focus loss discarded the game's capture request. Keep requested capture
  separate from the active grab, release it on focus loss, and restore it
  after Darling activates the game window. An explicit unlock while
  unfocused cancels restoration.
- Correct the XInput cookie ABI, require XI 2.1 for raw motion, recover pointer
  input if a previously healthy raw stream stops, and correct right/middle
  drag event types. Scroll sensitivity was applied twice; apply it once.
- The X11 close-message parser read incorrect offsets on LP64 and compared
  an atom through an incompatible function declaration. Use the actual
  `WM_PROTOCOLS`/`WM_DELETE_WINDOW` fields, and only signal game shutdown for
  the matching Roblox window.

### Private Servers/browser crash and graphics

- The actual browser core faults at `O2DataProviderCopyData`, called by
  Darling's `CATexImage2DCGImage` from `CARenderer`. An empty layer supplied a
  null image/data provider. Safely upload a transparent pixel for empty
  layers, check dimensions/stride, release copied image data, and restore GL
  unpack state. Hook the renderer before its private internal uploader; a
  dyld interposer alone cannot intercept that internal call.
- `WebPreferences setPlugInsEnabled:` had the wrong Objective-C argument
  signature. Implement its setter/getter with the actual BOOL ABI.
- Browser bridge connections and writes must not block the game thread.
  Bound queues, timeout pending requests, run timers in modal/tracking modes,
  clear incomplete frames after disconnect, and deliver errors when a send
  fails. Closed pages and invalid requests no longer create stray web views.
- Bind desktop EGL separately on each rendering thread. Copy the terminated
  CGL attribute list before passing it to Darling, propagate actual EGL
  failures, and roll back CGL context/surface state on failed binding.
  Restore the previous context after layer rendering, including a null
  previous context. The initial NVIDIA draw safeguard applies per context.
- GPU strings now have stable storage; X subwindow colormaps use the correct
  screen without leaking. FPS accounting uses successful presentations per
  surface. Expensive GL trace queries stop when the trace limit is reached.
  A successful later swap-interval change invalidates that drawable's cached
  forced-zero interval, so the next frame reapplies the launcher's vsync
  setting. Failed changes preserve both the cache and the EGL error.
- Report a conservative budget for the selected GPU from measured VRAM and
  current use. Unknown memory falls back to 512 MiB. Do not invent 8 GiB or
  report the memory of a different, larger adapter. Thread stack adjustment
  copies caller attributes and preserves caller-provided stacks.
- The Zink preflight now renders, reads back and presents to a real window
  with Darling's screen visual, tests compatibility and core profiles, and
  tests shared objects on a fresh rendering thread. A pbuffer alone missed
  failures in that presentation path.
- `HeightmapDebugPS` failed before GL compilation: the client's literal
  `uniform vec4` scan expects every matching declaration to be a numbered
  CB buffer, but two shader variants also declare ordinary MaterialLUT and
  ColorLUT arrays. The verified GLSL pack repair changes four spaces to tabs,
  preserving GLSL tokens, names, sizes, all pack metadata and source offsets.
  Its RBXS v11 tables, 2,736 descriptors and 897 shared source ranges were
  inspected and validated. A complete SHA-256 manifest permits only the
  known pack and these four changes; unsupported or modified packs remain
  untouched. Repairs are applied atomically on launch/update. A copied-client
  hardware Zink game join passed with zero Heightmap parser errors, compared
  with four errors per unpatched launch. Both repaired source variants also
  compiled after the client's CB-to-std140 rewrite on a real Mesa GL driver.

### Leaving a game

The latest user log shows about 6.6 seconds between starting the menu render
job and binding its workspace; the Replicator itself is destroyed in about
0.47 seconds. All four existing transport patches were already applied, so
the remaining delay cannot be attributed to an unpatched fallback connection.
Replace heuristic binary searches with a complete, versioned SHA-256
manifest and atomic replacement. Unsupported client versions are left
unchanged; unexpected edits cannot result in partial patching.

Earlier authenticated isolated runs returned to a menu in about 18 ms, but
the test probe's recurring four-second timer could mask a missed wakeup.
Those runs do not establish a fix. The user confirms the pause occurs on
every leave.

After removing the probe timer, real native desktop input through Home →
Game Details → Play → Escape/Leave/confirmation reproduced menu binding
delays of 2.392 and 2.442 seconds. The first run had no debugger attachment;
the second had two brief, address-only stack captures. Later frame gaps of
14.7 and 20.8 seconds occurred while the existing WebBridge timer continued
at 50 ticks/second and the main event loop stayed active. No slow NSGL
make-current/update/flush calls or drawable transitions were recorded.
The active menu worker was in DateTime ISO 8601 parsing, locale month-name
formatting, `strftime_l`/`tzset`, and Darling's file-close kqueue bookkeeping;
a network worker was also in that bookkeeping. Its map walk scanned the full
hard file-descriptor limit under a shared lock. In a matched, passive real-UI
comparison, repairing both runtime copies reduced leave-to-menu binding from
2.178 seconds to 15 ms. The transition's 2,103 close callbacks then consumed
7.719 ms, compared with about 1.9 seconds before. A later 12.531-second frame
gap still occurred; the complete leave pause remains under investigation.

The same native desktop run opened the actual Private Servers browser page,
rendered the server list and subscription dialog, and closed the browser
without exiting Roblox. No server was created or purchased. Warm right
mouse motion continued rendering at roughly 286–314 FPS with no frame gap
over 100 ms during the sampled windows.

The final comparison matches the user's audio, MangoHud, 1000 FPS cap,
quality settings and DNS, with private copies of the 2.64 GB persistent
temporary cache and the installed SQLite/OTA cache. The fixture supplies no
launch URL: native desktop input follows the actual experience-details UI
route and joins once. Warm five-second samples average roughly 320 FPS,
with maximum gaps of 5–52 ms. These are functional measurements in the test
scene, not a heavy-gameplay benchmark. The user's cache remains untouched.

The event queue also had a separately reproduced wakeup defect: a background
`[NSApp postEvent:atStart:]` appended an event while the main run loop kept
waiting. A plain `CFRunLoopWakeUp` did not make `runMode:beforeDate:` return
after a handled source. The queue now signals a source in the main loop's
common modes; repeated posts share one pending signal, and main-thread posts
avoid wakeup IPC. Coalesced motion posts use the same notification path.
`tests/run_darling_event_wakeup.sh` measured delivery in 0.54–0.71 ms for
background and timer posts in default, tracking and modal modes. The old
code waited about 801 ms until the fixture's explicit fallback source fired.
Raw/fallback input flood, focus and coalescing regressions still pass.
The real menu pause remains a separate investigation: passive counters have
observed continued event polling and 50 browser timer callbacks per second
during a reproduced frameless interval, with no background event posts.

### Darling kqueue cleanup

The audited libkqueue map stores kqueues by file descriptor. Every ordinary
successful close visits its active kqueues so READ/WRITE watches can be
removed before that descriptor is reused. Its original walker scans the
entire hard descriptor limit, including empty slots. The real client had
five occupied slots, highest descriptor 145, in a map whose inclusive last
descriptor was 1,048,575. Passive measurement during a reproduced leave
counted 1,882 close callbacks taking 1,815.6 ms in the first three reporting
buckets. This identifies a cost in the initial menu-binding delay; the later
frameless phase is measured separately.

`launcher/macoblox/darling_patches.py` prepares app-prefix copies of these
known x86_64 implementations:

| Library | Complete original SHA-256 | Complete repaired SHA-256 |
| --- | --- | --- |
| `usr/lib/libSystem.B.dylib` (244,532 bytes; active client path) | `f2caa3b1f39895d7b5c8853907ed73c9a93030b6460a3183318b5cb95b6caf32` | `1dc68f4c778d557358ea04a5728d5ebecaddc7623fe12f14cd4366ea5251a76b` |
| `usr/lib/system/libsystem_c.dylib` (2,975,108 bytes; separate implementation) | `b1a578ba173b705843e113f99348623f8923a57424ee2aac13c13617677ac6e3` | `a59c162be3a316fcfb25d7a9dcde43c90466ac70c24897642da53b8b1731e692` |

The repaired map appends a zero-initialized scan bound and extends it only
after a successful insertion. Walks visit through the greatest successfully
inserted descriptor, capped by the allocated capacity. The allocation also
includes the last valid descriptor: Darling's NOFILE value is inclusive,
and its lookup/insertion functions already accept that descriptor. Removing
entries retains the historical bound. The existing kqueue callbacks, watch
deletion, reference counts and global/per-kqueue locks remain in use. The
audited map has no free implementation or call; its storage lasts for the
process lifetime.

The complete container hash, x86_64 Mach-O layout, patch symbols, original
instruction hashes, region boundaries and complete repaired hash must all
match. Staging and installation require the library family for the intended
relative path and the exact planned result; a recognized library cannot be
substituted under the other library's filename. The i386 slice and container
metadata are unchanged. Unknown builds,
partial patches, custom prefix overrides and symlinks are preserved. Copies
are written atomically, retain permissions and are checked again before
replacement; the installed Darling source library is read-only.

`darling_sparse_map.c` documents the ISC-licensed reference behavior;
`darling_sparse_map.S` provides the exact position-independent replacement
instructions while preserving the original functions' frames and epilog
offsets for their unwind metadata. Native C/assembly fixtures cover aliases,
deletion, descriptor reuse, callbacks changing later entries, failed CAS,
inclusive boundaries and invalid bounds. Python fixtures validate the Mach-O
planner, generated assembly bytes, idempotent copies, preserved overrides,
failed replacement cleanup and concurrent changes. The standalone Mach-O
fixture `tests/darling_kqueue_test.c` exercises actual shared watches, close
cleanup and descriptor reuse, with a bounded alarm and a close benchmark.
The copied-prefix fixture passed these checks: 100 ordinary open/closes
took 109.482 ms with stock libraries, 110.493 ms with only libc repaired,
and 14.357 ms with the active libSystem implementation also repaired. The
libc-only result confirms why the active library must be repaired. The
fixture's optional final-descriptor case also passed at descriptor
1,048,575. It raises only its own soft NOFILE to the unchanged hard limit,
avoiding Darling's reserved driver descriptor; no limit change is persisted
to the client. The subsequent real-client comparison reduced initial menu
binding from 2.178 seconds to 15 ms and reduced the transition's close
callbacks to 7.719 ms in total. A later frameless interval remains separate;
these measurements do not establish a fix for the complete leave pause.

### Darling ulock error returns

The exported Darling `__ulock_wait` and `__ulock_wake` wrappers mishandle
`ULF_NO_ERRNO`. A standalone native fixture confirmed that a 1 ms timeout
returned `-1` and changed errno to 2108, instead of returning `-60` while
preserving errno. Invalid-operation waits and wakes similarly returned
`-1`/2070 instead of `-22` with unchanged errno. Ordinary error calls and
the changed-value success path behaved correctly.

`darling_fixes.c` now interposes thin adapters from `ulock_compat.h`: when
NO_ERRNO is requested, call the original ordinary-error API with that flag
cleared, convert its `-1` into the negative Darwin errno, then restore the
caller's errno. Other calls pass through directly. The original futex
implementation, timeout units, wake selection and successful return values
are retained. Host mock tests cover forwarding, error conversion, success
and errno preservation; `tests/darling_ulock_test.c` provides the bounded
native regression fixture. The actual Mach-O fixture injected with the
repaired full shim passed all six assertions in a separate prefix without
authentication data; the prefix stopped normally afterward.

The client's TBB wait code requests NO_ERRNO and compares the return with
`-60`. It also rechecks its deadline and generation before every wait, so
this ABI defect alone does not establish the cause of the remaining visible
menu pause. The sampled asset workers were waiting on empty work queues.

### Experimental backends

Settings now offers **Native Wayland (experimental)**, explicitly opt-in.
The Linux helper uses SDL2's Wayland driver, a native EGL window, a bounded
event queue, clipboard/cursor plumbing and requested-versus-active capture.
It is built when SDL2/Wayland development packages are available. Native EGL
window presentation and a shared Zink context passed on this desktop, but
full Roblox presentation, scaling, input methods and compositor compatibility
remain unfinished. The user deferred that work; use the default X11 option
for normal play.

The playable Vulkan option still uses Zink. The macOS client has Metal and
OpenGL backends; turning on a Vulkan preference did not create a native
Vulkan renderer. A separate [Metal-to-Vulkan prototype](../experimental/metal/README.md)
now translates two current client shaders, validates their SPIR-V and
descriptor bindings, builds a Vulkan pipeline on RTX 3060 Ti, draws to an
image and verifies all 256 red pixels by readback. This draw uses Vulkan
without OpenGL/Zink. Reproducible source, content pins and the licensed Indium
patch are included; generated client shader assets are not. Missing Metal
methods, resource/compute cases and window presentation keep it experimental
and prevent using it for normal gameplay.

### Validation

- Full Mach-O shim/framework and Linux Wayland-helper builds succeeded.
- `bash tests/run.sh`: 11 native fixtures and 44 Python tests passed.
- Real Darling/Xvfb input fixtures passed with raw input enabled and disabled:
  a 128-report flood completed in under 0.4 ms, retained all deltas, freed
  every cookie and made no per-report modifier queries. Focus restoration,
  cancellation, silence fallback, right/middle drag and immediate raw motion
  after paired Shift press/release transitions passed.
- Real Darling/Zink layer rendering with an empty parent and populated child
  completed twice without the reproduced null-provider crash.
- Real RTX 3060 Ti Zink window preflight passed for both profiles and shared
  thread contexts. The authenticated game join and UI leave above succeeded.

Intermittent gameplay lag spikes still need a sustained before/after
measurement; the successful functional checks do not establish their complete
removal.

## Earlier investigation notes

We need a recent startup log from a regular terminal. This will help determine where
the client is hanging: the loader, NIB loading, window creation, or rendering.
According to the owner’s recollection, the engine used to start up, but there was no image;
an old log confirming this has not yet been found.

There are still potential issues in the old code: some fatal signals
are suppressed, and the error handler manually parses the context and stack. These areas
require separate verification. Cocoa string constants have been updated to NSString.
`build_shims.py` is an old script that directly modifies the frameworks
in `~/.darling`; the new scripts do not run it automatically.
In `ffmpeg_compat/`, there are links between different ABI versions; compatibility
has not been verified, and a new build does not add this folder to the library path.

Accessing host files via `/Volumes/SystemRoot` is described in the documentation: 
https://docs.darlinghq.org/internals/basics/containerization.html

## Blocker on the host after lifting Codex restrictions

2026-09-21: The kernel was updated at 16:12 to 7.2.6-1-cachyos, but 7.2.0-1-cachyos is running. The module directory for the running kernel is missing; OverlayFS
is not registered in /proc/filesystems, and `modinfo overlay` fails.
This explains the `Cannot mount overlay: No such device` error before Roblox starts.
The update log confirms that the new kernel’s initramfs was successfully generated.
The next step is a normal reboot into the installed kernel, followed by running
`run_debug.sh`. An automatic reboot did not occur.
The script now detects this situation before Darling starts.

## Post-reboot check, September 21, 2026, 4:21–4:29 PM

Confirmed by log: MainMenu.nib loaded, RBXWindow created,
RobloxPlayerAppDelegate assigned, NSApplication run called.
Window/image display and game engine functionality NOT confirmed.

Next blocker: `Failed to initialize crash reporter`, std::runtime_error
from RobloxPlayer at return address 0x105606b21, called from 0x10002f4aa.
This was initially preceded by getxattr/setxattr errors. In xattr_compat.c
an adapter has been added only for org.chromium.crashpad.* and com.googlecode.crashpad.*:
Linux namespace user., access via fd, ENODATA is converted to ENOATTR.
Other names and non-zero position/options remain with Darling.
Data is actually written to the attributes; success is not faked.
After applying the adapter, xattr messages have disappeared, but the reporter initialization still
fails with an unspecified error. The cause of the subsequent crash has not been determined.
RobloxCrashHandler, using the same library, reaches the argument parsing stage
(`--crashCounter must be specified` when running --help); it does not load without the shim.

Logs: logs/touch-types.log (xattr errors), logs/xattr-compat.log (after the fix),
logs/crash-handler-with-shim.log. The launch time and exit code are also recorded
in separate logs/launch-*.log files.

The xattr test for a separate dylib and tests/xattr_compat_probe.c in Darling passed:
missing attribute, write/read, size query, small buffer,
missing path, passing an arbitrary name to the source function.
The original Roblox binary has not been modified. The libraries in the root directory and the .app file have been preserved;
the active build is located in build/.
