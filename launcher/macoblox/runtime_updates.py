"""Discover complete CiderDarling releases without changing runtime selection."""
import json
import os
from pathlib import Path
import re
import tempfile
import time
import urllib.request

from . import __version__

REPOSITORY = 'CiderHQ-org/CiderDarling'
FEED_URL = f'https://github.com/{REPOSITORY}/releases/download/runtime-updates/stable.json'
MAX_BYTES = 65536
CHECK_INTERVAL = 3600
FLAVORS = ('arch', 'ubuntu24.04')


def validate(data):
    if (not isinstance(data, dict) or data.get('schema_version') != 1
            or data.get('name') != 'CiderDarling' or data.get('channel') != 'stable'
            or data.get('architecture') != 'x86_64'):
        raise ValueError('Unknown CiderDarling update format')
    revision, series = data.get('source_revision'), data.get('patch_manifest_sha256')
    if (not isinstance(revision, str) or not re.fullmatch('[0-9a-f]{40}', revision)
            or not isinstance(series, str) or not re.fullmatch('[0-9a-f]{64}', series)
            or type(data.get('source_date')) is not int or data['source_date'] <= 0
            or data.get('release_url') != f'https://github.com/{REPOSITORY}/releases/tag/bin-{revision[:12]}'):
        raise ValueError('Invalid CiderDarling release identity')
    minimum = data.get('minimum_cider')
    if not isinstance(minimum, str) or not re.fullmatch(r'[0-9]+(?:\.[0-9]+)*', minimum):
        raise ValueError('Invalid required Quadra version')
    ancestors = data.get('supersedes')
    if (not isinstance(ancestors, list) or len(ancestors) > 128
            or any(not isinstance(value, str) or not re.fullmatch('[0-9a-f]{40}', value) for value in ancestors)):
        raise ValueError('Invalid runtime update history')
    builds = data.get('builds')
    if not isinstance(builds, dict) or any(flavor not in builds for flavor in FLAVORS):
        raise ValueError('The runtime release is incomplete')
    for flavor in FLAVORS:
        build = builds[flavor]
        stem = f'ciderdarling-{revision}-x86_64-{flavor}'
        if (not isinstance(build, dict) or build.get('archive') != stem + '.tar.xz'
                or build.get('manifest') != stem + '.json'
                or type(build.get('archive_bytes')) is not int or not 0 < build['archive_bytes'] < 20 * 1024**3):
            raise ValueError('Invalid runtime archive')
        for field in ('archive_sha256', 'manifest_sha256'):
            if not isinstance(build.get(field), str) or not re.fullmatch('[0-9a-f]{64}', build[field]):
                raise ValueError('Invalid runtime download checksum')
        for field in ('min_glibc', 'min_glibcxx', 'min_cxxabi', 'min_libgcc'):
            if not isinstance(build.get(field), str) or not re.fullmatch(r'[0-9]+(?:\.[0-9]+)*', build[field]):
                raise ValueError('Invalid runtime library requirement')
        libraries = build.get('native_libraries')
        if (not isinstance(libraries, list) or len(libraries) > 256
                or any(not isinstance(name, str) or not re.fullmatch(r'lib[A-Za-z0-9_+.-]+\.so(?:\.[0-9]+)*', name)
                       for name in libraries)):
            raise ValueError('Invalid runtime native libraries')
    return data


def supported(data):
    numbers = lambda version: tuple(int(value) for value in re.findall(r'\d+', version))
    return numbers(__version__) >= numbers(data['minimum_cider'])


def cache_path(cache):
    return Path(cache) / 'runtime-release.json'


def cached(cache):
    try:
        path = cache_path(cache)
        if path.stat().st_size > MAX_BYTES:
            return None
        data = validate(json.loads(path.read_bytes()))
        return data if supported(data) else None
    except (OSError, ValueError, TypeError):
        return None


def newer(release, metadata):
    """Offer descendants, never a downgrade from a newer/custom build."""
    current = metadata.get('source_revision')
    if current == release['source_revision']:
        return False
    return current in release['supersedes']


def check(cache, *, force=False, opener=urllib.request.urlopen):
    """Fetch on a worker thread. Keep the last valid feed through outages."""
    prior = cached(cache)
    path = cache_path(cache)
    if not force and prior and time.time() - path.stat().st_mtime < CHECK_INTERVAL:
        return prior
    request = urllib.request.Request(FEED_URL, headers={'User-Agent': f'Quadra/{__version__}',
                                                       'Accept': 'application/json'})
    with opener(request, timeout=12) as response:
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('Runtime update feed is too large')
    data = validate(json.loads(raw))
    if not supported(data):
        return prior
    if prior and data['source_revision'] != prior['source_revision'] and not newer(data, prior):
        return prior
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.runtime-release-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
    return data


def pin(release):
    return {'revision': release['source_revision'], 'manifest': release['patch_manifest_sha256']}
