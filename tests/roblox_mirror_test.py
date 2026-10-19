"""Mirror origin validation, archive completeness, cache reuse and HTTP paths."""
import http.client
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import zipfile

spec = importlib.util.spec_from_file_location('quadra_mirror', Path(__file__).resolve().parents[1] / 'services/roblox-mirror/server.py')
mirror = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mirror)
UPLOAD = 'version-212bac6bdccd4673'


class Response(io.BytesIO):
    def __init__(self, body, size=None, url='https://setup.rbxcdn.com/mac/client.zip'):
        super().__init__(body)
        self.headers = {'Content-Length': str(len(body) if size is None else size)}
        self.url = url


def archive():
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as file:
        file.writestr('RobloxPlayer.app/Contents/Info.plist', 'fixture')
    return output.getvalue()


class MirrorTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.cache = mirror.Cache(self.directory.name)

    def test_archive_is_fetched_once_and_reused_byte_for_byte(self):
        body = archive()
        with patch.object(mirror, 'upstream', return_value=Response(body)) as opener:
            for _ in range(2):
                with self.cache.archive(UPLOAD) as file:
                    self.assertEqual(file.read(), body)
            self.assertEqual(opener.call_count, 1)
            self.assertEqual(opener.call_args.args[0], f'https://setup.rbxcdn.com/mac/{UPLOAD}-RobloxPlayer.zip')

    def test_incomplete_or_non_zip_download_is_never_cached(self):
        for response in (Response(archive(), size=100000), Response(b'not a zip')):
            with patch.object(mirror, 'upstream', return_value=response):
                with self.assertRaises(ValueError):
                    self.cache.archive(UPLOAD)
            self.assertEqual(list(Path(self.directory.name).iterdir()), [])

    def test_version_is_cached_without_changing_channel(self):
        body = json.dumps({'version': '0.743.0.7431134', 'clientVersionUpload': UPLOAD}).encode()
        path = '/v2/client-version/MacPlayer/channel/znext'
        with patch.object(mirror, 'upstream', return_value=Response(body)) as opener:
            self.assertEqual(self.cache.version(path), self.cache.version(path))
            self.assertEqual(opener.call_count, 1)
            self.assertEqual(opener.call_args.args[0], 'https://clientsettingscdn.roblox.com' + path)

    def test_invalid_version_and_redirects_are_rejected(self):
        with patch.object(mirror, 'upstream', return_value=Response(b'{"version":"bad"}')):
            with self.assertRaises(ValueError):
                self.cache.version('/v2/client-version/MacPlayer')
        response = Response(b'private', url='https://other.example/private')
        with patch.object(mirror.urllib.request, 'urlopen', return_value=response):
            with self.assertRaises(ValueError):
                mirror.upstream('https://setup.rbxcdn.com/mac/client.zip', 10)
        self.assertTrue(response.closed)

    def test_http_only_accepts_public_paths_and_does_not_forward_credentials(self):
        server = mirror.Server(('127.0.0.1', 0), self.cache)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with patch.object(mirror, 'upstream', return_value=Response(archive())) as opener:
                for path in ('/v2/login', '/mac/../account', '/mac/' + UPLOAD + '-RobloxPlayer.zip?url=https://evil', '/healthz'):
                    connection = http.client.HTTPConnection(*server.server_address, timeout=3)
                    connection.request('GET', path, headers={'Cookie': 'private', 'Authorization': 'secret'})
                    result = connection.getresponse()
                    self.assertEqual(result.status, 200 if path == '/healthz' else 404)
                    result.read()
                    connection.close()
                opener.assert_not_called()
                connection = http.client.HTTPConnection(*server.server_address, timeout=3)
                connection.request('GET', f'/mac/{UPLOAD}-RobloxPlayer.zip', headers={'Cookie': 'private', 'Authorization': 'secret'})
                result = connection.getresponse()
                self.assertEqual(result.status, 200)
                self.assertEqual(result.read(), archive())
                self.assertEqual(opener.call_args.args, (f'https://setup.rbxcdn.com/mac/{UPLOAD}-RobloxPlayer.zip', 60))
                connection.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(3)
