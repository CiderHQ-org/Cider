def release_fixture(revision='a' * 40, previous='b' * 40):
    builds = {}
    for flavor in ('arch', 'ubuntu24.04'):
        stem = f'ciderdarling-{revision}-x86_64-{flavor}'
        builds[flavor] = {'archive': stem + '.tar.xz', 'manifest': stem + '.json',
                         'archive_sha256': 'c' * 64, 'manifest_sha256': 'd' * 64,
                         'archive_bytes': 4096, 'min_glibc': '2.39', 'min_glibcxx': '3.4.30',
                         'min_cxxabi': '1.3.13', 'min_libgcc': '3.0', 'native_libraries': ['libcairo.so.2']}
    return {'schema_version': 1, 'name': 'CiderDarling', 'channel': 'stable', 'architecture': 'x86_64',
            'source_revision': revision, 'patch_manifest_sha256': 'e' * 64, 'source_date': 123,
            'minimum_cider': '0.23', 'supersedes': [previous], 'builds': builds,
            'release_url': f'https://github.com/CiderHQ-org/CiderDarling/releases/tag/bin-{revision[:12]}'}
