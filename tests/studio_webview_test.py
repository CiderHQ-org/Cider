"""The WebView2 runtime in Studio's prefix: download, checksum, install order."""
import base64
import hashlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock

from quadra import studio_webview as webview

INSTALLER = b'MZ the WebView2 runtime installer'
SHA256 = hashlib.sha256(INSTALLER).hexdigest()
VERSION = webview.VERSION


class Response(io.BytesIO):
    pass


def download_info(version=VERSION, body=INSTALLER):
    digest = base64.b64encode(hashlib.sha256(body).digest()).decode()
    entry = lambda name, size: {'FileId': name, 'SizeInBytes': size, 'Url': f'http://cdn.test/{name}',
                                'Hashes': {'Sha256': digest}}
    return [entry(f'MicrosoftEdge_X64_{version}_143.0.3650.96.exe', 61), entry(f'MicrosoftEdge_X64_{version}.exe', len(body)),
            entry(f'MicrosoftEdge_X64_{version}_144.0.3719.82.exe', 13)]


class RuntimeDownloadTests(unittest.TestCase):
    def test_the_full_runtime_is_chosen_not_an_update_from_an_older_one(self):
        seen = []

        def opener(request, timeout=0, context=None):
            seen.append((request.full_url, request.get_method(), context is not None))
            return Response(json.dumps(download_info()).encode())

        info = webview.runtime_download(VERSION, opener)
        self.assertEqual(info, {'url': f'http://cdn.test/MicrosoftEdge_X64_{VERSION}.exe', 'size': len(INSTALLER),
                                'sha256': SHA256})
        url, method, trusts_microsoft = seen[0]
        self.assertTrue(url.endswith(f'/versions/{VERSION}/files?action=GenerateDownloadInfo'))
        self.assertEqual((method, trusts_microsoft), ('POST', True))

    def test_a_version_microsoft_does_not_have_is_a_clear_error(self):
        opener = lambda *a, **k: Response(json.dumps(download_info('9.9.9.9')[:1]).encode())
        with self.assertRaisesRegex(RuntimeError, '144'):
            webview.runtime_download(VERSION, opener)

    def test_microsofts_root_certificate_is_trusted_next_to_the_systems(self):
        context = webview._context()
        self.assertTrue(any('Microsoft Root Certificate Authority 2011' in str(cert) for cert in context.get_ca_certs()))
        self.assertGreater(len(context.get_ca_certs()), 1)

    def test_studios_gpu_process_follows_the_renderer(self):
        self.assertEqual(webview.browser_arguments('dxvk'), '--in-process-gpu --use-angle=vulkan')
        self.assertEqual(webview.browser_arguments('vulkan'), '--in-process-gpu --use-angle=vulkan')
        self.assertEqual(webview.browser_arguments('d3d11fl10'), '--in-process-gpu --use-angle=gl')


class InstallTests(unittest.TestCase):
    def setUp(self):
        base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        self.prefix, self.cache = base / 'prefix', base / 'cache'
        self.prefix.mkdir()
        (self.prefix / 'user.reg').write_text('')
        self.set_installed('')
        self.commands = []
        self.progress = Mock()
        info = {'url': 'http://cdn.test/x.exe', 'size': len(INSTALLER), 'sha256': SHA256}
        self.runtime = unittest.mock.patch.object(webview, 'runtime_download', return_value=info)
        self.runtime.start()
        self.addCleanup(self.runtime.stop)

    def set_installed(self, version):
        text = ''
        if version:
            text = (r'[Software\\Wow6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\Microsoft EdgeWebView] 1'
                    f'\n"DisplayVersion"="{version}"\n')
        (self.prefix / 'system.reg').write_text(text)

    def wine(self, *arguments):
        self.commands.append(arguments)
        if arguments and arguments[0].endswith('.exe') and 'webview-' in arguments[0] and not self.fail_install:
            self.set_installed(VERSION)

    fail_install = False

    def download(self, body=INSTALLER):
        def fetch(url, target, progress, label, digest):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
            digest.update(body)
        self.fetch = Mock(side_effect=fetch)
        return self.fetch

    def test_the_runtime_is_downloaded_checked_and_installed_with_windows_7_behaviour(self):
        webview.ensure(self.prefix, self.wine, self.download(), self.cache, VERSION, self.progress)
        self.fetch.assert_called_once()
        self.assertEqual(self.commands[0][:3], ('reg', 'add', webview.APPDEFAULTS))
        self.assertIn('win7', self.commands[0])
        installer = self.cache / f'webview-{VERSION}.exe'
        self.assertEqual(self.commands[1], (str(installer), *webview.INSTALL_ARGUMENTS))
        self.assertEqual(webview.installed(self.prefix), VERSION)

    def test_nothing_happens_when_the_version_is_installed(self):
        self.set_installed(VERSION)
        self.assertFalse(webview.ensure(self.prefix, self.wine, self.download(), self.cache, VERSION, self.progress))
        self.assertEqual(self.commands, [])
        self.runtime.target.runtime_download.assert_not_called()

    def test_a_download_that_fails_its_checksum_is_not_installed_and_not_kept(self):
        with self.assertRaisesRegex(RuntimeError, 'checksum'):
            webview.ensure(self.prefix, self.wine, self.download(b'tampered'), self.cache, VERSION, self.progress)
        self.assertEqual(self.commands, [])
        self.assertFalse((self.cache / f'webview-{VERSION}.exe').exists())

    def test_a_verified_download_from_before_is_reused_and_a_damaged_one_is_fetched_again(self):
        self.cache.mkdir()
        (self.cache / f'webview-{VERSION}.exe').write_bytes(INSTALLER)
        webview.ensure(self.prefix, self.wine, self.download(), self.cache, VERSION, self.progress)
        self.fetch.assert_not_called()
        self.set_installed('')
        (self.cache / f'webview-{VERSION}.exe').write_bytes(b'half a download')
        webview.ensure(self.prefix, self.wine, self.download(), self.cache, VERSION, self.progress)
        self.fetch.assert_called_once()

    def test_another_version_is_uninstalled_first(self):
        self.set_installed('100.0.1.1')
        webview.ensure(self.prefix, self.wine, self.download(), self.cache, VERSION, self.progress)
        removal = self.commands[0]
        self.assertTrue(removal[0].endswith('Application/100.0.1.1/Installer/setup.exe'))
        self.assertEqual(removal[1:], ('--msedgewebview', '--uninstall', '--system-level', '--force-uninstall'))

    def test_the_windows_version_is_not_set_twice(self):
        (self.prefix / 'user.reg').write_text(r'[Software\\Wine\\AppDefaults\\msedgewebview2.exe] 1' '\n"Version"="win7"\n')
        webview.ensure(self.prefix, self.wine, self.download(), self.cache, VERSION, self.progress)
        self.assertFalse(any(command[:1] == ('reg',) for command in self.commands))

    def test_an_installer_that_leaves_nothing_behind_is_an_error(self):
        self.fail_install = True
        with self.assertRaisesRegex(RuntimeError, 'did not install'):
            webview.ensure(self.prefix, self.wine, self.download(), self.cache, VERSION, self.progress)


if __name__ == '__main__':
    unittest.main()
