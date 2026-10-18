# VR

Roblox's macOS client (checked on 0.743.0.7431134) still contains Roblox's VR
pipeline: VRService, the `RBX::Graphics::DeviceVR` interface, the stereo
render path, the VR home menu and the client's VR emulator
(`DebugDeviceVR`). Only the device that talks to a headset is missing: the
Windows and Quest builds attach an OpenXR device, the Mac build none.

Quadra attaches one. The shim (`vr_device.c`) creates the client's own
`DebugDeviceVR`, swaps in a copy of its vtable whose methods talk to the
host's OpenXR runtime (`vr_xr.c`), and puts it where `DeviceGL` keeps its VR
device. Everything else is Roblox's code.

## Where the device goes

`DeviceGL` has the slot already:

```
DeviceVR *DeviceGL::getVR()   { return vr && vrEnabled ? vr : nullptr; }  // +0x278, +0x280
void      DeviceGL::setVR(bool on) { vrEnabled = on; }
```

`DeviceGL::beginFrame` calls `vr->beginFrame()` and `DeviceGL::present`
calls `vr->endFrame()`; present swaps the game window only when the device's
slot 31 answers true (the emulator answers false). The shim hooks
`DeviceGL::beginFrame` (vtable slot 13, which returns the frame's
`DeviceContext`) to start the OpenXR session on the render thread, with the
game's EGL context current, and attach the device.

Classes are found by RTTI name (`N3RBX8Graphics8DeviceGLE`,
`N3RBX8Graphics13DebugDeviceVRE`, `N3RBX8Graphics13FramebufferGLE`) and every
patched function must contain the instructions the shim expects, so another
client release either matches or leaves VR off.

## DeviceVR

42 virtual methods; the Quest `OpenXrDevice` of the same release names them
in its error strings.

| Slot | Method | Quadra |
|---|---|---|
| 2 | `update` | no-op (state is written when the frame opens) |
| 3 | haptics `(hand, amplitude)` | OpenXR vibration, renewed while active |
| 4 | recenter | re-anchors the base space at the head's position and yaw |
| 5 | `getState` (0x138 bytes) | opens the headset frame on the first render-thread read |
| 9 | `getEyeFramebuffer(eye)` | the emulator's "VR Eye" targets |
| 26 | create resources | emulator, at the headset's eye size |
| 27 / 28 | `beginFrame` / `endFrame` | open (fallback) / copy eyes and `xrEndFrame` |
| 31 | present the window too | true when mirroring |
| 37 / 38 | display rate / request rate | `XR_FB_display_refresh_rate` |

State (`getState`), as the Quest device fills it:

| Offset | Contents |
|---|---|
| 0x00 | head: `u8 valid`, position xyz at +4, quaternion xyzw at +0x10 (meters) |
| 0x20 | floor (VRService `UserCFrame.Floor`), same layout |
| 0x40, 0x60 | left, right hand (grip position, aim orientation) |
| 0x80 | `u8` controllers present (UserInputService Gamepad1 connected) |
| 0x84 | `u32` bit per input slot changed this frame |
| 0x88 | `float` per input slot |
| 0xf8 | eye positions in the head space, `float[2][3]` |
| 0x110 | tangents of the half angles up, down, left, right, `float[2][4]` |
| 0x133 | `u8` active |

Input slots: 0 left stick click, 1/2 left stick x/y, 3 left trigger, 4 left
grip, 9 right stick click, 10/11 right stick, 12 right trigger, 13 right grip,
22 A, 23 B, 24 X, 25 Y, 26 menu. Triggers and grips snap to 0/1 below 0.01
and above 0.99, as on Quest. RenderView's per-frame VR update
(`0x1049b69f2` in 0.743.0.7431134) calls `update()`, reads the state and
turns it into VRService user CFrames and Gamepad1 input.

## Frame timing

Per render frame the state is read first by RenderView's VR update, then by
the camera preparation, then by the renderer. The headset frame opens at the
first read: `xrWaitFrame` paces the game to the headset, then the views are
located and written to the state. Roblox's camera comes from its game step,
which saw the previous frame's head pose, so each image is one frame behind
the state. The shim therefore locates views one display period ahead and
submits them with the next frame's image; the compositor reprojects from the
pose that image was drawn with.

The launch log reports, every 900 frames, the frame rate, late frames and the
time per frame spent waiting for the headset, preparing the camera, drawing,
submitting and presenting the game window.

## Settings and environment

The launcher (`launcher/macoblox/vr.py`) finds the host's active OpenXR runtime
the way the loader would (`XR_RUNTIME_JSON`, `~/.config/openxr/1/`, `/etc/xdg`,
known WiVRn/Monado manifests) and passes it, because the loader runs inside
Darling with the guest's HOME:

| Variable | Meaning |
|---|---|
| `MACOBLOX_VR` | `openxr`, or `openxr-headset` without the window mirror |
| `MACOBLOX_VR_SCALE` | percent of the headset's recommended eye size (default 70) |
| `MACOBLOX_XR_RUNTIME_JSON` | runtime manifest, set as the host's `XR_RUNTIME_JSON` |
| `MACOBLOX_VR_FOLLOW_RATE=1` | let Roblox's display-rate requests (90 Hz) reach the headset |

Development modes: `MACOBLOX_VR=1` attaches the emulator with its own head
(eyes mirrored into the window), `debug` also turns on the client's emulator
mirror, and `-lag0` submits the views a frame opened with.

`tests/vr_xr_host.c` drives `vr_xr.c` natively against the runtime with a test
pattern and prints head, hands and inputs (triggers vibrate, A recenters);
`tests/vr_openxr_abi_test.c` checks the vendored `vr_openxr.h` against the
Khronos headers.
