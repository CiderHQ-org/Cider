# Installer runtime selection

The source installer offers Regular Darling and CiderHQ's CiderDarling.
`--darling regular` and `--darling ciderdarling` select explicitly; interactive
setup offers the same choices. First installation defaults to regular Darling.
Updates retain the saved choice, including an existing custom prefix.

The launcher also offers **Settings → Environment → Darling → Darling runtime**
with **DarlingHQ's Darling** and **CiderHQ's CiderDarling**. Selecting a row
previews the choice; **Apply and restart Cider** validates the installed runtime,
saves it atomically and restarts through the normal launcher entry point.
The restart does not replay an original Roblox link. It reloads all client,
sysroot, prefix and session paths together, avoiding mixed runtime state.

Switching is blocked while the launcher owns a Roblox session or is busy, and
also checks for Roblox running externally in the currently selected prefix.
No Darling server is stopped and no runtime or sign-in data is deleted.
Missing runtimes are labelled and cannot be applied. The refresh button
detects runtimes added or removed since Settings was opened. Flatpak presents
the bundled runtime as read-only.

When CiderDarling is missing, selecting it shows **Install in terminal**.
This opens the desktop terminal with the local installer using
`--install-runtime --darling ciderdarling`. That mode installs only the runtime:
it does not update or replace Cider's checkout, build its compatibility shim,
activate a different runtime or touch either guest prefix. Source compilation
still asks for terminal confirmation and installing dependencies uses sudo.
Native package payloads include the same standalone installer.

