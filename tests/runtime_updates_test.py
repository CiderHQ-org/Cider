import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
import urllib.error

from quadra import runtime_install, runtime_updates
from runtime_update_fixture import release_fixture


class RuntimeUpdatesTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.cache = Path(self.directory.name)
        self.release = release_fixture()

    def opener(self, data):
        return Mock(side_effect=lambda *args, **kwargs: io.BytesIO(json.dumps(data).encode()))

    def test_complete_feed_is_cached_privately_and_reused_without_network(self):
        opener = self.opener(self.release)
        self.assertEqual(runtime_updates.check(self.cache, opener=opener), self.release)
        self.assertEqual(runtime_updates.cache_path(self.cache).stat().st_mode & 0o777, 0o600)
        self.assertEqual(runtime_updates.check(self.cache, opener=opener), self.release)
        self.assertEqual(opener.call_count, 1)
        self.assertEqual(opener.call_args.args[0].full_url, runtime_updates.FEED_URL)

    def test_outage_or_invalid_feed_preserves_the_last_valid_release(self):
        runtime_updates.check(self.cache, opener=self.opener(self.release))
        before = runtime_updates.cache_path(self.cache).read_bytes()
        for opener in (Mock(side_effect=urllib.error.URLError('offline')), self.opener({'schema_version': 999})):
            with self.assertRaises((OSError, ValueError)):
                runtime_updates.check(self.cache, force=True, opener=opener)
            self.assertEqual(runtime_updates.cache_path(self.cache).read_bytes(), before)

    def test_release_may_name_the_repository_by_its_old_or_new_owner_only(self):
        revision = self.release['source_revision'][:12]
        for owner in ('CiderHQ-org', 'QuadraHQ'):
            with self.subTest(owner=owner):
                data = copy.deepcopy(self.release)
                data['release_url'] = f'https://github.com/{owner}/CiderDarling/releases/tag/bin-{revision}'
                self.assertEqual(runtime_updates.validate(data), data)
        data = copy.deepcopy(self.release)
        data['release_url'] = f'https://github.com/someone-else/CiderDarling/releases/tag/bin-{revision}'
        with self.assertRaises(ValueError):
            runtime_updates.validate(data)

    def test_incomplete_wrong_origin_or_path_and_checksum_payloads_are_rejected(self):
        cases = []
        for field, value in [('release_url', 'https://other.test/release'), ('architecture', 'arm64'),
                             ('source_revision', '../other'), ('source_date', True)]:
            data = copy.deepcopy(self.release)
            data[field] = value
            cases.append(data)
        missing = copy.deepcopy(self.release)
        del missing['builds']['arch']
        cases.append(missing)
        for field, value in [('archive', '../bad.tar.xz'), ('archive_sha256', 'bad'), ('manifest_sha256', ''),
                             ('native_libraries', ['/tmp/lib.so']), ('archive_bytes', True)]:
            data = copy.deepcopy(self.release)
            data['builds']['arch'][field] = value
            cases.append(data)
        for data in cases:
            with self.subTest(data=data):
                with self.assertRaises(ValueError):
                    runtime_updates.validate(data)

    def test_oversized_feed_and_newer_required_cider_do_not_replace_cache(self):
        with self.assertRaises(ValueError):
            runtime_updates.check(self.cache, opener=lambda *args, **kwargs: io.BytesIO(b'x' * 65537))
        future = copy.deepcopy(self.release)
        future['minimum_cider'] = '999.0'
        self.assertIsNone(runtime_updates.check(self.cache, opener=self.opener(future)))
        self.assertFalse(runtime_updates.cache_path(self.cache).exists())

    def test_only_descendant_releases_are_offered_and_older_feed_is_ignored(self):
        self.assertTrue(runtime_updates.newer(self.release, {'source_revision': 'b' * 40}))
        self.assertFalse(runtime_updates.newer(self.release, {'source_revision': 'a' * 40}))
        self.assertFalse(runtime_updates.newer(self.release, {'source_revision': 'f' * 40}))
        runtime_updates.check(self.cache, opener=self.opener(self.release))
        older = release_fixture('b' * 40, 'f' * 40)
        self.assertEqual(runtime_updates.check(self.cache, force=True, opener=self.opener(older)), self.release)

    def test_terminal_installs_an_immutable_snapshot_of_the_accepted_release(self):
        project = self.cache / 'project'
        project.mkdir()
        (project / 'install.sh').write_text('exit 0\n')
        job = runtime_install.Installation.create(project, 'ciderdarling', self.cache, release=self.release)
        self.addCleanup(job.close)
        self.release['source_revision'] = 'f' * 40
        self.assertEqual(job.target_revision, 'a' * 40)
        self.assertEqual(job.command[-2], '--runtime-release')
        snapshot = json.loads(Path(job.command[-1]).read_text())
        self.assertEqual(snapshot['source_revision'], 'a' * 40)
