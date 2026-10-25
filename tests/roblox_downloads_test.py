"""A denied public deployment may fall back; account and other failures cannot."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from quadra import core, roblox_downloads

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
    def test_default_version_check_ignores_a_saved_restricted_channel(self):
        payload = json.dumps({'version': '0.743.0.7431134', 'clientVersionUpload': UPLOAD}).encode()
        with patch.object(core, 'load_settings', return_value={'roblox_channel': 'zbeta'}) as settings, \
                patch.object(core, 'open_public', return_value=Response(payload)) as opener:
            self.assertEqual(core.latest_version(), ('0.743.0.7431134', UPLOAD))
        opener.assert_called_once_with(VERSION, timeout=10)
        settings.assert_not_called()

    def test_explicit_required_channel_can_still_use_the_clients_validated_deployment(self):
        target = {'channel': 'zbeta', 'version': '0.743.0.7431134', 'upload': UPLOAD}
        error = denied(VERSION + '/channel/zbeta', 401)
        self.addCleanup(error.close)
        with patch.object(core, 'open_public', side_effect=error), \
                patch.object(core, 'required_client_update', return_value=target), \
                patch.object(core, 'installed_version', return_value='0.742.0.7420000'):
            self.assertEqual(core.latest_version('zbeta', required_log='current.log'),
                             (target['version'], UPLOAD))

    def test_primary_success_never_uses_mirror(self):
        response = Response()
        with patch.object(roblox_downloads.urllib.request, 'urlopen', return_value=response) as opener:
            self.assertIs(roblox_downloads.open_public(VERSION), response)
            self.assertEqual(opener.call_count, 1)
            self.assertEqual(opener.call_args.args[0].full_url, VERSION)
        response.close()

    def test_403_tries_official_alternate_without_changing_channel_or_upload(self):
        for url in (VERSION, VERSION + '/channel/znext', ARCHIVE):
            with self.subTest(url=url):
                response = Response()
                error = denied(url)
                with patch.object(roblox_downloads.urllib.request, 'urlopen', side_effect=[error, response]) as opener:
                    self.assertIs(roblox_downloads.open_public(url), response)
                    self.assertTrue(error.fp.closed)
                    request = opener.call_args.args[0]
                    self.assertEqual(request.full_url, roblox_downloads.official_alternates(url)[0])
                    self.assertEqual(set(key.lower() for key in request.headers), {'user-agent'})
                    self.assertEqual(opener.call_count, 2)
                response.close()

    def test_mirror_remains_available_when_all_official_origins_deny(self):
        for url in (VERSION, VERSION + '/channel/znext', ARCHIVE):
            with self.subTest(url=url):
                alternates = roblox_downloads.official_alternates(url)
                errors = [denied(candidate) for candidate in (url, *alternates)]
                response = Response()
                fallback = []
                with patch.object(roblox_downloads.urllib.request, 'urlopen',
                                  side_effect=[*errors, response]) as opener:
                    self.assertIs(roblox_downloads.open_public(url, on_fallback=lambda: fallback.append(True)), response)
                    self.assertEqual([call.args[0].full_url for call in opener.call_args_list],
                                     [url, *alternates, roblox_downloads.mirror_url(url)])
                    self.assertTrue(all(error.fp.closed for error in errors))
                    self.assertEqual(fallback, [True])
                    self.assertGreaterEqual(opener.call_args.kwargs['timeout'], 40)
                response.close()

    def test_unreachable_alternate_does_not_prevent_mirror_recovery(self):
        response = Response()
        with patch.object(roblox_downloads.urllib.request, 'urlopen', side_effect=[
                denied(), urllib.error.URLError('name lookup failed'), response]) as opener:
            self.assertIs(roblox_downloads.open_public(VERSION), response)
            self.assertEqual(opener.call_args.args[0].full_url, roblox_downloads.mirror_url(VERSION))
        response.close()

    def test_alternate_restrictions_and_final_403_are_not_hidden(self):
        for code in (400, 401, 405):
            error = denied(status=code)
            with patch.object(roblox_downloads.urllib.request, 'urlopen', side_effect=[denied(), error]) as opener:
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    roblox_downloads.open_public(VERSION)
                self.assertEqual(raised.exception.code, code)
                self.assertEqual(opener.call_count, 2)
            error.close()
        errors = [denied() for _ in range(3)]
        with patch.object(roblox_downloads.urllib.request, 'urlopen', side_effect=errors):
            with self.assertRaises(urllib.error.HTTPError) as raised:
                roblox_downloads.open_public(VERSION)
            self.assertEqual(raised.exception.code, 403)
        for error in errors:
            error.close()

    def test_unavailable_alternate_after_403_reaches_the_same_deployment_on_mirror(self):
        for code in (404, 408, 429, 500, 502, 503, 504):
            for url in (VERSION, VERSION + '/channel/znext', ARCHIVE):
                with self.subTest(code=code, url=url):
                    errors = [denied(url), *[denied(candidate, code) for candidate in roblox_downloads.official_alternates(url)]]
                    response = Response()
                    with patch.object(roblox_downloads.urllib.request, 'urlopen', side_effect=[*errors, response]) as opener:
                        self.assertIs(roblox_downloads.open_public(url), response)
                        self.assertEqual(opener.call_args.args[0].full_url, roblox_downloads.mirror_url(url))
                    self.assertTrue(all(error.fp.closed for error in errors))
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
                    if status == 403:
                        self.assertEqual(roblox_downloads.official_alternates(url), ())
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
