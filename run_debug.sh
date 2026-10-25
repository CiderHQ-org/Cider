#!/usr/bin/env bash
set -euo pipefail
project_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
runtime_fields=$(python3 - "$project_dir/launcher" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
from quadra.runtime import resolve_runtime, guest_variables
runtime = resolve_runtime()
print('\n'.join(runtime[key] for key in ('executable', 'sysroot', 'prefix')))
print('1' if guest_variables(runtime['metadata']) else '')
PY
)
mapfile -t runtime <<< "$runtime_fields"
darling_executable=${runtime[0]}
export DARLING_SYSROOT=${runtime[1]} DPREFIX=${runtime[2]}
if [[ ${runtime[3]:-} == 1 ]]; then export QUADRA_NATIVE_WORKQUEUE=1; fi
# An upgraded kernel can leave the running kernel without loadable modules.
if ! grep -qw overlay /proc/filesystems; then
  running_kernel=$(uname -r)
  if [[ ! -d "/usr/lib/modules/$running_kernel" ]]; then
    printf 'Darling cannot start: OverlayFS is unavailable and modules for running kernel %s are missing.\n' "$running_kernel" >&2
    printf 'Reboot into the installed kernel, then run this script again.\n' >&2
    exit 1
  fi
fi
# Darling's Mesa receives X11 displays. A desktop session may export
# EGL_PLATFORM=wayland, which makes Mesa treat them as Wayland and crash.
export EGL_PLATFORM=x11
# No host player here (the launcher's pw-cat FIFO), and Darling's own audio
# path crashes the game: no sound, as the launcher does without pw-cat.
# QUADRA_AUDIO_FIFO=... or QUADRA_AUDIO=1 overrides this.
if [[ -z ${QUADRA_AUDIO_FIFO:-} ]]; then
  export QUADRA_AUDIO=${QUADRA_AUDIO:-0}
fi
"$project_dir/build_debug_shim.sh"
mkdir -p "$project_dir/logs"
log_file=$(mktemp "$project_dir/logs/launch-$(date +%Y%m%d-%H%M%S)-XXXXXX.log")
printf 'Log: %s\n' "$log_file"
# Pass paths as arguments, preserving spaces and non-ASCII names.
# Use the existing Darling prefix, which contains the framework replacements.
set +e
# Forward every QUADRA_* variable into the Darling shell as NAME=value
# arguments, so new diagnostic switches need no changes here.
quadra_env=()
while IFS= read -r name; do
  quadra_env+=("$name=${!name}")
done < <(compgen -e | grep '^QUADRA_' || true)
"$darling_executable" shell /bin/bash -c '
  project_dir=$1
  env_count=$2
  shift 2
  while [ "$env_count" -gt 0 ]; do
    export "$1"
    shift
    env_count=$((env_count - 1))
  done
  app_dir="$project_dir/RobloxPlayer.app/Contents/MacOS"
  cd "$app_dir" || exit
  export DYLD_FORCE_FLAT_NAMESPACE=1
  export DYLD_INSERT_LIBRARIES="$project_dir/build/libQuadraShims.dylib"
  export DYLD_LIBRARY_PATH="$project_dir/build:$app_dir"
  exec ./RobloxPlayer "$@"
' quadra "/Volumes/SystemRoot$project_dir" "${#quadra_env[@]}" "${quadra_env[@]}" "$@" 2>&1 | tee "$log_file"
launch_status=${PIPESTATUS[0]}
printf '\nLauncher exit status: %s\n' "$launch_status" | tee -a "$log_file"
exit "$launch_status"
