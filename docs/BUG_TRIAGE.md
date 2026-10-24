# Runtime and hardware investigations

The supplied logs stay outside Git. This record contains observations and
test scope, not accounts, join links or copies of user logs.

| Report | Evidence | Change or next diagnostic |
| --- | --- | --- |
| Quadra 0.35, b0fcb070, RTX 3080, native Wayland/OpenGL, no window | Both warmups and the final launch report `Cannot mount overlay: No such device`, followed by the missing mount-namespace file; no Roblox process starts. The reporter's `modprobe` also fails with `Module overlay not found in directory /lib/modules/7.2.9-arch1-1`. | Stop after the first known OverlayFS warmup failure and show actionable module/kernel recovery instructions. A regression preserves ordinary transient startup retries and skips stale failure output when the server is already running. Reboot into the installed kernel first: the missing running-kernel module matches [ArchWiki's post-upgrade troubleshooting](https://wiki.archlinux.org/title/General_troubleshooting#Cannot_use_some_peripherals_after_kernel_upgrade). If it persists, check that the installed kernel supplies OverlayFS. |
| Quadra 0.35, `crash 1.txt`, regular Darling e947f0d5a, RX 6800, OpenGL/X11 | The reporter identifies game joining/loading as the trigger. The client connects through RakNet and initializes game content, then the log ends mid-line with `frontend_detached status=1` followed by `roblox_disappeared`, with the guest exit unknown. An early EGL failure is followed by a valid rendering surface and OpenGL initialization. There is no fatal signal, crash stack or GPU-memory-exhaustion message. | No crash cause is established by this file. Enable **Crash diagnostics** and **Allow freeze diagnostics** before reproducing, then collect the full diagnostics archive for the matching launch. Keep this regular-Darling/OpenGL case separate from the Wayland clipboard and Renoir/Metal cases. Shader-availability warnings do not identify a fatal shader failure. |
| RX 6800 follow-up, `quadra-diagnostics-20261023-200922`, Quadra 0.35 | The same regular-Darling e947f0d5a/OpenGL/X11 configuration joins and loads game assets before disappearing at 00:08:18 UTC. `allow_debugger` is true, but `diagnostic_signals` is false. Collection at 00:09:22 finds no running player, so there are no live thread samples. The CrashHandler log contains startup only; there is no fatal signal, register report or crash stack. The last timestamped `dserver.log` error predates this launch. `nspsam` and its gzip copy contain the same files. | Keep **Allow freeze diagnostics** enabled and turn on **Settings → Environment → Diagnostics → Crash diagnostics** before relaunching Roblox and reproducing. Then collect the matching archive. The missing crash site still prevents a targeted repair; shader warnings and logs from the other installed runtime do not establish its cause. |
| Renoir/Ryzen 5 4500U, Void, Quadra 0.35.p1, hardware report at 2026-10-24 01:52:30 UTC | The pasted report selects CiderDarling b0fcb070 on kernel 6.18.58_1. All five offscreen host OpenGL scenarios pass, including 4× MSAA, one/two CPU affinity and 100 context lifecycle cycles; gameplay and onscreen presentation are untested. The newly supplied `cider-diagnostics-20261012-185630 pt2.tar.gz` has the same SHA-256 as the original October 12 archive and contains Cider 0.23patch1 logs. | The hardware report does not contain this crash's renderer selection, launch log or fault site. Collect the matching 0.35.p1 launch archive with **Crash diagnostics** enabled before reproducing and **Allow freeze diagnostics** retained. Host readback success and this memory snapshot do not establish the gameplay failure's cause or validate the Metal memory mitigation. |
| Quadra 0.35.p1, `message.txt`, GTX 1060 6 GB, CiderDarling b0fcb070, native Wayland/Zink/MangoHud | Startup and the release version check succeed. RakNet connects and all 153 game modules load; rendering continues around 65–76 FPS before the frontend exits with status 1 and no live player at 02:32:30 UTC. Short UDP stalls recover. There is no fatal signal/register report, stack, device-loss message or out-of-memory report. | A crash cause is not established. Collect the matching archive with **Crash diagnostics** and **Allow freeze diagnostics** enabled before launch. Compare with MangoHud disabled, then native OpenGL on the same machine to isolate the overlay and Zink paths. The earlier libdecor, shader and telemetry-DNS warnings do not identify a fatal failure. |
| Public Roblox HTTP 403 fallback follow-up | Public metadata, the current client ZIP and the mirror are reachable from the investigation host. At investigation start, the deployed mirror script predates archive-origin retries. After an initial 403, both launcher and mirror code also stop on an alternate's 404, 429 or server error. | Deployed the tested mirror script and verified its checksum. Continue through unavailable alternate origins to the same upload/channel, retaining initial non-403 errors and authentication restrictions. Mixed HTTP regression tests pass. A real 158,362,150-byte client installation through the public mirror succeeds with forced primary 403 and alternate 503 responses; embedded version validation, old-client backup and partial-download cleanup are verified. |
| Setup blocked by a restricted channel | Setup shared the routine updater's saved-channel and last-log selection. A stale `zbeta` report could redirect an installation to an anonymous request the server rejects. | Setup, startup and ordinary manual checks use the public release. Only explicit required-update recovery may request a rollout deployment. A real GTK fixture verifies all three ordinary paths with saved `zbeta` and a stale required-update log; the validated gated-client recovery remains covered separately. |
| Quadra 0.35 copy/paste, Radeon 860M, Wayland/Zink | The supplied log ends with frontend status 1 after normal game output; the reporter identifies copy and paste as triggers. A fresh-prefix AppKit fixture reproduces an exit at rich-text paste: the general pasteboard exposes a local RTF copy despite advertising only plain text. | The Wayland general pasteboard transfers only supported plain text and handles legacy/UTF-8 string APIs explicitly. The previous shim exits during rich-text paste; the repaired shim passes plain/rich Ctrl+C/X/V, Unicode, replaced/empty clipboard, private pasteboard formats and the existing keyboard/capture suite. In-game confirmation on the reporting machine remains needed. |
| Quadra 0.35, Renoir, 6 GiB, Metal | The new log reports a 706 MiB graphics budget and 52 retained preloaded pipelines, then `radv/amdgpu: Not enough memory for command submission` and `VK_ERROR_DEVICE_LOST`. It does not include that launch's separate memory trace. | Refresh the graphics budget during play, respect cgroup headroom, cap low-memory APUs at 512 MiB and restrict optional resident pipelines' estimated footprint to a quarter of that budget (at most 16 at 512 MiB). Larger APUs scale with RAM. This is a memory-pressure mitigation; the log does not establish a leak, and affected-hardware gameplay validation remains needed. |
| Cider 0.23patch1, October 12 archive | The launch joins a game and ends with network timeouts and UDP scheduling diagnostics. Neither its launch log nor its server logs contain a fatal exception or crash stack. | This older archive does not establish another crash cause. Keep the later 0.35 Renoir device-loss report separate from this Zink session. |
| Quadra 0.34, custom CachyOS `7.3.0-rc6-2-cachyos-rc-custom`, RTX 5070 | The current launch completes library, pipeline and resource preparation, then both Darling warmups and the game frontend exit with `Cannot mount overlay: No such device`. No Roblox process starts. The bundled Roblox and Metal logs are from earlier launches. | OverlayFS is unavailable to this runtime. On the reporting machine, try `sudo modprobe overlay`. If the running kernel's module is missing after an update, reboot into the installed kernel. A custom kernel needs `CONFIG_OVERLAY_FS` enabled (built in or with a matching installed module). The archive does not establish which module/configuration problem caused it; verify on that machine. |
| [Issue 36](https://github.com/CiderHQ-org/Cider/issues/36), setup/update HTTP 403 | The screenshot shows a setup HTTP 403. Both public deployment endpoints work from korona. A real HTTPS test forced primary 403s, then fetched and installed the complete client from the mirror, validating its version and preserving the old client backup. | Retry only the same public channel/upload through the deployed cache. Never proxy sign-in or game traffic. Reject truncated downloads before changing the installed client. |
| [Issue 35](https://github.com/CiderHQ-org/Cider/issues/35), RMB then LMB freezes camera/pointer | The attached log uses native Wayland, runtime b0fcb070 and Zink on Renoir. The AppKit bridge gave left-drag motion priority over captured right-drag motion. | Keep right-drag motion during camera capture, with independent button transitions. Real AppKit in a private compositor verifies RMB+LMB deltas and both release orders. Retest in the reporter's game is still needed. |
| [Issue 34](https://github.com/CiderHQ-org/Cider/issues/34), intermittent 60+ to 15 FPS | Also reproduced intermittently by the maintainer, with no deterministic trigger or slow-frame trace yet. | Automatically log one `[Quadra FPS drop]` marker when a surface that sustained 45+ FPS falls to 20 or lower. No pacing or cap changes. Enable **Frame rate in the log** and collect diagnostics while the drop is happening to distinguish a render/presentation stall from CPU scheduling. This issue is not yet diagnosed or fixed. |
| SkellyDude, Ryzen 5 4500U/Radeon | Runtime 4312, Zink, no MangoHud; exits during shim/startup initialization with frontend status 1 | The exact 4312 math library contains recursive sincos functions. Quadra now interposes compiler-safe float/double and pi wrappers. Retest on that machine is still needed. |
| [Issue 27](https://github.com/CiderHQ-org/Cider/issues/27), Arch startup | Runtime 4312; frontend status 1 while one selected-prefix game process is alive | Preserve and monitor the live guest after frontend disconnect. Add the old-runtime math repair. |
| Claire, GTX 1060 | Runtime a8dae, Zink and MangoHud; one short log and one later frontend exit, without a native crash stack | Only Zink crashes are confirmed. Compare OpenGL without MangoHud, then collect diagnostics with debugger access enabled. Shader-availability warnings alone do not identify the crash. |
| [Issue 25](https://github.com/CiderHQ-org/Cider/issues/25), duplicate typing; local Wayland chat/search report | The 0.25 AppKit reproducer receives one physical keyDown but inserts twice: SDL_TEXTINPUT inserts inside the pump, then the queued keyDown reaches Darling's text interpreter. | Queue committed text after the physical event. Preserve the original key event for gameplay and binding lookup, while preventing its interpreter fallback from inserting text again. Genuine repeated commits remain separate. X11 reports still need their own capture. |
| Intermittent Wayland Ctrl | Ctrl was mapped to Command, and SDL_GetModState could already reflect a later release in the batch. Modifier polling also inferred each side from the shared flag. | Use macOS Control codes/flags and each SDL key event's modifier snapshot. Track explicit left/right transitions, preserve snapshots for mouse events, and queue held-key releases on focus loss. Plain-text Ctrl+A/C/X/V are covered through real AppKit. |
| Claire, 0.25, GTX 1060, Wayland/Zink/MangoHud | The supplied message.txt successfully selects RakNet and joins. It ends at ordinary game messages, without a fatal signal, native stack or lifecycle exit record. Unsupported shader-pack and shader-availability warnings appear earlier. | This file does not identify the crash. Enable **Allow freeze diagnostics**, reproduce, and collect the complete diagnostics archive. Compare OpenGL with MangoHud disabled on the affected machine; do not attribute the crash to shaders or the keyboard repair without a crash site. |
| [Issue 26](https://github.com/CiderHQ-org/Cider/issues/26), KDE windows | Wayland sizing and X11 closing symptoms; screenshot without a matching lifecycle log | Retest with the parent-buffer resize repair, then collect backend, scaling, window/close and lifecycle traces on the affected machine before assigning a cause. |
| Native Wayland startup freeze, local RTX 3060 Ti | Runtime b0fcb070; native OpenGL initially renders, then RBX Worker A remains in `IOHIDManagerSetDeviceMatching` / `io_service_add_notification_bin`. With manager matching repaired, the same worker blocks in `IOServiceGetMatchingServices`; its serialized matching class is `IOHIDDevice`. | Interpose the public HID manager matching APIs and return an empty HID-only service inventory in native Wayland mode. The existing IOService notification interpose misses direct calls within IOKit. SDL supplies keyboard/mouse input; native HID controller discovery remains unsupported. Unrelated service matching still delegates to Darling. |
| Native Wayland game-join freeze | Menu works after HID repair; a game-join worker blocks in `IOServiceGetMatchingService`. The serialized class is `IOPlatformExpertDevice`. | Return the absent-service result only for this unsupported Apple hardware service in native mode, preserving matching-dictionary ownership and delegation for other classes/X11. |
| Native Wayland vertical mouse offset | Clicks land above/below the cursor; `NSEvent.mouseLocation` flips window-local Wayland Y using the whole display height, while `NSWindow.mouseLocationOutsideOfEventStream` uses window height. | Preserve Cocoa's virtual window origin and share a locked numeric pointer/frame snapshot. Screen/window locations and Quartz warp requests now roundtrip through the same logical coordinates. |
| Native Wayland outer window stays fixed, local niri | User confirms game joins and clicks align, but the image resizes inside a fixed border. A no-auth protocol trace configures 954×1032 while the parent retains its initial 320×240 SHM buffer. | Map the parent at SDL's actual initial size, then update its opaque background and commit geometry on compositor size changes. Coalesce updates per SDL event batch; game views continue using EGL subsurfaces. |

The old-library regression runs an exact copy of 4312's libsystem_m in a new
private prefix using a user/mount/PID namespace. The fixture fails without the
shim and passes with the production shim. Host numeric tests cover finite and
non-finite inputs, float/double return ABI, and pi wrappers. This proves the
math repair; it does not prove every supplied crash has the same cause.

The Wayland HID reproducer runs the same manager create/match/open/copy/close
sequence against the exact b0fcb070 archive in a disposable namespace. The
unrepaired shim blocks at the first match and hits an eight-second alarm; the
repaired shim returns with zero devices and successful open/close. The
HID-only service inventory reproducer separately blocks with only the manager
repair, and returns success with an empty iterator after both repairs. Native
ownership/routing checks verify that the consumed service dictionary is released
once, manager matching arguments stay borrowed, and non-HID/X11 queries still
delegate to Darling. The full
AppKit fixture additionally passed native NVIDIA OpenGL and Mesa Zink core/
compatibility contexts, Cocoa event/window identity and pixel readback with
`DISPLAY` unset. The user separately confirmed that the menu remains responsive,
games now finish joining, and clicks align with the cursor on the local machine.

The singular Apple-platform reproducer blocks with the preceding shim and
returns no service after the scoped repair. Coordinate tests cover differing
window/display heights, nonzero/negative window origins, fractional logical
values, and rejection of nonfinite/out-of-window warps. The real AppKit fixture
checks that screen-relative and window-relative mouse locations agree. Physical
global window placement is unavailable to ordinary Wayland clients; Cocoa's
virtual origin is used consistently for conversions within Quadra.

The resize fixture enters and leaves fullscreen on its own window, allowing
the tiling compositor to choose the actual sizes. It checks rendering and
pointer conversions after each transition. The runner additionally examines
the no-auth Wayland protocol trace: a matching parent buffer must actually be
attached and committed; resizing a child alone cannot pass. The preceding shim
fails both parent-buffer checks despite receiving the Cocoa resize events.
The repaired shim passes both checks on native NVIDIA OpenGL and Mesa Zink,
including core/compatibility contexts, pixel readback, and fullscreen/restore.
After restarting Quadra with the repaired shim, the user confirmed that Roblox's
outer border resizes and clicks remain aligned while joining a game on native
Wayland. This confirms the local niri/NVIDIA case; other compositor and GPU
reports still need their own validation.

## Hardware coverage

The optional `tests/run_darling_wayland_keyboard.py` builds a separate helper
with test-only synthetic SDL input and a Mach-O AppKit fixture. It never adds
an injection export to the production helper. In a private KWin compositor and
fresh b0fcb070 prefix, the release shim fails the first character with two
insertions for one physical keyDown; the repaired shim passes single delivery,
held-key repeats, Unicode commits, plain-text Ctrl+A/C/X/V, Ctrl word editing,
Backspace, arrow navigation, both Ctrl keys, focus-loss releases, and a responder change before
text delivery. This checks the compatibility layer; physical in-game testing
on affected machines remains necessary. Rich-text/RTF import is outside this
plain-text fixture's scope. No typed user text or account data is captured.

For #37, the AppKit fixture also checks Shift Lock centering before the host's
capture acknowledgement, preserving that target across focus changes, and
cancelling a camera drag interrupted by switching windows. The X11 runner's
`MACOBLOX_TEST_FOCUS_ONLY=1` mode checks persistent capture, explicit unlock,
interrupted drag and a late background lock request with both raw and fallback
input. These checks pass in disposable b0fcb070 prefixes and private servers.

For #38, Metal's budget tests model the reported Renoir/shared-RAM configuration,
the later 706 MiB case, host/cgroup pressure and the shared shader-preload cap.
The C ABI checks conservative fallback and explicit limits, with exact 1x/4x
render readback on lavapipe and NVIDIA. A real Mach-O fixture verifies that
the same Metal device can observe a reduced budget after its static properties
were cached; the preceding framework fails that assertion. The affected AMD
laptop still needs gameplay validation.

Additional local probes have existing limits: after making the X11 fixture's
initial focus and asynchronous capture explicit, its full flood mode still
fails a fallback extra-button motion assertion. The focused regression above
passes. The private QPainter KWin compositor rejects NVIDIA EGL allocation with
`EGL_BAD_ALLOC` on both builds. Those failures do not validate hardware
rendering. The fullscreen/restore fixture passes at 150% scaling with the
repaired production helper.

Use **Collect hardware report**, or:

```sh
quadrahq --hardware-report --graphics
quadrahq --hardware-report --gameplay startup=pass --gameplay join=fail
```

The GPU matrix tests actual adapter identity, baseline rendering, MSAA,
one/two CPU affinity limits, and 100 resource-lifecycle cycles. Gameplay stages
start as `not_tested`; explicit observations are labeled `user_reported`.
Reports remain local. A failed or unavailable probe is retained in the report.
Use real AMD, Intel, NVIDIA and hybrid-laptop reports to extend coverage; a
passing NVIDIA host probe cannot establish AMD gameplay support.

## Updates and recovery

CiderDarling's binary workflow requires Clang/GCC source regressions and real
Mach-O math/thread/network/AppKit/CGL tests against each exact archived build.
Software Mesa and a private Xvfb display provide repeatable CI graphics.
Checksummed smoke reports must match the archive before stable promotion.

An update preserves the preceding installed version and its selection record.
The rollback button restores that version with the current prefix after
checking its client, matching sysroot and metadata. It does not delete a
runtime or reset the prefix. This is a previous installation, not a promise
that an untested old version works on every machine.
