Quadra 0.37.p4 fixes VR controllers, which never vibrated. Nothing else changes from 0.37.p3.

- **Controller vibration in VR:** Roblox only passes vibration to the controllers while the headset reports a focused session with controllers that can vibrate. Quadra's VR device reported neither, so a game's rumble never reached the controllers. Both are now reported, and Roblox sends the LeftHand and RightHand motors to their controllers and the Large and Small motors to both.
- **`VRService.VRSessionState` follows the headset:** it now reads Idle, Visible, Focused or Stopping as the headset's session changes, instead of staying Idle.
- Everything in the 0.37 to 0.37.p3 notes still applies: Roblox Studio in its own section, the move to QuadraHQ/Quadra, the Simplified Chinese translation, Studio's Vulkan layer in the distro packages, the Grid look fixes and the mouse button and key fixes.

Validation: tried in a live Roblox game on a Quest 2 over WiVRn. The controllers vibrated, and the log shows the session reaching focused before Roblox started vibration; the same setup never vibrated before. The native tests pass. Of the 432 unit tests, one trace-file housekeeping test fails, and it fails the same way on 0.37.p3. Other headsets and OpenXR runtimes were not tried.

Fully close and reopen Quadra after updating. Studio is not in the Flatpak. OpenGL remains the default for the game; VR requires OpenGL or Vulkan/Zink. Native packages include the matching Metal host and framework. Install `.pkg.tar.zst` on Arch derivatives, `.deb` on Ubuntu 24.04+/Debian 13+, or the binary `.rpm` on current Fedora. Darling/CiderDarling downloads remain separate. Source archives, build recipes and `SHA256SUMS` are attached.
