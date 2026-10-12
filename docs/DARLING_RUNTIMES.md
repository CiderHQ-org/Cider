# Installer runtime selection

The source installer offers Regular Darling and CiderHQ's CiderDarling.
`--darling regular` and `--darling ciderdarling` select explicitly; interactive
setup offers the same choices. First installation defaults to regular Darling.
Updates retain the saved choice, including an existing custom prefix.

Regular Darling reuses a matching installed client and sysroot, then tries the
existing distro and checksum-verified upstream packages before offering a
source build. CiderDarling always uses CiderHQ's pinned source or a matching
installed version. It never falls back to installing regular Darling.

The current CiderDarling pin is
`4312cd798e1ec1967b13b1a8adcedd5efcba8a10`, with patch manifest SHA-256
`2be76e8bf45ab7fc06e937ea3876049d6e46ffaab35ebc6d255f8f3f713707a0`.
It installs into `/opt/ciderdarling/<revision>`. Source preparation calls its
versioned bootstrap to fetch pinned public dependencies and apply source
patches. Builds disable i386, Metal implementation and the global install-time
Darling shutdown hook. The OpenGL runtime and Metal API stubs are included.
Both source build paths retain the existing explicit terminal confirmation.

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

Only the existing workqueue trampoline workaround is bypassed automatically:
the launcher supplies `MACOBLOX_NATIVE_WORKQUEUE=1` when the selected runtime's
metadata declares `workqueue_stack_reset_x86_64`. Other compatibility shims
remain active. Changing the selected sysroot or runtime revision invalidates
the launcher's shim build stamp. Restart the launcher after switching.

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
bash -n install.sh build_debug_shim.sh run_debug.sh
bash website/build.sh
cmp install.sh website/dist/install.sh
```

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
