#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
set -euo pipefail
base=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
project=$(cd -- "$base/../.." && pwd -P)
cache=${XDG_CACHE_HOME:-$HOME/.cache}/quadra-vulkan/src
darling_source=${DARLING_SOURCE:-$cache/darling}
vulkan_headers=${VULKAN_HEADERS:-$cache/Vulkan-Headers-1.3.290/include}
sysroot=${DARLING_SYSROOT:-/usr/libexec/darling}
work=${MACOBLOX_METAL_WORK:-$project/work/metal-backend-repro}
compiler=${CXX:-clang++}
python3 "$base/source_pins.py" --darling "$darling_source" --vulkan "$vulkan_headers"
metal_source="$darling_source/src/external/metal"
sdk="$darling_source/Developer/Platforms/MacOSX.platform/Developer/SDKs/MacOSX.sdk"
mkdir -p "$work/out"
work=$(cd -- "$work" && pwd -P)
indium_source="$work/indium"
# Only this private build copy is changed. Upstream source remains untouched.
if [[ -e "$indium_source" ]]; then
  printf '%s\n' "Indium build copy already exists: $indium_source" >&2
  printf '%s\n' 'Use a new MACOBLOX_METAL_WORK directory for a fresh build.' >&2
  exit 1
fi
cp -a "$metal_source/deps/indium" "$indium_source"
patch -s -d "$indium_source" -p1 < "$base/indium_ssbo.patch"
common=( -target x86_64-apple-darwin -fuse-ld=lld -isysroot "$sysroot"
  -mmacosx-version-min=11.0 -O2 -fblocks -std=c++17 -fno-objc-arc
  -nostdinc++ -I "$darling_source/src/external/libcxx/include"
  -isystem "$sdk/usr/include" -F "$sdk/System/Library/Frameworks"
  -F "$sdk/System/Library/PrivateFrameworks"
  -I "$indium_source/include" -I "$indium_source/private-include"
  -I "$vulkan_headers" -I "$darling_source/src/startup/mldr/elfcalls"
  -I "$darling_source/src/frameworks/CoreServices/include"
  -DTARGET_OS_WASI=0 -Wno-nullability-completeness
  -DDARLING -DPLATFORM_MacOSX -DDARLING_METAL_ENABLED=1 )
"$compiler" "${common[@]}" -dynamiclib -install_name @rpath/libiridium.dylib \
  "$base/iridium_adapter.cpp" -lc++ -lc++abi -L "$sysroot/usr/lib/system" -lcommonCrypto \
  -Wl,-undefined,dynamic_lookup -o "$work/out/libiridium.dylib"
"$compiler" "${common[@]}" -dynamiclib -install_name @rpath/libindium.dylib \
  "$indium_source"/src/indium/*.cpp -L "$work/out" -liridium -lc++ -lc++abi \
  -Wl,-undefined,dynamic_lookup -o "$work/out/libindium.dylib"
"$compiler" "${common[@]}" -I "$metal_source/include" -I "$metal_source/private-include" \
  -dynamiclib -install_name /System/Library/Frameworks/Metal.framework/Versions/A/Metal \
  "$metal_source"/src/Metal/*.mm -L "$work/out" -lindium -lc++ -lc++abi -lobjc -framework Foundation \
  -Wl,-undefined,dynamic_lookup -o "$work/out/Metal"
"$compiler" "${common[@]}" -I "$metal_source/include" -I "$metal_source/private-include" \
  "$base/pipeline_probe.mm" "$work/out/Metal" -L "$work/out" -lindium \
  -lc++ -lc++abi -lobjc -framework Foundation \
  -Wl,-rpath,"/Volumes/SystemRoot$work/out" -o "$work/out/pipeline-probe"
"$compiler" -target x86_64-apple-darwin -fuse-ld=lld -isysroot "$sysroot" \
  -mmacosx-version-min=11.0 "$base/device_probe.m" "$work/out/Metal" \
  -lobjc -framework Foundation -Wl,-rpath,"/Volumes/SystemRoot$work/out" \
  -o "$work/out/device-probe"
mkdir -p "$work/out/Metal.framework/Versions/A"
ln -sfn ../../../Metal "$work/out/Metal.framework/Versions/A/Metal"
ln -sfn A "$work/out/Metal.framework/Versions/Current"
ln -sfn Versions/Current/Metal "$work/out/Metal.framework/Metal"
printf '%s\n' "Built native Vulkan experiment in $work/out"
