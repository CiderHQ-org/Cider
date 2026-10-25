"""Studio's Wine is the newest stable Kombucha release, and a failed check never breaks an install."""
import io
from pathlib import Path
import shutil
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from quadra import core, studio

RELEASES = 'https://github.com/vinegarhq/kombucha'
TAG = 'stable+20261018103513'


class Response(io.BytesIO):
    def __init__(self, body=b'', url=''):
        super().__init__(body)
        self.headers = {'Content-Length': str(len(body))}
        self.url = url


def kombucha_archive(tag=TAG):
    """The release layout: one directory holding bin, lib and share."""
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode='w:xz') as archive:
        for name, body in (('bin/wine', b'#!/bin/sh\n'), ('lib/wine/x86_64-unix/ntdll.so', b'elf')):
            member = tarfile.TarInfo(f'kombucha-{tag}/{name}')
            member.size, member.mode = len(body), 0o755
            archive.addfile(member, io.BytesIO(body))
    return data.getvalue()


class StudioWineTests(unittest.TestCase):
    def setUp(self):
        base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        self.wine = base / 'studio' / 'wine'
        for name, value in (('ROOT', base / 'studio'), ('WINE', self.wine),
                            ('STATE', base / 'studio' / 'state.json'), ('PREFIX', base / 'studio' / 'prefix')):
            patcher = patch.object(studio, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(core, 'DOWNLOADS', base / 'downloads')
        patcher.start()
        self.addCleanup(patcher.stop)
        self.urls = []
        self.progress = lambda fraction, text: None

    def release(self, tag=TAG, archive=None):
        """Serves the release redirect and the archive; remembers what was asked for."""
        archive = kombucha_archive(tag) if archive is None else archive

        def opener(url, timeout=30):
            self.urls.append(url)
            if url.endswith('/releases/latest'):
                return Response(url=f'{RELEASES}/releases/tag/{tag}')
            return Response(archive, url)

        return patch.object(studio, '_open', opener)

    def test_latest_tag_is_decoded_from_the_release_redirect(self):
        for escaped in ('stable+20261018103513', 'stable%2B20261018103513'):
            with self.subTest(escaped=escaped), \
                    patch.object(studio, '_open', return_value=Response(url=f'{RELEASES}/releases/tag/{escaped}')):
                self.assertEqual(studio._latest_tag(RELEASES), TAG)

    def test_fresh_install_unpacks_the_kombucha_build_without_its_top_directory(self):
        state = {}
        with self.release():
            studio._ensure_wine(state, self.progress)
        self.assertEqual(state['wine'], TAG)
        self.assertEqual(studio._state()['wine'], TAG)
        self.assertTrue((self.wine / 'bin' / 'wine').is_file())
        self.assertTrue((self.wine / 'lib' / 'wine' / 'x86_64-unix' / 'ntdll.so').is_file())
        self.assertEqual(self.urls[-1], f'{RELEASES}/releases/download/stable%2B20261018103513/'
                                        'kombucha-stable%2B20261018103513.tar.xz')
        self.assertEqual(list((core.DOWNLOADS).glob('*')), [], 'the archive is removed after unpacking')

    def test_current_build_is_not_downloaded_again(self):
        state = {}
        with self.release():
            studio._ensure_wine(state, self.progress)
            self.urls.clear()
            studio._ensure_wine(state, self.progress)
        self.assertEqual(self.urls, [f'{RELEASES}/releases/latest'])

    def test_older_build_is_replaced_and_its_wineserver_stopped(self):
        (self.wine / 'bin').mkdir(parents=True)
        log = self.wine.parent / 'wineserver.log'
        (self.wine / 'bin' / 'wine').write_text('#!/bin/sh\n')
        server = self.wine / 'bin' / 'wineserver'
        server.write_text(f'#!/bin/sh\necho "$@" >> {log}\n')
        server.chmod(0o755)
        (self.wine / 'old-only-file').write_text('from the previous build')
        state = {'wine': '10.15', 'prefix': '10.15', 'dxvk': 'v2.7'}
        with self.release():
            studio._ensure_wine(state, self.progress)
        self.assertEqual(log.read_text().strip(), '-k')
        self.assertEqual(state['wine'], TAG)
        self.assertFalse((self.wine / 'old-only-file').exists())
        self.assertTrue((self.wine / 'lib' / 'wine' / 'x86_64-unix' / 'ntdll.so').is_file())
        # The prefix and DXVK follow the new build.
        self.assertNotEqual(state['prefix'], state['wine'])

    def test_offline_keeps_the_installed_build(self):
        (self.wine / 'bin').mkdir(parents=True)
        (self.wine / 'bin' / 'wine').write_text('#!/bin/sh\n')
        state = {'wine': '10.15'}
        with patch.object(studio, '_open', side_effect=urllib.error.URLError('offline')):
            studio._ensure_wine(state, self.progress)
        self.assertEqual(state, {'wine': '10.15'})
        self.assertTrue((self.wine / 'bin' / 'wine').exists())

    def test_offline_without_any_build_is_an_error(self):
        with patch.object(studio, '_open', side_effect=urllib.error.URLError('offline')):
            with self.assertRaises(OSError):
                studio._ensure_wine({}, self.progress)

    def test_failed_download_leaves_the_installed_build_and_state_alone(self):
        (self.wine / 'bin').mkdir(parents=True)
        (self.wine / 'bin' / 'wine').write_text('#!/bin/sh\n')
        state = {'wine': '10.15'}

        error = urllib.error.HTTPError(RELEASES, 404, 'missing', {}, io.BytesIO())
        self.addCleanup(error.close)

        def opener(url, timeout=30):
            if url.endswith('/releases/latest'):
                return Response(url=f'{RELEASES}/releases/tag/{TAG}')
            raise error

        with patch.object(studio, '_open', opener):
            with self.assertRaises(OSError):
                studio._ensure_wine(state, self.progress)
        self.assertEqual(state, {'wine': '10.15'})
        self.assertTrue((self.wine / 'bin' / 'wine').exists())


if __name__ == '__main__':
    unittest.main()
