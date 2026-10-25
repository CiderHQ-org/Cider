#!/usr/bin/env python3
"""Stage a verified Darling sysroot for packaging; never install a runtime."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'launcher'))
from quadra import runtime_updates


def download(url, target, digest):
    request = urllib.request.Request(url, headers={'User-Agent': 'Quadra-package-builder'})
    hasher = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=60) as response, target.open('xb') as output:
        size = 0
        while chunk := response.read(1 << 20):
            size += len(chunk)
            if size > 8 * 1024**3:
                raise ValueError('Build runtime archive is too large')
            hasher.update(chunk)
            output.write(chunk)
    if hasher.hexdigest() != digest:
        raise ValueError('Build runtime checksum does not match')


def build_files(member, path):
    # Darling's root links some paths to absolute guest paths (/System/...,
    # /Volumes/SystemRoot/..., /dev). They resolve only inside Darling and the
    # build uses none of them, but the data filter rejects them: leave them out.
    if member.issym() and member.linkname.startswith('/'):
        return None
    return tarfile.data_filter(member, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    feed = None
    try:
        with urllib.request.urlopen(runtime_updates.FEED_URL, timeout=12) as response:
            raw = response.read(runtime_updates.MAX_BYTES + 1)
        if len(raw) > runtime_updates.MAX_BYTES:
            raise ValueError('Update feed is too large')
        feed = runtime_updates.validate(json.loads(raw))
    except (OSError, ValueError):
        pass
    if feed is not None and runtime_updates.supported(feed):
        revision = feed['source_revision']
        build = feed['builds']['ubuntu24.04']
        archive = out / build['archive']
        url = f'https://github.com/QuadraHQ/CiderDarling/releases/download/bin-{revision[:12]}/{archive.name}'
        download(url, archive, build['archive_sha256'])
        with tarfile.open(archive) as source:
            members = source.getmembers()
            if any(Path(member.name).parts[0] != revision for member in members):
                raise ValueError('Build runtime archive names another revision')
            source.extractall(out / 'stage', members=members, filter=build_files)
        sysroot = out / 'stage' / revision / 'libexec/darling'
    else:
        # This lets Quadra packages build while CiderDarling's first CI release
        # is still compiling. Only Mach-O libraries/headers are used; the
        # staged Darling client and Linux bridges are never executed.
        text = (ROOT / 'install.sh').read_text()
        tag = re.search(r'^DARLING_TAG=(v[0-9.]+)$', text, re.M)[1]
        digest = re.search(r'^DARLING_DEBS_SHA256=([0-9a-f]{64})$', text, re.M)[1]
        archive = out / 'darling-debs.zip'
        download(f'https://github.com/darlinghq/darling/releases/download/{tag}/debs_{tag.rsplit(".", 1)[-1]}.zip',
                 archive, digest)
        debs = out / 'debs'
        debs.mkdir()
        count = 0
        with zipfile.ZipFile(archive) as source:
            for member in source.infolist():
                if member.is_dir() or not member.filename.endswith('.deb'):
                    continue
                target = debs / Path(member.filename).name
                with source.open(member) as stream, target.open('xb') as output:
                    shutil.copyfileobj(stream, output)
                subprocess.run(['dpkg-deb', '--extract', str(target), str(out / 'stage')], check=True)
                count += 1
        if not count:
            raise ValueError('The pinned archive has no Darling packages')
        sysroot = out / 'stage/usr/libexec/darling'
    if not (sysroot / 'usr/lib/libSystem.B.dylib').is_file():
        raise ValueError('The build sysroot is incomplete')
    (out / 'sysroot').symlink_to(sysroot.relative_to(out))
    print('Verified build sysroot:', out / 'sysroot')


if __name__ == '__main__':
    main()
