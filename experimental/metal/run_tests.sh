#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
set -euo pipefail
base=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
cache=${XDG_CACHE_HOME:-$HOME/.cache}/quadra-vulkan/src
darling_source=${DARLING_SOURCE:-$cache/darling}
compiler=${HOST_CXX:-c++}
temporary=$(mktemp -d /tmp/quadra-metal-tests-XXXXXX)
trap 'rm -rf -- "$temporary"' EXIT
python3 "$base/test_shader_cache.py"
"$compiler" -std=c++17 -Wall -Wextra -Werror \
  -I "$darling_source/src/external/metal/deps/indium/include" \
  "$base/test_adapter.cpp" "$base/iridium_adapter.cpp" -o "$temporary/adapter-test"
"$temporary/adapter-test"
printf '%s\n' 'Native Metal cache and adapter tests passed'
