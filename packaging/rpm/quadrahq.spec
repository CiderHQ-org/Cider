%bcond_with prebuilt_metal
%global upstream_version 0.37.p4
Name:           quadrahq
Version:        0.37.p4
Release:        1%{?dist}
Summary:        Run the macOS Roblox client on Linux through Darling
License:        GPL-3.0-only AND MIT AND ISC AND OFL-1.1
URL:            https://quadrahq.org
Source0:        https://github.com/QuadraHQ/Quadra/releases/download/v%{upstream_version}/quadrahq-%{upstream_version}-source.tar.gz#/quadrahq-%{upstream_version}.tar.gz
Source1:        quadrahq-install-payload.sh
ExclusiveArch:  x86_64

BuildRequires:  clang
BuildRequires:  lld
BuildRequires:  gcc-c++
BuildRequires:  python3
%if %{without prebuilt_metal}
BuildRequires:  rust >= 1.98
BuildRequires:  cargo >= 1.98
%endif
BuildRequires:  pkgconfig(sdl2)
BuildRequires:  pkgconfig(wayland-client)
BuildRequires:  pkgconfig(wayland-egl)
BuildRequires:  pkgconfig(wayland-cursor)
BuildRequires:  pkgconfig(vulkan)

Provides:       macoblox = %{version}-%{release}
Obsoletes:      macoblox < %{version}
Provides:       ciderhq = %{version}-%{release}
Obsoletes:      ciderhq <= %{version}
Requires:       python3
Requires:       unzip
Requires:       hicolor-icon-theme
Requires:       shared-mime-info
Requires:       desktop-file-utils
Requires:       libEGL.so.1()(64bit)
Requires:       libvulkan.so.1()(64bit)
Requires:       libX11.so.6()(64bit)
Requires:       libXext.so.6()(64bit)
Requires:       libXfixes.so.3()(64bit)
Requires:       libXi.so.6()(64bit)
Requires:       libXcursor.so.1()(64bit)

%if 0%{?suse_version}
Recommends:     llvm
Requires:       python3-gobject
Requires:       python3-gobject-cairo
Requires:       python3-cairo
Requires:       typelib-1_0-Gtk-4_0 >= 4.14
Requires:       typelib-1_0-Adw-1 >= 1.5
Requires:       typelib-1_0-WebKit-6_0
Requires:       pulseaudio-utils
Recommends:     pipewire-tools
%else
Requires:       llvm-libs >= 15
Requires:       python3-gobject
Requires:       python3-cairo
Requires:       gtk4 >= 4.14
Requires:       libadwaita >= 1.5
Requires:       webkitgtk6.0
Requires:       pulseaudio-utils
Recommends:     pipewire-utils
%endif
Suggests:       darling, mangohud

# Keep private Mach-O frameworks out of ELF dependency generation and strip
# only the Linux helper. Compile the private Python modules explicitly;
# icon/MIME cache handling comes from the package manager.
%global __requires_exclude_from ^%{_libdir}/quadrahq/shim/(.*\\.framework/.*|.*\\.dylib)$
%global __provides_exclude_from ^%{_libdir}/quadrahq/shim/.*$
%global __strip /bin/true
%global debug_package %{nil}

%description
Quadra provides a GTK launcher and compatibility shims for the macOS
Roblox player. It includes desktop shortcuts and Roblox link handlers.
Roblox is downloaded on first setup. A full Darling installation including
GUI frameworks and stubs is required.

%prep
%setup -q -n Quadra-%{upstream_version}

%build
QUADRA_BUILD_DIR="$PWD/native-build" ./build_debug_shim.sh
QUADRA_BUILD_DIR="$PWD/native-build" bash packaging/build-metal.sh
strip --strip-unneeded native-build/libquadra-wayland.so
[ ! -f native-build/libquadra-studio-layer.so ] || strip --strip-unneeded native-build/libquadra-studio-layer.so

%install
bash "%{SOURCE1}" "$PWD" "$PWD/native-build" "%{buildroot}" "%{_libdir}"
python3 -m compileall -q -d "%{_datadir}/quadrahq/launcher" "%{buildroot}%{_datadir}/quadrahq/launcher"