The launch uses `xdg-terminal-exec` when available, with
[GIO's terminal flag](https://docs.gtk.org/gio/flags.AppInfoCreateFlags.html) as
fallback. GIO arguments use
[quoted command-line values and escaped percent signs](https://docs.gtk.org/gio/type_func.AppInfo.create_from_commandline.html).
The terminal keeps its build output visible until Enter is pressed. Atomic
started/result records track the actual installer shell independently of
terminal clients that detach. Closing the terminal early, failure to open it
or a failed/cancelled install releases the launcher operation and preserves
the current selection. Success refreshes the runtime choices and previews
CiderDarling; **Apply and restart Cider** remains a separate action.

Regular Darling reuses a matching installed client and sysroot, then tries the
existing distro and checksum-verified upstream packages before offering a
source build. CiderDarling always uses CiderHQ's pinned source or a matching
installed version. It never falls back to installing regular Darling.

The current CiderDarling pin is
`a8dae5f8e6daf6ec0245f94a9ba97c0d0cc4aeb7`, with patch manifest SHA-256
`009cf8db2cfc409ceaafb602dac3ee0744e987396eb544e1361bc86910e03e44`.
It installs into `/opt/ciderdarling/<revision>`. Source preparation calls its
versioned bootstrap to fetch pinned public dependencies and apply source
patches. Builds disable i386, Metal implementation and the global install-time
Darling shutdown hook. The OpenGL runtime and Metal API stubs are included.
Both source build paths retain the existing explicit terminal confirmation.
On Arch, if `mesa-git` is installed, dependency setup recognizes it as the
host's Mesa provider and omits official `mesa`, avoiding a package conflict.

Automatic compilation parallelism uses process CPU affinity, available host
memory and cgroup v2 ancestor CPU quotas and memory headroom. It reserves 25%
memory headroom and budgets 1 GiB per compiler. `DARLING_BUILD_JOBS` accepts
`auto` or an explicit count from 1 to 8192. Runtime worker scheduling follows
the runtime's own CPU policy; the build job count does not force idle workers
to spin.

The installer activates a selection by atomically saving
`$XDG_CONFIG_HOME/ciderhq/runtime.json`, defaulting to
`~/.config/ciderhq/runtime.json`, after the launcher shim and desktop setup
succeed. It records an absolute client path, sysroot and prefix. The launcher,
direct shim builds and `run_debug.sh` use these paths rather than independently
choosing a client on PATH and a root under `/usr`.

Regular Darling's default prefix remains `~/.darling`. CiderDarling's default
is `~/.ciderdarling`; this keeps existing upper-layer library overrides and
sign-in files in the regular prefix. `DPREFIX` explicitly overrides this
choice. Switching does not remove either installation or either prefix.
`--purge` affects only the selected prefix. Flatpak ignores the host selection
and keeps its bundled client, root and rootless helper.

The optional `runtimes` map in the same schema-1 configuration remembers each
runtime's client, root and custom prefix. The UI and installer both preserve
these records when switching, including an existing runtime used before any
installer configuration was saved. Installed CiderDarling discovery prefers
the saved version, then other complete versions in `/opt/ciderdarling`.
An incomplete version with missing metadata cannot appear as regular Darling.

Only the existing workqueue trampoline workaround is bypassed automatically:
the launcher supplies `MACOBLOX_NATIVE_WORKQUEUE=1` when the selected runtime's
metadata declares `workqueue_stack_reset_x86_64`. Other compatibility shims
remain active. Changing the selected sysroot or runtime revision invalidates
the launcher's shim build stamp. Restart the launcher after switching.

The Cider shim also repairs `__exp10`/`__exp10f` for existing Darling builds.
Clang can rewrite `pow(10, x)` inside the builtin implementation into an
endless call to that same implementation; a live freeze captured a Roblox
worker spinning there during a game join. The shim uses an indirect power
call to prevent that rewrite, and the CiderDarling build disables builtin
rewriting for both `exp10.c` and `sincos.c`. This shim repair also covers a
copied math library in the prefix. Updating Cider rebuilds the source shim
on the next launch; native packages need a package containing the new shim.

## Automatic runtime releases in Cider 0.23

Successful CiderDarling binary CI runs publish an immutable update manifest on
their `bin-<revision>` release and promote it to
`https://github.com/CiderHQ-org/CiderDarling/releases/download/runtime-updates/stable.json`.
Both distribution archives must be complete. An older build finishing late
cannot replace a newer channel, and builds preceding the exp10 repair are not
promoted. The publisher uses CiderDarling's own workflow token.

The launcher checks at startup and hourly on a worker thread. Settings →
CiderDarling has a manual check and an automatic-check toggle. A valid feed is
cached atomically; outages preserve the last good release. Only descendants
of the installed revision are offered, avoiding downgrades of custom/newer
builds. Flatpak keeps its bundled runtime and does not check host updates.

Clicking **Update in terminal** copies the accepted feed into the private
installer job directory and passes it as `--runtime-release FILE`. The terminal
installs that exact revision even if a newer feed is published during the
download. Archive and manifest SHA-256 checks precede installation. Existing
version directories and both guest prefixes are preserved; updating an active
CiderDarling records the new version, then **Apply and restart Cider** reloads
the client and sysroot together.

The standalone installer checks the same channel for CiderDarling, using its
bundled pin when the service is unavailable. `--pinned-runtime` disables that
check, while an explicit `--runtime-release FILE` installs its exact revision.

## Validation on October 12, 2026

Installer decision tests cover both menu and CLI choices, saved selections,
separate prefixes, atomic configuration, exact revision/manifest checks,
regular-client discovery when a CiderDarling client is earlier on PATH,
declined builds, incomplete-install preservation, build flags and job counts.
Launcher tests cover matching client/root selection, missing selected clients,
Flatpak isolation, explicit prefix overrides, native workqueue metadata and
shim stamp invalidation.

The installer's actual public download/bootstrap path also passed in a fresh
temporary checkout at the exact pinned revision. Its 59 source patches passed
the coverage audit, and a clean configure using the installer's flags generated
the expected revision and manifest metadata.

```bash
PYTHONPATH=launcher python3 -m unittest discover -s tests -p 'installer_runtime_test.py'
PYTHONPATH=launcher python3 -m unittest discover -s tests -p 'runtime_selection_test.py'
GSETTINGS_BACKEND=memory GDK_BACKEND=x11 GSK_RENDERER=cairo xvfb-run -a python3 tests/runtime_settings_ui.py
PYTHONPATH=launcher python3 -m unittest discover -s tests -p 'runtime_install_test.py'
GSETTINGS_BACKEND=memory GDK_BACKEND=x11 QT_QPA_PLATFORM=xcb GSK_RENDERER=cairo dbus-run-session -- xvfb-run -a python3 tests/runtime_install_terminal.py
bash -n install.sh build_debug_shim.sh run_debug.sh
bash website/build.sh
cmp install.sh website/dist/install.sh
```

The real GTK fixture passes switches in both directions, custom-prefix
retention, busy and external-game protection, configuration-write and restart
failures, missing/removed runtime checks, refresh after installation, Flatpak
read-only behavior and restart arguments without replaying a Roblox URI. It
uses temporary configuration, fake runtime clients and mocked restarts; it
does not install or execute Darling or alter the live launcher.

The install-only mode is checked with stubbed runtime installation: launcher
updates, launcher dependency installation and preference activation are not
called. Real pseudo-terminal tests exercise build confirmation input, safe
arguments, completion codes, startup failure and keeping output open. The
separate-terminal fixture exercises the desktop-default launch and GIO
fallback on a private display/session bus, using only a fake installer with
special-character paths. No system software is installed by these tests.

The actual Cider shim and framework replacements built against the staged
CiderDarling root. Real Mach-O threading, condition-variable, ulock, datagram
and kqueue fixtures passed with this shim loaded in a fresh disposable user,
mount and PID namespace. Dispatch reached 16 concurrent workers on the 16
available CPU threads. Real offscreen and windowed AppKit/OpenGL lifecycle
fixtures passed with the same shim on the RTX 3060 Ti. The staged runtime
revision was `3ac1f6818e76c4b0ac0e317af435f412070297fc`; its runtime code and
patch manifest match the installer's later documentation/merge revision.

The broader existing suite is not green: Python discovery reports 3 failures
and 9 errors, and the native suite stops at its GPU physical-size assertion.
The same failures reproduce on unchanged Cider. This integration does not
change those tests or their unrelated behavior. No live installation,
existing prefix or Roblox sign-in was used for validation; gameplay and
other GPUs still require testing.
