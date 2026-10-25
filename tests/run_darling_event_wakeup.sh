#!/usr/bin/env bash
# Own prefix and X server only; timeout keeps a broken wait bounded.
set -euo pipefail
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
test_dir=$(mktemp -d /tmp/quadra-event-wakeup.XXXXXX)
test_prefix="$test_dir/prefix"
test_shim=${QUADRA_TEST_SHIM:-$project_dir/build/libQuadraShims.dylib}
cleanup() {
  DPREFIX="$test_prefix" darling shutdown >/dev/null 2>&1 || true
  [[ -z ${xvfb_pid:-} ]] || kill "$xvfb_pid" 2>/dev/null || true
  rm -rf -- "$test_dir" 2>/dev/null || true
}
trap cleanup EXIT
clang -target x86_64-apple-darwin -fuse-ld=lld -isysroot "${DARLING_SYSROOT:-/usr/libexec/darling}" \
  -mmacosx-version-min=11.0 -fobjc-exceptions "$project_dir/tests/darling_event_wakeup_test.m" \
  -framework AppKit -framework Foundation -framework CoreFoundation -o "$test_dir/wakeup-test"
Xvfb -displayfd 3 -screen 0 800x600x24 -ac -nolisten tcp 3>"$test_dir/display" >"$test_dir/xvfb.log" 2>&1 &
xvfb_pid=$!
for ((attempt=0; attempt<100; attempt++)); do
  [[ ! -s "$test_dir/display" ]] || break
  kill -0 "$xvfb_pid" 2>/dev/null || { cat "$test_dir/xvfb.log"; exit 1; }
  sleep 0.05
done
test_display=":$(cat "$test_dir/display")"
for run_mode in default tracking modal; do
for mode in source wake none timer; do
  DISPLAY="$test_display" DPREFIX="$test_prefix" timeout 10s darling shell /bin/bash -c '
    unset WAYLAND_DISPLAY QUADRA_WAYLAND_SOCKET QUADRA_WEB_SOCKET
    export QUADRA_WAYLAND=0 DYLD_FORCE_FLAT_NAMESPACE=1
    export DYLD_INSERT_LIBRARIES="/Volumes/SystemRoot$1"
    exec "/Volumes/SystemRoot$2/wakeup-test" "$3" "$4" "$5"
  ' wakeup-test "$test_shim" "$test_dir" "$mode" "${QUADRA_REQUIRE_EVENT_WAKEUP:-}" "$run_mode" >"$test_dir/$mode-$run_mode.log" 2>&1 || {
    cat "$test_dir/$mode-$run_mode.log"; exit 1;
  }
  tail -n 1 "$test_dir/$mode-$run_mode.log"
done
done
