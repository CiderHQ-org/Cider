#!/usr/bin/env bash
# Build the guest framework and either compile the pinned host crate or use
# the release workflow's Ubuntu 24.04 artifact (same source revision).
set -euo pipefail
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
build_dir=${MACOBLOX_BUILD_DIR:-$project_dir/build}
bash "$project_dir/prototype/metal-vulkan/build.sh" framework
if [[ -n ${QUADRA_METAL_HOST_LIBRARY:-} ]]; then
  install -m755 -- "$QUADRA_METAL_HOST_LIBRARY" "$build_dir/metal/libquadra_metal_host.so"
else
  bash "$project_dir/prototype/metal-vulkan/build.sh" host
fi
