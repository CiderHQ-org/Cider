{
  lib,
  callPackage,
  stdenv,
  llvmPackages,
  pkg-config,
  python3,
  SDL2,
  wayland,
  makeWrapper,
  wrapGAppsHook4,
  gobject-introspection,
  gtk4,
  libadwaita,
  webkitgtk_6_0,
  desktop-file-utils,
  buildFHSEnv,
  runtime ? "ciderdarling",
  withStudio ? false,
}:
let
  darling = callPackage ./darling.nix { inherit runtime; };
  metalHost = callPackage ./metal-host.nix { };
  python = python3.withPackages (p: [
    p.pygobject3
    p.pycairo
  ]);
  version = (builtins.fromJSON (builtins.readFile ../release.json)).version;
  payload = stdenv.mkDerivation {
    pname = "quadrahq-payload-${runtime}";
    inherit version;
    src = lib.fileset.toSource {
      root = ../..;
      fileset = lib.fileset.unions [
        (lib.fileset.unions (
          map (name: ../../. + "/${name}") (
            builtins.attrNames (
              lib.filterAttrs (
                name: type: type == "regular" && builtins.match ".*\\.(c|cpp|m|h|S)" name != null
              ) (builtins.readDir ../..)
            )
          )
        ))
        ../../build_debug_shim.sh
        ../../patch_startup_throttle.py
        ../../install.sh
        ../../README.md
        ../../LICENSE
        ../../LICENSES
        (lib.fileset.fileFilter (file: !file.hasExt "pyc") ../../launcher)
        ../../frameworks
        ../../branding
        (lib.fileset.fileFilter (file: !file.hasExt "pyc") ../../packaging)
        ../../flatpak/darling-noroot.c
        ../../flatpak/launchd_pid1.c
        ../../prototype/metal-vulkan
      ];
    };
    nativeBuildInputs = [
      llvmPackages.clang
      llvmPackages.lld
      pkg-config
      python3
      makeWrapper
      wrapGAppsHook4
      gobject-introspection
      desktop-file-utils
    ];
    buildInputs = [
      SDL2
      wayland
      gtk4
      libadwaita
      webkitgtk_6_0
    ];
    dontConfigure = true;
    dontWrapGApps = true;
    # Mach-O files are cross compiled against Darling's SDK. The host clang
    # wrapper injects Linux flags, so use unwrapped clang for Darwin only.
    postPatch = ''
      substituteInPlace build_debug_shim.sh prototype/metal-vulkan/build.sh \
        --replace-fail 'clang -target' '${llvmPackages.clang-unwrapped}/bin/clang -target'
    '';
    buildPhase = ''
      runHook preBuild
      export DARLING_SYSROOT=${darling}/libexec/darling
      export QUADRA_BUILD_DIR="$PWD/native-build"
      bash build_debug_shim.sh
      QUADRA_METAL_HOST_LIBRARY=${metalHost}/lib/libquadra_metal_host.so bash packaging/build-metal.sh
      $CC -shared -fPIC -O2 -DQUADRA_NIX_STORE flatpak/darling-noroot.c -ldl -o native-build/darling-noroot.so
      ${llvmPackages.clang-unwrapped}/bin/clang -target x86_64-apple-darwin -fuse-ld=lld \
        -isysroot "$DARLING_SYSROOT" -mmacosx-version-min=11.0 -dynamiclib -O2 \
        flatpak/launchd_pid1.c -o native-build/launchd_pid1.dylib
      runHook postBuild
    '';
    installPhase = ''
      runHook preInstall
      bash packaging/install-payload.sh "$PWD" "$PWD/native-build" "$PWD/stage" /usr/lib
      mkdir -p "$out"
      cp -a stage/usr/. "$out/"
      install -m755 native-build/darling-noroot.so native-build/launchd_pid1.dylib "$out/lib/quadrahq/"
      ${lib.optionalString (runtime == "ciderdarling") ''
        install -m644 packaging/org.quadrahq.Quadra.CiderDarling.desktop "$out/share/applications/"
      ''}
      runHook postInstall
    '';
    preFixup = ''
      makeWrapper ${python}/bin/python3 "$out/bin/quadrahq" \
        --add-flags "$out/share/quadrahq/launcher/quadrahq-launcher" \
        --set QUADRA_PREBUILT_SHIM "$out/lib/quadrahq/shim" \
        --set QUADRA_BUNDLED_DARLING ${darling} \
        --set QUADRA_NOROOT_LIB "$out/lib/quadrahq/darling-noroot.so" \
        --set QUADRA_PID1_DYLIB "$out/lib/quadrahq/launchd_pid1.dylib" \
        "''${gappsWrapperArgs[@]}"
    '';
    doInstallCheck = true;
    installCheckPhase = ''
      for entry in "$out"/share/applications/*.desktop; do
        desktop-file-validate "$entry"
      done
    '';
    # Linux strip cannot process the guest's Mach-O binaries.
    dontStrip = true;
  };
in
buildFHSEnv {
  pname = "quadrahq";
  inherit version;
  targetPkgs =
    p:
    [
      payload
      python
      p.gtk4
      p.libadwaita
      p.webkitgtk_6_0
      p.gsettings-desktop-schemas
      p.hicolor-icon-theme
      p.SDL2
      p.wayland
      p.libglvnd
      p.mesa
      p.vulkan-loader
      p.llvmPackages.llvm.lib
      p.libx11
      p.libxext
      p.libxfixes
      p.libxi
      p.libxcursor
      p.libxrandr
      p.libxkbfile
      p.cairo
      p.fontconfig
      p.freetype
      p.fuse
      p.giflib
      p.libjpeg8
      p.libpng
      p.libtiff
      p.dbus
      p.ffmpeg_6
      p.pulseaudio
      p.pipewire
      p.unzip
      p.xdg-utils
      p.xdg-user-dirs
      p.shared-mime-info
      p.desktop-file-utils
      p.procps
      p.pciutils
    ]
    ++ lib.optional withStudio p.wineWow64Packages.stable;
  multiArch = false;
  # The guest root contains symlinks such as /Volumes/SystemRoot -> /.
  # Mount it after the FHS merge, which otherwise follows guest symlinks.
  # Darling's no-overlay copy uses lstat, so the root must be a real directory.
  extraBuildCommands = ''
    mkdir -p "$out${if runtime == "ciderdarling" then darling.fhsPrefix else "/usr/libexec/darling"}"
    for program in ${darling}/bin/*; do
      ln -s "$program" "$out/usr/bin/$(basename "$program")"
    done
  '';
  extraBwrapArgs =
    if runtime == "ciderdarling" then
      [
        "--ro-bind ${darling} ${darling.fhsPrefix}"
      ]
    else
      [
        "--ro-bind ${darling}/libexec/darling /usr/libexec/darling"
      ];
  runScript = "${payload}/bin/quadrahq";
  extraInstallCommands = ''
    mkdir -p "$out/share/applications"
    for directory in icons mime licenses; do
      ln -s ${payload}/share/$directory "$out/share/$directory"
    done
    cp ${payload}/share/applications/*.desktop "$out/share/applications/"
    substituteInPlace "$out"/share/applications/*.desktop \
      --replace-fail 'Exec=quadrahq' "Exec=$out/bin/quadrahq"
  '';
  passthru = {
    inherit
      darling
      payload
      metalHost
      runtime
      ;
  };
  meta = {
    description = "Roblox launcher using ${runtime} with rootless NixOS support";
    homepage = "https://quadrahq.org";
    license = lib.licenses.gpl3Only;
    platforms = [ "x86_64-linux" ];
    mainProgram = "quadrahq";
  };
}