%files
%license %{_datadir}/licenses/quadrahq/
%{_bindir}/quadrahq
%{_libdir}/quadrahq/
%{_datadir}/quadrahq/
%{_datadir}/applications/org.quadrahq.Quadra*.desktop
%{_datadir}/applications/quadrahq-roblox-window.desktop
%{_datadir}/icons/hicolor/*/apps/quadrahq.png
%{_datadir}/mime/packages/org.quadrahq.Quadra.xml

%changelog
* Mon Oct 26 2026 Quadra maintainers <noreply@aubree.wtf> - 0.37.p4-1
- Fix VR controllers never vibrating: Roblox only passes vibration to the controllers while the headset reports a focused session with controllers able to vibrate, and Quadra reported neither. VRService.VRSessionState now follows the headset.

* Sun Oct 25 2026 Quadra maintainers <noreply@aubree.wtf> - 0.37.p3-1
- Fix the middle and extra mouse buttons, which did nothing in game, and keys outside the main block (Insert, Right Alt, Menu, F13 to F20, keypad =, the ISO key), which were sent as the A key on X11 and dropped on native Wayland.

* Sun Oct 25 2026 Quadra maintainers <noreply@aubree.wtf> - 0.37.p2-1
- Fix the Grid and Monochrome looks: a long subtitle no longer squeezes the chosen value of a dropdown to an ellipsis, and disabled buttons are no longer dimmed twice, which left Apply and restart Quadra nearly unreadable.

* Sun Oct 25 2026 Quadra maintainers <noreply@aubree.wtf> - 0.37.p1-1
- Build the Roblox Studio Vulkan layer into the Arch, Debian and Fedora packages: the 0.37 packages lacked it, so Studio's Vulkan renderer reported that its fix was not built. The package recipes now require the Vulkan headers and the release build checks that the layer is packaged.

* Sun Oct 25 2026 Quadra maintainers <noreply@aubree.wtf> - 0.37-1
- Give Roblox Studio a section of its own in the launcher, running on Kombucha (Vinegar's Wine build) with Microsoft's WebView2, so Studio's sign-in, Toolbox and Creator Hub pages work again.
- Choose Studio's renderer (DXVK, DXVK-Sarek, Wine's Direct3D, Vulkan) and graphics card, with GameMode, Discord presence, a sign-in backup, a Studio version or channel to stay on and Studio fast flags.
- Move to QuadraHQ/Quadra and finish the Quadra rename in the code; add a Simplified Chinese translation.

* Sat Oct 24 2026 Quadra maintainers <noreply@aubree.wtf> - 0.36.p1-1
- Fix the camera continuing to turn after releasing the right mouse button when the left button was clicked during a right-button drag.

* Sat Oct 24 2026 Quadra maintainers <noreply@aubree.wtf> - 0.36-1
- Remove the menu freeze after leaving a game by polling the game's idle I/O loops.
- Update Quadra M2VK and add a stall watcher and richer hardware report.

* Fri Oct 23 2026 Quadra maintainers <noreply@aubree.wtf> - 0.35.p2-1
- Recover public Roblox downloads when alternate origins are unavailable.
- Add the website report guide and required diagnostics archive issue form.

* Fri Oct 23 2026 Quadra maintainers <noreply@aubree.wtf> - 0.35.p1-1
- Keep setup and routine updates on the public Roblox release channel.
- Repair Wayland clipboard handling for rich text views and Unicode.
- Refresh integrated GPU budgets and bound resident shader preloads.
- Explain unavailable OverlayFS support before starting Roblox.
- Include NixOS packaging and live Darling status in the launcher.

* Thu Oct 22 2026 Quadra maintainers <noreply@aubree.wtf> - 0.35-1
- Redesign the launcher with Grid, classic GNOME and monochrome appearances.
- Retry blocked Roblox deployments through alternate official download servers.
- Fix Shift Lock centering and interrupted camera capture after switching windows.
- Bound integrated GPU graphics budgets by device memory and shared RAM headroom.

* Thu Oct 22 2026 Quadra maintainers <noreply@aubree.wtf> - 0.34-1
- Release Quadra M2VK and staged shader/resource preloading.

* Wed Oct 21 2026 Quadra maintainers <noreply@aubree.wtf> - 0.33-1
- Integrate Quadra M2VK with bounded shader and resource preloading.
- Improve Metal presentation, pipeline reuse, resource safety and diagnostics.

* Mon Oct 19 2026 Quadra maintainers <noreply@aubree.wtf> - 0.32-1
- Ship the experimental Metal on Vulkan bridge in native packages.
- Fix the Metal layer compositor crash and clear renderer state on switching.

* Mon Oct 19 2026 Quadra maintainers <noreply@aubree.wtf> - 0.31-1
- Release the Quadra / QuadraHQ rebrand with migrated Cider user data.
- Retry public Roblox download HTTP 403s through the Quadra cache.
- Preserve captured right-drag motion with both mouse buttons held.
- Record severe FPS drops for diagnosis; the intermittent FPS issue remains open.

* Sat Oct 17 2026 Quadra maintainers <noreply@aubree.wtf> - 0.30-1
- Rebrand to Quadra / QuadraHQ at quadrahq.org; retain the existing logo.
- Migrate settings, cache and sign-in from Cider and MacOBlox.

* Sat Oct 17 2026 Cider maintainers <noreply@aubree.wtf> - 0.30-1
- Add experimental VR through the host's OpenXR runtime (WiVRn, Monado).
- Fix duplicated typing and the Control key state with native Wayland.

* Thu Oct 15 2026 Cider maintainers <noreply@aubree.wtf> - 0.25-1
- Support Roblox 0.743.0.7431134 with checksum-verified transport compatibility.
- Warn when Roblox selects a transport other than RakNet.
- Apply initial fullscreen requests to native Wayland windows.

* Tue Oct 13 2026 Cider maintainers <noreply@aubree.wtf> - 0.24.p1-1
- Repair Roblox 0.743 Error 256 with verified RakNet compatibility.
- Skip shared-config and legacy dummy connections; retain full checksum validation.
- Keep the cursor visible during right-button camera dragging.

* Tue Oct 13 2026 Cider maintainers <noreply@aubree.wtf> - 0.24-1
- Repair native Wayland startup and game-join freezes, pointer coordinates and window resizing.
- Rename the launcher backend option to Wayland.

* Tue Oct 13 2026 Cider maintainers <noreply@aubree.wtf> - 0.23.patch2-1
- Repair old-runtime sincos recursion and preserve live guests after shell disconnects.
- Add runtime rollback, resumable downloads and local hardware coverage reports.

* Mon Oct 12 2026 Cider maintainers <noreply@aubree.wtf> - 0.23.patch1-1
- Relicense under the GPL v3 and show CiderHQ's Discord presence.
- Find terminals without xdg-terminal-exec for runtime installs.

* Mon Oct 12 2026 Cider maintainers <noreply@aubree.wtf> - 0.23-1
- Add automatic runtime update discovery and the game-join math repair.
- Package the current launcher and diagnostics; let users choose their runtime.

* Mon Oct 12 2026 Cider maintainers <noreply@aubree.wtf> - 0.22Patch1-1
- Add the supplied CiderHQ logo and release installer/runtime updates.
- Refresh launcher, desktop, website and native package branding.

* Sun Oct 11 2026 Cider maintainers <noreply@aubree.wtf> - 0.22-2
- Follow the CiderHQ-org/Cider repository move and renamed release archive.
- Include the old MacOBlox shortcut icons in the payload.

* Sun Oct 11 2026 Cider maintainers <noreply@aubree.wtf> - 0.22-1
- Rebrand and repair multi-monitor input, Roblox 0.742 GLSL and Darling source credentials.

* Wed Oct 07 2026 MacOBlox maintainers <noreply@aubree.wtf> - 0.21patch1-1
- Update scaled input, X11 capture, cursor overlay and Roblox 0.742 transport compatibility.

* Tue Oct 06 2026 MacOBlox maintainers <noreply@aubree.wtf> - 0.21-1
- Initial Fedora and openSUSE package with prebuilt shims and desktop integration.
