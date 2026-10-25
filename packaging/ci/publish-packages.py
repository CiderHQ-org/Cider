#!/usr/bin/env python3
"""Publish complete distro packages, then pin their immutable source archive."""
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = 'QuadraHQ/Quadra'


def run(*args, **kwargs):
    return subprocess.run(list(map(str, args)), check=True, text=True, capture_output=True, **kwargs).stdout


def main():
    directory, version, revision = sys.argv[1:]
    if not re.fullmatch(r'[0-9]+\.[0-9]+[A-Za-z0-9.]*', version) or not re.fullmatch('[0-9a-f]{40}', revision):
        raise ValueError('Invalid release identity')
    dist = Path(directory).resolve()
    files = sorted(path for path in dist.iterdir() if path.is_file())
    if (not any(path.suffix == '.deb' for path in files)
            or not any(path.name.endswith('.pkg.tar.zst') for path in files)
            or not any(path.suffix == '.rpm' and not path.name.endswith('.src.rpm') for path in files)):
        raise ValueError('A distro package is missing; keeping the release unpublished')
    source = dist / f'quadrahq-{version}-source.tar.gz'
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    sums = dist / 'SHA256SUMS'
    sums.write_text(''.join(f'{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n' for path in files))
    notes = ROOT / 'packaging/ci/release-notes.md'
    tag = 'v' + version
    current = subprocess.run(['gh', 'release', 'view', tag, '--repo', REPOSITORY,
                              '--json', 'isDraft,targetCommitish'], text=True, capture_output=True)
    if current.returncode == 0:
        record = json.loads(current.stdout)
        if not record['isDraft'] or record['targetCommitish'] != revision:
            raise ValueError('Refusing to replace an existing release')
        run('gh', 'release', 'upload', tag, *files, sums, '--repo', REPOSITORY, '--clobber')
    else:
        if 'not found' not in current.stderr.lower() and '404' not in current.stderr:
            raise RuntimeError(current.stderr)
        run('gh', 'release', 'create', tag, *files, sums, '--repo', REPOSITORY, '--draft',
            '--target', revision, '--title', 'Quadra ' + version, '--notes-file', notes)
    run('gh', 'release', 'edit', tag, '--repo', REPOSITORY, '--draft=false', '--latest')
    # This commit intentionally follows the source tag: putting the archive's
    # own checksum inside that archive would make its hash circular.
    run('git', 'fetch', 'origin', 'main', cwd=ROOT)
    run('git', 'checkout', 'main', cwd=ROOT)
    run('git', 'merge', '--ff-only', 'origin/main', cwd=ROOT)
    record = json.loads((ROOT / 'packaging/release.json').read_text())
    if record['version'] != version:
        print('A newer release is being prepared; leaving its recipes unchanged.')
        return
    record['sha256'] = digest
    (ROOT / 'packaging/release.json').write_text(json.dumps(record, indent=2) + '\n')
    for asset, target in [('quadrahq.PKGBUILD', 'PKGBUILD'), ('quadrahq.SRCINFO', '.SRCINFO')]:
        shutil.copy2(dist / asset, ROOT / 'packaging/aur/quadrahq' / target)
    run('git', 'config', 'user.name', 'Quadra release bot', cwd=ROOT)
    run('git', 'config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com', cwd=ROOT)
    run('git', 'add', 'packaging/release.json', 'packaging/aur/quadrahq/PKGBUILD',
        'packaging/aur/quadrahq/.SRCINFO', cwd=ROOT)
    changed = subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=ROOT).returncode
    if changed:
        run('git', 'commit', '-m', f'Pin Quadra {version} release source and AUR recipe', cwd=ROOT)
        run('git', 'push', 'origin', 'main', cwd=ROOT)
    print(f'Published Quadra {version} packages and source checksum {digest}.')


if __name__ == '__main__':
    main()
