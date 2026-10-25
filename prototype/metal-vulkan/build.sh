#!/usr/bin/env bash
# Metal on Vulkan: the guest Metal.framework (Darwin, needs clang + lld and
# Darling's runtime sysroot) and the host library (Linux, needs Rust 1.98+).
#   prototype/metal-vulkan/build.sh [framework|host|all]   (default: all)
# Output: $QUADRA_BUILD_DIR/metal (default build/metal).
set -euo pipefail
here=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
project_dir=$(dirname -- "$(dirname -- "$here")")
build_dir=${QUADRA_BUILD_DIR:-$project_dir/build}/metal
what=${1:-all}
mkdir -p "$build_dir"

build_framework() {
  local sysroot=${DARLING_SYSROOT:-}
  if [[ -z $sysroot ]]; then
    sysroot=$(python3 - "$project_dir/launcher" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
from quadra.runtime import resolve_runtime
print(resolve_runtime()['sysroot'])
PY
    )
  fi
  local objc_literal_flag=
  if clang -target x86_64-apple-darwin -fno-objc-constant-literals -x objective-c -fsyntax-only /dev/null 2>/dev/null; then
    objc_literal_flag=-fno-objc-constant-literals
  fi
  local framework=$build_dir/Metal.framework
  mkdir -p "$framework/Versions/A"
  local output
  output=$(mktemp "$framework/Versions/A/.Metal.XXXXXX")
  # shellcheck disable=SC2086
  if ! clang -target x86_64-apple-darwin -fuse-ld=lld \
      -isysroot "$sysroot" -mmacosx-version-min=11.0 \
      -O2 -fno-omit-frame-pointer -dynamiclib -fno-objc-arc -fblocks $objc_literal_flag \
      -Werror=incompatible-function-pointer-types -Wno-objc-root-class -Wno-incomplete-implementation \
      -install_name /System/Library/Frameworks/Metal.framework/Versions/A/Metal \
      -compatibility_version 1.0.0 -current_version 370.64.2 \
      "$here/framework/QMHost.m" "$here/framework/QMDescriptors.m" \
      "$here/framework/QMObjects.m" "$here/framework/QMLayer.m" \
      -lobjc -framework Foundation -framework CoreFoundation \
      -o "$output"; then
    rm -f -- "$output"
    return 1
  fi
  chmod 755 "$output"
  mv -- "$output" "$framework/Versions/A/Metal"
  ln -sfn A "$framework/Versions/Current"
  ln -sfn Versions/Current/Metal "$framework/Metal"
  printf 'Built: %s\n' "$framework"
}

build_host() {
  if ! command -v cargo >/dev/null; then
    printf '%s\n' 'Metal host library skipped: install Rust (cargo) 1.98 or newer.' >&2
    return 1
  fi
  local target=${CARGO_TARGET_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/quadrahq/metal-target}
  CARGO_TARGET_DIR=$target cargo build --locked --release --manifest-path "$here/host/Cargo.toml"
  local output
  output=$(mktemp "$build_dir/.host.XXXXXX")
  # Line tables stay in the cache's copy; the installed one is stripped.
  objcopy --strip-debug "$target/release/libquadra_metal_host.so" "$output"
  chmod 755 "$output"
  mv -- "$output" "$build_dir/libquadra_metal_host.so"
  printf 'Built: %s\n' "$build_dir/libquadra_metal_host.so"
}

case $what in
  framework) build_framework ;;
  host) build_host ;;
  all) build_framework && build_host ;;
  *) printf 'usage: %s [framework|host|all]\n' "$0" >&2; exit 2 ;;
esac
