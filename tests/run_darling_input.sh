#!/usr/bin/env bash
# Optional graphical regression in an isolated prefix and disposable X server.
# QUADRA_TEST_FOCUS_ONLY=1 runs the focus/drag regression for both input modes.
set -euo pipefail
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
test_dir=$(mktemp -d /tmp/quadra-input.XXXXXX)
test_prefix="$test_dir/prefix"
test_build=${QUADRA_BUILD_DIR:-$project_dir/build}
sysroot=${DARLING_SYSROOT:-/usr/libexec/darling}
cleanup() {
  DPREFIX="$test_prefix" darling shutdown >/dev/null 2>&1 || true
  [[ -z ${xvfb_pid:-} ]] || kill "$xvfb_pid" 2>/dev/null || true
  # Darling's overlay work directory can contain a root-owned, inaccessible
  # directory after shutdown; that does not change the fixture's exit status.
  rm -rf -- "$test_dir" 2>/dev/null || true
}
trap cleanup EXIT
if [[ -n ${QUADRA_TEST_TEMPLATE:-} ]]; then
  python3 - "$QUADRA_TEST_TEMPLATE" "$test_prefix" <<'PY'
import os, shutil, stat, sys
def ignore(directory, names):
    return [name for name in names if name in ('.init.pid', '.darlingserver.sock')
            or stat.S_ISSOCK(os.lstat(os.path.join(directory, name)).st_mode)]
shutil.copytree(sys.argv[1], sys.argv[2], symlinks=True, ignore=ignore)
PY
fi
clang -target x86_64-apple-darwin -fuse-ld=lld -isysroot "$sysroot" \
  -mmacosx-version-min=11.0 -fobjc-exceptions "$project_dir/tests/darling_input_test.m" \
  -framework AppKit -framework Foundation -framework CoreGraphics -o "$test_dir/input-test"
Xvfb -displayfd 3 -screen 0 800x600x24 -ac -nolisten tcp 3>"$test_dir/display" >"$test_dir/xvfb.log" 2>&1 &
xvfb_pid=$!
for ((attempt=0; attempt<100; attempt++)); do
  [[ ! -s "$test_dir/display" ]] || break
  kill -0 "$xvfb_pid" 2>/dev/null || { cat "$test_dir/xvfb.log"; exit 1; }
  sleep 0.05
done
test_display=":$(cat "$test_dir/display")"
for raw in 0 1; do
  DISPLAY="$test_display" DPREFIX="$test_prefix" timeout 30s darling shell /bin/bash -c '
    unset WAYLAND_DISPLAY QUADRA_WAYLAND_SOCKET
    export QUADRA_WAYLAND=0 QUADRA_RAW_MOUSE="$1"
    export QUADRA_MOUSE_SENSITIVITY=1 QUADRA_SCROLL_SENSITIVITY=1
    export QUADRA_TEST_FOCUS_ONLY="$4"
    export DYLD_FORCE_FLAT_NAMESPACE=1
    export DYLD_INSERT_LIBRARIES="/Volumes/SystemRoot$2/libQuadraShims.dylib"
    exec "/Volumes/SystemRoot$3/input-test"
  ' input-test "$raw" "$test_build" "$test_dir" "${QUADRA_TEST_FOCUS_ONLY:-0}" >"$test_dir/input-$raw.log" 2>&1 || {
    cat "$test_dir/input-$raw.log"
    exit 1
  }
  tail -n 1 "$test_dir/input-$raw.log"
done
