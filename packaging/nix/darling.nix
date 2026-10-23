{
  lib,
  stdenvNoCC,
  fetchurl,
  libarchive,
  python3,
  runtime,
}:
let
  pins = (builtins.fromJSON (builtins.readFile ./runtime-pins.json)).ciderdarling;
  installer = builtins.readFile ../../install.sh;
  regularTag = builtins.head (builtins.match ".*\nDARLING_TAG=([^\n]+)\n.*" installer);
  regularHash = builtins.head (builtins.match ".*\nDARLING_DEBS_SHA256=([0-9a-f]+)\n.*" installer);
  cider = runtime == "ciderdarling";
  fhsPrefix =
    if cider then "/usr/lib64/quadrahq-runtime/${builtins.substring 0 30 pins.revision}" else "/usr";
in
assert lib.assertMsg (builtins.elem runtime [
  "ciderdarling"
  "regular"
]) "Unknown Darling runtime: ${runtime}";
stdenvNoCC.mkDerivation {
  pname = "quadrahq-${runtime}-runtime";
  version = if cider then builtins.substring 0 12 pins.revision else lib.removePrefix "v" regularTag;
  src = fetchurl (
    if cider then
      {
        url = "https://github.com/CiderHQ-org/CiderDarling/releases/download/bin-${
          builtins.substring 0 12 pins.revision
        }/ciderdarling-${pins.revision}-x86_64-ubuntu24.04.tar.xz";
        sha256 = pins.sha256;
      }
    else
      {
        url = "https://github.com/darlinghq/darling/releases/download/${regularTag}/debs_${lib.last (lib.splitString "." regularTag)}.zip";
        sha256 = regularHash;
      }
  );
  nativeBuildInputs = [
    libarchive
    python3
  ];
  dontUnpack = true;
  dontConfigure = true;
  dontBuild = true;
  # Preserve the guest's absolute symlinks and Mach-O binaries. Linux ELF
  # loaders and dlopen dependencies are supplied by buildFHSEnv at runtime.
  dontFixup = true;

  installPhase = ''
    runHook preInstall
    mkdir stage
  ''
  + (
    if cider then
      ''
        tar -xJf "$src" -C stage --strip-components=1
        mkdir -p "$out"
        cp -a stage/bin stage/libexec "$out/"
        chmod -R u+w "$out"
        python3 ${./relocate-runtime.py} "$out" /opt/ciderdarling/${pins.revision} ${fhsPrefix}
        python3 - "$out/libexec/darling/usr/share/ciderdarling/runtime.json" <<'PY'
        import json, sys
        with open(sys.argv[1]) as stream:
            data = json.load(stream)
        if (data.get('source_revision') != '${pins.revision}'
                or data.get('patch_manifest_sha256') != '${pins.patchManifest}'
                or data.get('architecture') != 'x86_64'):
            sys.exit('CiderDarling runtime metadata does not match the Nix pin')
        PY
      ''
    else
      ''
        bsdtar -xf "$src" -C stage
        for deb in stage/debs_*/*.deb; do
          case "$deb" in
            */darling-perl_*|*/darling-python2_*|*/darling-ruby_*|*/darling-pyobjc_*|*/darling-cli-python2-*) continue ;;
          esac
          mkdir deb
          bsdtar -xf "$deb" -C deb 'data.tar.*'
          bsdtar -xf deb/data.tar.* -C stage
          rm -r deb
        done
        mkdir -p "$out/bin"
        cp -a stage/usr/bin/darling stage/usr/bin/darlingserver "$out/bin/"
        cp -a stage/usr/libexec "$out/"
      ''
  )
  + ''
    chmod 0755 "$out/bin/darling" "$out/bin/darlingserver"
    test -f "$out/libexec/darling/usr/lib/libSystem.B.dylib"
    runHook postInstall
  '';

  passthru = { inherit fhsPrefix; };
  meta = {
    description = "Pinned ${runtime} runtime for Quadra's FHS environment";
    homepage =
      if cider then "https://github.com/CiderHQ-org/CiderDarling" else "https://www.darlinghq.org";
    license = lib.licenses.gpl3Only;
    platforms = [ "x86_64-linux" ];
    sourceProvenance = [ lib.sourceTypes.binaryNativeCode ];
  };
}
