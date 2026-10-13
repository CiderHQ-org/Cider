# October 13 runtime and hardware investigations

The supplied logs stay outside Git. This record contains observations and
test scope, not accounts, join links or copies of user logs.

| Report | Evidence | Change or next diagnostic |
| --- | --- | --- |
| SkellyDude, Ryzen 5 4500U/Radeon | Runtime 4312, Zink, no MangoHud; exits during shim/startup initialization with frontend status 1 | The exact 4312 math library contains recursive sincos functions. Cider now interposes compiler-safe float/double and pi wrappers. Retest on that machine is still needed. |
| [Issue 27](https://github.com/CiderHQ-org/Cider/issues/27), Arch startup | Runtime 4312; frontend status 1 while one selected-prefix game process is alive | Preserve and monitor the live guest after frontend disconnect. Add the old-runtime math repair. |
| Claire, GTX 1060 | Runtime a8dae, Zink and MangoHud; one short log and one later frontend exit, without a native crash stack | Only Zink crashes are confirmed. Compare OpenGL without MangoHud, then collect diagnostics with debugger access enabled. Shader-availability warnings alone do not identify the crash. |
| [Issue 25](https://github.com/CiderHQ-org/Cider/issues/25), duplicate typing | One keyDown/keyUp pair is reported, but text may insert twice | Enable **Trace text input**, reproduce, and collect diagnostics. It logs insertion counts and selection ranges, never typed text. Do not discard repeated keystrokes based on timing. |
| [Issue 26](https://github.com/CiderHQ-org/Cider/issues/26), KDE windows | Wayland sizing and X11 closing symptoms; screenshot without a matching lifecycle log | Native Wayland remains experimental. Collect backend, scaling, window/close and lifecycle traces on the affected machine before assigning a cause. |
| Native Wayland startup freeze, local RTX 3060 Ti | Runtime b0fcb070; native OpenGL initially renders, then RBX Worker A remains in `IOHIDManagerSetDeviceMatching` / `io_service_add_notification_bin` | Interpose the public HID manager matching APIs in native Wayland mode. The existing IOService notification interpose misses direct calls within IOKit. SDL supplies keyboard/mouse input; native HID controller discovery remains unsupported. |

The old-library regression runs an exact copy of 4312's libsystem_m in a new
private prefix using a user/mount/PID namespace. The fixture fails without the
shim and passes with the production shim. Host numeric tests cover finite and
non-finite inputs, float/double return ABI, and pi wrappers. This proves the
math repair; it does not prove every supplied crash has the same cause.

The Wayland HID reproducer runs the same manager create/match/open/copy/close
sequence against the exact b0fcb070 archive in a disposable namespace. The
unrepaired shim blocks at the first match and hits an eight-second alarm; the
repaired shim returns with zero devices and successful open/close. The full
AppKit fixture additionally passed native NVIDIA OpenGL and Mesa Zink core/
compatibility contexts, Cocoa event/window identity and pixel readback with
`DISPLAY` unset. Actual gameplay confirmation is separate from these fixtures.

## Hardware coverage

Use **Collect hardware report**, or:

```sh
ciderhq --hardware-report --graphics
ciderhq --hardware-report --gameplay startup=pass --gameplay join=fail
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
