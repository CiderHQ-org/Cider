"""A denied public deployment may fall back; account and other failures cannot."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from macoblox import core, roblox_downloads

VERSION = 'https://clientsettingscdn.roblox.com/v2/client-version/MacPlayer'
UPLOAD = 'version-212bac6bdccd4673'
ARCHIVE = f'https://setup.rbxcdn.com/mac/{UPLOAD}-RobloxPlayer.zip'


class Response(io.BytesIO):
    def __init__(self, body=b'{}', size=None):
        super().__init__(body)
        self.headers = {'Content-Length': str(len(body) if size is None else size)}


def denied(url=VERSION, status=403):
    return urllib.error.HTTPError(url, status, 'failure', {}, io.BytesIO(b'denied'))


class PublicDownloadTests(unittest.TestCase):
    def test_primary_success_never_uses_mirror(self):
        response = Response()
        with patch.object(roblox_downloads.urllib.request, 'urlopen', return_value=response) as opener:
            self.assertIs(roblox_downloads.open_public(VERSION), response)
            self.assertEqual(opener.call_count, 1)
            self.assertEqual(opener.call_args.args[0].full_url, VERSION)
        response.close()

    def test_403_retries_identical_channel_or_upload_without_credentials(self):
        for url in (VERSION, VERSION + '/channel/znext', ARCHIVE):
            with self.subTest(url=url):
                response = Response()
                error = denied(url)
                with patch.object(roblox_downloads.urllib.request, 'urlopen', side_effect=[error, response]) as opener:
                    self.assertIs(roblox_downloads.open_public(url), response)
                    self.assertTrue(error.fp.closed)
                    request = opener.call_args.args[0]
                    self.assertEqual(request.full_url, roblox_downloads.mirror_url(url))
                    self.assertEqual(set(key.lower() for key in request.headers), {'user-agent'})
                    self.assertGreaterEqual(opener.call_args.kwargs['timeout'], 40)
                response.close()

    def test_other_http_errors_and_account_paths_never_use_mirror(self):
        cases = [(VERSION, code) for code in (401, 404, 429, 500)]
        cases += [(url, 403) for url in (
            'https://auth.roblox.com/v2/login', VERSION + '?token=secret',
            'https://clientsettingscdn.roblox.com.evil/v2/client-version/MacPlayer',
            'https://secret@clientsettingscdn.roblox.com/v2/client-version/MacPlayer',
            'https://setup.rbxcdn.com/mac/../account', 'http://setup.rbxcdn.com/mac/' + UPLOAD + '-RobloxPlayer.zip')]
        for url, status in cases:
            with self.subTest(url=url, status=status):
                error = denied(url, status)
                with patch.object(roblox_downloads.urllib.request, 'urlopen', side_effect=error) as opener:
                    with self.assertRaises(urllib.error.HTTPError):
                        roblox_downloads.open_public(url)
                    self.assertEqual(opener.call_count, 1)
                error.close()

    def test_fallback_metadata_is_validated_by_the_launcher(self):
        for payload, valid in (({'version': '0.743.0.7431134', 'clientVersionUpload': UPLOAD}, True),
                               ({'version': 'bad', 'clientVersionUpload': '../bad'}, False)):
            with patch.object(roblox_downloads.urllib.request, 'urlopen',
                              side_effect=[denied(), Response(json.dumps(payload).encode())]):
                if valid:
                    self.assertEqual(core.latest_version(''), ('0.743.0.7431134', UPLOAD))
                else:
                    with self.assertRaises(ValueError):
                        core.latest_version('')

    def test_truncated_download_keeps_installed_client_and_removes_partial(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            bundle = base / 'RobloxPlayer.app'
            bundle.mkdir()
            marker = bundle / 'keep'
            marker.write_text('installed client')
            with patch.object(core, 'DOWNLOADS', base / 'downloads'), \
                    patch.object(core, 'APP_BUNDLE', bundle), \
                    patch.object(roblox_downloads.urllib.request, 'urlopen',
                                 side_effect=[denied(ARCHIVE), Response(b'partial', size=100)]):
                with self.assertRaisesRegex(OSError, 'Incomplete Roblox download'):
                    core.update_roblox(UPLOAD)
            self.assertEqual(marker.read_text(), 'installed client')
            self.assertEqual(list((base / 'downloads').iterdir()), [])
