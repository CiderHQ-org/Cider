# October 13 runtime and hardware investigations

The supplied logs stay outside Git. This record contains observations and
test scope, not accounts, join links or copies of user logs.

| Report | Evidence | Change or next diagnostic |
| --- | --- | --- |
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

Additional local probes have existing limits: the X11 mouse fixture fails its
motion-coalescing assertion with both the release and repaired shims, and the
private QPainter KWin compositor rejects NVIDIA EGL window allocation with
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
