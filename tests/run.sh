#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
test_build=$(mktemp -d /tmp/quadra-tests.XXXXXX)
trap 'rm -rf -- "$test_build"' EXIT
clang -O2 -Wall -Wextra -pthread tests/runtime_helpers_test.c worker_wake.c -o "$test_build/runtime"
"$test_build/runtime"
clang -O2 -Wall -Wextra -pthread tests/dns_concurrency_test.c -o "$test_build/dns-concurrency"
"$test_build/dns-concurrency"
clang -O2 -Wall -Wextra tests/thread_stack_test.c -o "$test_build/thread-stack"
"$test_build/thread-stack"
clang -O2 -Wall -Wextra tests/raw_mouse_test.c -o "$test_build/raw-mouse"
"$test_build/raw-mouse"
clang -O2 -Wall -Wextra -pthread tests/cursor_selection_test.c -o "$test_build/cursor-selection"
"$test_build/cursor-selection"
clang -O2 -Wall -Wextra tests/x_modifier_state_test.c -o "$test_build/x-modifier-state"
"$test_build/x-modifier-state"
clang -O2 -Wall -Wextra tests/gpu_info_test.c -o "$test_build/gpu-info"
"$test_build/gpu-info"
clang -std=c11 -O2 -Wall -Wextra -pthread tests/ui_scale_test.c -o "$test_build/ui-scale"
"$test_build/ui-scale"
clang -O2 -Wall -Wextra -pthread tests/graphics_context_test.c graphics_context.c -o "$test_build/graphics-context"
"$test_build/graphics-context"
clang -O2 -Wall -Wextra tests/gl_profile_test.c graphics_context.c -o "$test_build/gl-profile"
"$test_build/gl-profile"
"$test_build/gl-profile" --fps-drop
clang -O2 -Wall -Wextra tests/layer_image_test.c -o "$test_build/layer-image"
"$test_build/layer-image"
clang -O2 -Wall -Wextra tests/shader_compat_test.c shader_compat.c -o "$test_build/shader"
"$test_build/shader"
clang -O2 -Wall -Wextra tests/telemetry_hosts_test.c -o "$test_build/telemetry"
"$test_build/telemetry"
clang -O2 -Wall -Wextra tests/connectx_compat_test.c -o "$test_build/connectx"
"$test_build/connectx"
clang -O2 -Wall -Wextra tests/darling_sparse_map_test.c darling_sparse_map.c darling_sparse_map.S -o "$test_build/sparse-map"
"$test_build/sparse-map"
clang -O2 -Wall -Wextra tests/ulock_compat_test.c -o "$test_build/ulock"
"$test_build/ulock"
clang -O2 -Wall -Wextra tests/math_compat_test.c -lm -o "$test_build/math"
"$test_build/math"
clang -O2 -Wall -Wextra tests/hid_compat_test.c -o "$test_build/hid"
"$test_build/hid"
clang -O2 -Wall -Wextra tests/wayland_coordinates_test.c -o "$test_build/wayland-coordinates"
"$test_build/wayland-coordinates"
clang -O2 -Wall -Wextra tests/drag_cursor_test.c -o "$test_build/drag-cursor"
"$test_build/drag-cursor"
clang -O2 -Wall -Wextra tests/mouse_motion_test.c -o "$test_build/mouse-motion"
"$test_build/mouse-motion"
clang -O2 -Wall -Wextra tests/x_key_codes_test.c -o "$test_build/x-key-codes"
"$test_build/x-key-codes"
if pkg-config --exists openxr egl; then
  clang -O2 -Wall -Wextra tests/vr_openxr_abi_test.c tests/vr_openxr_abi_khronos.c -o "$test_build/vr-openxr-abi"
  "$test_build/vr-openxr-abi"
fi
if pkg-config --exists sdl2 wayland-client wayland-egl wayland-cursor; then
  clang++ -std=c++17 -O2 -Wall -Wextra -pthread tests/wayland_keyboard_test.cpp \
    $(pkg-config --cflags --libs sdl2 wayland-client wayland-egl wayland-cursor) \
    -o "$test_build/wayland-keyboard"
  "$test_build/wayland-keyboard"
  clang++ -std=c++17 -O2 -Wall -Wextra -pthread tests/wayland_pointer_test.cpp \
    $(pkg-config --cflags --libs sdl2 wayland-client wayland-egl wayland-cursor) \
    -o "$test_build/wayland-pointer"
  "$test_build/wayland-pointer"
fi
PYTHONPATH=launcher python3 -m unittest discover -s tests -p '*_test.py'
