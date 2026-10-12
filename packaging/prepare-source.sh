#!/usr/bin/env bash
# Prepare Cider sources and Arch/Debian/RPM inputs without installing them.
set -euo pipefail
if [[ $# -lt 1 || $# -gt 2 ]]; then
  printf 'Usage: %s OUTPUT_DIR [--local|RELEASE_ARCHIVE]\n' "$0" >&2
  exit 2
fi
packaging_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
project_dir=$(dirname -- "$packaging_dir")
mapfile -t release < <(python3 - "$packaging_dir/release.json" <<'PY'
import json, sys
record = json.load(open(sys.argv[1]))
print(record['version'])
print(record.get('sha256') or '')
PY
)
version=${release[0]}
checksum=${release[1]:-}
[[ $version =~ ^[0-9][0-9A-Za-z.]*$ ]] || { printf '%s\n' 'Invalid release version.' >&2; exit 1; }
if [[ ${2:-} != --local && ! $checksum =~ ^[0-9a-f]{64}$ ]]; then
  printf '%s\n' 'The Cider release archive is not pinned yet. Use --local before publication.' >&2
  exit 1
fi
output=$(realpath -m -- "$1")
[[ ! -e $output ]] || { printf 'Output already exists: %s\n' "$output" >&2; exit 1; }
mkdir -p -- "$(dirname -- "$output")"
staging=$(mktemp -d "$(dirname -- "$output")/.ciderhq-sources.XXXXXX")
trap 'rm -rf -- "$staging"' EXIT
archive=$staging/ciderhq_$version.orig.tar.gz
if [[ ${2:-} == --local ]]; then
  python3 - "$project_dir" "$archive" "$version" <<'PY'
import gzip, subprocess, sys, tarfile
from pathlib import Path
root, output, version = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
paths = {Path(name.decode()) for name in subprocess.check_output(
    ['git', '-C', str(root), 'ls-files', '-z']).split(b'\0') if name}
directories = ('launcher', 'branding', 'packaging', 'frameworks', 'flatpak', 'docs', 'experimental')
new_files = subprocess.check_output(['git', '-C', str(root), 'ls-files', '-z',
                                    '--others', '--exclude-standard', '--', *directories])
public_extensions = {'.py', '.sh', '.c', '.m', '.h', '.cpp', '.svg', '.desktop', '.xml', '.json', '.yml', '.in', '.md', '.spec'}
public_names = {'.SRCINFO', 'PKGBUILD', 'ciderhq-launcher', 'macoblox-launcher'}
paths.update(path for name in new_files.split(b'\0') if name
             for path in [Path(name.decode())]
             if path.suffix in public_extensions or path.name in public_names)
for pattern in ('*.c', '*.m', '*.h', '*.cpp', '*.S', '*.sh'):
    paths.update(path.relative_to(root) for path in root.glob(pattern))
paths = {path for path in paths if path.parts[0] in directories or len(path.parts) == 1}
paths = {path for path in paths if path.suffix not in ('.pyc', '.log')
         and (root / path).is_file() and path.name != 'AGENTS.md'}
def metadata(info):
    info.mtime = 0
    info.uid = info.gid = 0
    info.uname = info.gname = ''
    return info
with output.open('wb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as zipped:
    with tarfile.open(fileobj=zipped, mode='w') as archive:
        for path in sorted(paths):
            archive.add(root / path, arcname=f'Cider-{version}/{path}', recursive=False, filter=metadata)
PY
  checksum=$(sha256sum -- "$archive")
  checksum=${checksum%% *}
elif [[ $# == 2 ]]; then
  cp -- "$2" "$archive"
else
  curl --fail --location --retry 3 \
    "https://github.com/CiderHQ-org/Cider/releases/download/v$version/ciderhq-$version-source.tar.gz" --output "$archive"
fi
printf '%s  %s\n' "$checksum" "$archive" | sha256sum --check --status
tar -xzf "$archive" -C "$staging"
source_root=$staging/Cider-$version
cp -r --no-preserve=ownership "$packaging_dir/debian" "$source_root/debian"
install -m755 "$packaging_dir/install-payload.sh" "$source_root/debian/install-payload.sh"
install -d "$staging/rpm/SOURCES" "$staging/rpm/SPECS" "$staging/aur/ciderhq"
cp -- "$archive" "$staging/rpm/SOURCES/ciderhq-$version.tar.gz"
install -m755 "$packaging_dir/install-payload.sh" "$staging/rpm/SOURCES/ciderhq-install-payload.sh"
install -m644 "$packaging_dir/rpm/ciderhq.spec" "$staging/rpm/SPECS/ciderhq.spec"
sed "s/@RELEASE_SHA256@/$checksum/g" "$packaging_dir/aur/ciderhq/PKGBUILD.in" > "$staging/aur/ciderhq/PKGBUILD"
cp -- "$archive" "$staging/aur/ciderhq/ciderhq-$version.tar.gz"
if command -v makepkg >/dev/null && (( EUID != 0 )); then
  (cd "$staging/aur/ciderhq" && makepkg --printsrcinfo > .SRCINFO)
fi
mv --no-clobber -T -- "$staging" "$output"
[[ ! -d $staging ]] || { printf 'Output was created by another process: %s\n' "$output" >&2; exit 1; }
printf 'Debian source: %s\nRPM top directory: %s\nStable AUR recipe: %s\n' \
  "$output/Cider-$version" "$output/rpm" "$output/aur/ciderhq"
