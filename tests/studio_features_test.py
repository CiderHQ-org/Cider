"""Studio's settings in action: renderer, DXVK, flags, overlay, backup, prefix, install order, supervisor.

Wine is replaced by a script that records what it is asked to do and imitates
`wineboot` and `reg export`; nothing here starts a real Wine."""
import io
import json
import os
from pathlib import Path
import shutil
import stat
import tarfile
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from quadra import core, studio, studio_deploy

FAKE_WINE = '''#!/usr/bin/env python3
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
log = Path(os.environ["FAKE_WINE_LOG"])
entry = {"args": args}
if args[:1] == ["regedit"]:
    entry["regedit"] = Path(args[2][2:].replace("\\\\", "/")).read_text()
with log.open("a") as out:
    out.write(json.dumps(entry) + "\\n")
if args[:1] == ["wineboot"]:
    (Path(os.environ["WINEPREFIX"]) / "system.reg").write_text("fake")
if args[:2] == ["reg", "export"]:
    if args[2] in os.environ.get("FAKE_MISSING_KEYS", "").split(";"):
        sys.exit(1)
    Path(args[3][2:].replace("\\\\", "/")).write_text("exported " + args[2])
'''
FAKE_WINESERVER = '''#!/usr/bin/env python3
import json, os, sys
with open(os.environ["FAKE_WINE_LOG"], "a") as out:
    out.write(json.dumps({"wineserver": sys.argv[1:]}) + "\\n")
'''


class StudioFixture(unittest.TestCase):
    def setUp(self):
        base = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        self.base = base
        self.root = base / 'studio'
        paths = {
            'ROOT': self.root, 'WINE': self.root / 'wine', 'PREFIX': self.root / 'prefix',
            'APP': self.root / 'prefix/drive_c/Program Files/Roblox Studio',
            'EXECUTABLE': self.root / 'prefix/drive_c/Program Files/Roblox Studio/RobloxStudioBeta.exe',
            'STATE': self.root / 'state.json', 'BACKUPS': self.root / 'backup', 'APPDATA': self.root / 'appdata',
            'SUPERVISOR_LOCK': self.root / 'supervisor.lock', 'OVERLAY': base / 'overlay',
        }
        for name, value in paths.items():
            patcher = patch.object(studio, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name, value in {'DOWNLOADS': base / 'downloads', 'LOGS': base / 'logs', 'CACHE_DIR': base / 'cache',
                            'SHIM_DIR': base / 'shim'}.items():
            patcher = patch.object(core, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.log = base / 'wine.log'
        patcher = patch.dict(os.environ, {'FAKE_WINE_LOG': str(self.log)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.progress = Mock()
        studio.APP.mkdir(parents=True)
        (studio.WINE / 'bin').mkdir(parents=True)
        for name, text in (('wine', FAKE_WINE), ('wineserver', FAKE_WINESERVER)):
            program = studio.WINE / 'bin' / name
            program.write_text(text)
            program.chmod(program.stat().st_mode | stat.S_IEXEC)

    def calls(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def wine_commands(self):
        return [call['args'] for call in self.calls() if 'args' in call]

    def options(self, **settings):
        return studio.Options({f'studio_{key}': value for key, value in settings.items()})


class OptionsTests(StudioFixture):
    def test_unusable_values_fall_back_to_their_defaults(self):
        options = studio.Options({'studio_renderer': 'metal', 'studio_version': 'latest', 'studio_channel': 'a b',
                                  'studio_gamemode': 'yes', 'studio_fflags': ['x'], 'studio_wine': 7})
        self.assertEqual((options.renderer, options.version, options.channel, options.gamemode, options.fflags, options.wine),
                         ('dxvk', '', '', True, {}, ''))

    def test_good_values_are_kept(self):
        options = self.options(renderer='vulkan', version='version-0123456789abcdef', channel='zintegration',
                               gamemode=False, fflags={'FFlagA': 1, '': 2}, wine=' stable+1 ', gpu='pci:0000:01:00.0')
        self.assertEqual((options.renderer, options.version, options.channel, options.gamemode, options.wine, options.gpu),
                         ('vulkan', 'version-0123456789abcdef', 'zintegration', False, 'stable+1', 'pci:0000:01:00.0'))
        self.assertEqual(options.fflags, {'FFlagA': 1}, 'a flag needs a name')

    def test_only_the_dxvk_renderers_use_dxvk(self):
        self.assertEqual([self.options(renderer=name).dxvk for name in studio.RENDERERS],
                         ['dxvk', 'sarek', None, None, None])


class EnvironmentTests(StudioFixture):
    def test_dxvk_renderers_override_the_direct3d_dlls_and_the_others_do_not(self):
        self.assertIn('d3d11,dxgi=n,b', studio._wine_env(self.options(renderer='dxvk'))['WINEDLLOVERRIDES'])
        for name in ('d3d11', 'd3d11fl10', 'vulkan'):
            self.assertNotIn('=n,b', studio._wine_env(self.options(renderer=name))['WINEDLLOVERRIDES'])

    def test_wine_and_webview_use_the_backend_of_the_renderer(self):
        for name, backend in (('dxvk', 'vulkan'), ('d3d11', 'gl'), ('d3d11fl10', 'gl'), ('vulkan', 'vulkan')):
            env = studio._wine_env(self.options(renderer=name))
            self.assertEqual(env['WINE_D3D_CONFIG'], f'renderer={backend}')
            self.assertEqual(env['WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS'], f'--in-process-gpu --use-angle={backend}')
        self.assertNotIn('WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS', studio._wine_env(self.options(webview=False)))

    def test_studios_log_is_only_asked_for_when_launching(self):
        self.assertIn('warn+seh', studio._wine_env(self.options(), launching=True)['WINEDEBUG'])
        self.assertEqual(studio._wine_env(self.options())['WINEDEBUG'], '-all')

    def test_the_vulkan_layer_is_enabled_only_when_it_was_built(self):
        self.assertNotIn('VK_INSTANCE_LAYERS', studio._wine_env(self.options(renderer='vulkan')))
        core.SHIM_DIR.mkdir()
        (core.SHIM_DIR / 'libquadra-studio-layer.so').write_text('')
        env = studio._wine_env(self.options(renderer='vulkan'))
        self.assertEqual(env['VK_INSTANCE_LAYERS'], 'VK_LAYER_QUADRA_studio')
        manifest = json.loads((Path(env['VK_LAYER_PATH']) / 'VkLayer_QUADRA_studio.json').read_text())
        self.assertEqual(manifest['layer']['library_path'], str(core.SHIM_DIR / 'libquadra-studio-layer.so'))
        self.assertNotIn('VK_INSTANCE_LAYERS', studio._wine_env(self.options(renderer='dxvk')))

    def test_the_chosen_gpu_reaches_the_launch_and_a_missing_one_does_not_stop_it(self):
        with patch.object(studio.gpus, 'selected_gpu', return_value={'pci': 'x'}) as select, \
                patch.object(studio.gpus, 'gpu_environment', return_value={'DRI_PRIME': 'pci-0000_01_00_0!'}) as build:
            env = studio._wine_env(self.options(gpu='pci:0000:01:00.0'), launching=True)
        select.assert_called_once_with('pci:0000:01:00.0')
        build.assert_called_once_with({'pci': 'x'}, 'vulkan')
        self.assertEqual(env['DRI_PRIME'], 'pci-0000_01_00_0!')
        with patch.object(studio.gpus, 'selected_gpu', side_effect=RuntimeError('unplugged')):
            env = studio._wine_env(self.options(gpu='pci:0000:09:00.0'), launching=True)
        self.assertNotIn('DRI_PRIME', env.keys() - os.environ.keys())
        with patch.object(studio.gpus, 'selected_gpu', return_value={'pci': 'x'}), \
                patch.object(studio.gpus, 'gpu_environment', return_value={}) as build:
            studio._wine_env(self.options(renderer='d3d11', gpu='pci:0000:01:00.0'), launching=True)
        self.assertEqual(build.call_args.args[1], 'opengl', "Wine's own Direct3D draws through OpenGL")

    def test_a_wine_folder_of_your_own_replaces_the_managed_one_only_when_it_is_usable(self):
        custom = self.base / 'my-wine'
        (custom / 'bin').mkdir(parents=True)
        self.assertEqual(studio.wine_root(self.options(wine_root=str(custom))), studio.WINE, 'no bin/wine yet')
        (custom / 'bin' / 'wine').write_text('')
        self.assertEqual(studio.wine_root(self.options(wine_root=str(custom))), custom)
        self.assertEqual(studio.wine_root(self.options()), studio.WINE)


class FilesTests(StudioFixture):
    def flags(self):
        return json.loads((studio.APP / 'ClientSettings' / 'ClientAppSettings.json').read_text())

    def test_the_renderer_decides_the_graphics_api_whatever_the_user_flags_say(self):
        studio._apply_files(self.options(renderer='vulkan', fflags={'FFlagDebugGraphicsPreferD3D11': True,
                                                                     'FIntFramerateCap': 120}))
        flags = self.flags()
        self.assertTrue(flags['FFlagDebugGraphicsPreferVulkan'])
        self.assertFalse(flags['FFlagDebugGraphicsPreferD3D11'])
        self.assertTrue(flags['FFlagDebugGraphicsDisableD3D11'])
        self.assertFalse(flags['FFlagDebugGraphicsDisableVulkan'])
        self.assertEqual(flags['FIntFramerateCap'], 120)

    def test_dxvk_and_wines_direct3d_both_ask_studio_for_direct3d_11(self):
        for name, api in (('dxvk', 'D3D11'), ('dxvk-sarek', 'D3D11'), ('d3d11', 'D3D11'), ('d3d11fl10', 'D3D11FL10')):
            studio._apply_files(self.options(renderer=name))
            self.assertTrue(self.flags()[f'FFlagDebugGraphicsPrefer{api}'], name)

    def test_the_overlay_is_copied_over_studio_and_the_flags_win_over_it(self):
        (studio.OVERLAY / 'content/textures').mkdir(parents=True)
        (studio.OVERLAY / 'content/textures/sky.png').write_text('mine')
        (studio.OVERLAY / 'ClientSettings').mkdir()
        (studio.OVERLAY / 'ClientSettings/ClientAppSettings.json').write_text('{"FFlagFromOverlay": true}')
        studio._apply_files(self.options())
        self.assertEqual((studio.APP / 'content/textures/sky.png').read_text(), 'mine')
        self.assertNotIn('FFlagFromOverlay', self.flags())
        self.assertIn('FFlagDebugGraphicsPreferD3D11', self.flags())

    def test_no_overlay_is_fine(self):
        studio._apply_files(self.options())
        self.assertFalse(studio.OVERLAY.exists())


def dxvk_archive(top='dxvk-3.1.1'):
    data = io.BytesIO()
    with tarfile.open(fileobj=data, mode='w:gz') as archive:
        for folder in ('x64', 'x32'):
            for name in ('d3d9.dll', 'd3d10core.dll', 'd3d11.dll', 'dxgi.dll', 'README.txt'):
                body = f'{top} {folder} {name}'.encode()
                member = tarfile.TarInfo(f'{top}/{folder}/{name}')
                member.size = len(body)
                archive.addfile(member, io.BytesIO(body))
    return data.getvalue()


class GraphicsTests(StudioFixture):
    def serve(self, body):
        """Stands in for the download of a DXVK archive."""
        def fetch(url, target, progress=None, label='', digest=None):
            self.downloads.append(url)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
        self.downloads = []
        patcher = patch.object(studio, '_download', fetch)
        patcher.start()
        self.addCleanup(patcher.stop)

    def dlls(self):
        return sorted(path.name for path in studio.APP.glob('*.dll'))

    def test_dxvks_64_bit_dlls_go_next_to_studio_and_only_those(self):
        self.serve(dxvk_archive())
        state = {}
        with patch.object(studio, '_latest_tag', return_value='v3.1.1'):
            studio._ensure_graphics(state, self.progress, self.options())
        self.assertEqual(self.dlls(), ['d3d10core.dll', 'd3d11.dll', 'd3d9.dll', 'dxgi.dll'])
        self.assertEqual((studio.APP / 'd3d11.dll').read_text(), 'dxvk-3.1.1 x64 d3d11.dll')
        self.assertEqual(state['dxvk_applied'], 'dxvk-v3.1.1')
        self.assertTrue(self.downloads[0].endswith('/v3.1.1/dxvk-3.1.1.tar.gz'))

    def test_nothing_is_fetched_again_while_it_is_current_and_the_archive_is_kept_for_a_switch_back(self):
        self.serve(dxvk_archive())
        state = {}
        with patch.object(studio, '_latest_tag', return_value='v3.1.1'):
            studio._ensure_graphics(state, self.progress, self.options())
            studio._ensure_graphics(state, self.progress, self.options())
            self.assertEqual(len(self.downloads), 1)
            studio._ensure_graphics(state, self.progress, self.options(renderer='d3d11'))
            self.assertEqual(self.dlls(), [])
            self.assertNotIn('dxvk_applied', state)
            studio._ensure_graphics(state, self.progress, self.options())
        self.assertEqual(len(self.downloads), 1, 'the cached archive serves the switch back')
        self.assertEqual(len(self.dlls()), 4)

    def test_a_new_dxvk_release_replaces_the_old_dlls(self):
        self.serve(dxvk_archive('dxvk-3.1.1'))
        state = {}
        with patch.object(studio, '_latest_tag', return_value='v3.1.1'):
            studio._ensure_graphics(state, self.progress, self.options())
        self.serve(dxvk_archive('dxvk-3.2'))
        with patch.object(studio, '_latest_tag', return_value='v3.2'):
            studio._ensure_graphics(state, self.progress, self.options())
        self.assertEqual((studio.APP / 'd3d11.dll').read_text(), 'dxvk-3.2 x64 d3d11.dll')

    def test_sarek_is_the_pinned_async_build(self):
        self.serve(dxvk_archive('dxvk-sarek-async-v1.11.0'))
        state = {}
        studio._ensure_graphics(state, self.progress, self.options(renderer='dxvk-sarek'))
        self.assertEqual(self.downloads, [studio.SAREK_URL])
        self.assertIn('dxvk-sarek-async-v1.11.0.tar.gz', studio.SAREK_URL)
        self.assertEqual(state['dxvk_applied'], 'sarek-1.11.0')

    def test_offline_keeps_the_dxvk_that_is_installed_and_fails_without_one(self):
        self.serve(dxvk_archive())
        state = {}
        with patch.object(studio, '_latest_tag', side_effect=OSError('offline')):
            with self.assertRaises(OSError):
                studio._ensure_graphics(state, self.progress, self.options())
        with patch.object(studio, '_latest_tag', return_value='v3.1.1'):
            studio._ensure_graphics(state, self.progress, self.options())
        with patch.object(studio, '_latest_tag', side_effect=OSError('offline')):
            studio._ensure_graphics(state, self.progress, self.options())
        self.assertEqual(len(self.dlls()), 4)

    def test_dxvk_dlls_left_in_the_prefix_by_earlier_versions_are_removed(self):
        system32 = studio.PREFIX / 'drive_c/windows/system32'
        system32.mkdir(parents=True)
        (system32 / 'd3d11.dll').write_bytes(b'MZ DXVK 2.7')
        (system32 / 'dxgi.dll').write_bytes(b'MZ DXVK 2.7')
        (system32 / 'kernel32.dll').write_bytes(b'MZ wine')
        studio._remove_prefix_dxvk(self.options())
        self.assertEqual(sorted(path.name for path in system32.iterdir()), ['kernel32.dll'])
        self.assertIn(['wineboot', '-u'], self.wine_commands())

    def test_wines_own_direct3d_dll_is_left_alone(self):
        system32 = studio.PREFIX / 'drive_c/windows/system32'
        system32.mkdir(parents=True)
        (system32 / 'd3d11.dll').write_bytes(b'MZ wine builtin')
        studio._remove_prefix_dxvk(self.options())
        self.assertTrue((system32 / 'd3d11.dll').exists())
        self.assertEqual(self.wine_commands(), [])


class BackupTests(StudioFixture):
    def setUp(self):
        super().setUp()
        (studio.PREFIX / 'system.reg').write_text('prefix')

    def test_sign_in_and_settings_are_saved_privately(self):
        self.assertTrue(studio.backup_settings(self.options()))
        self.assertEqual(sorted(path.name for path in studio.BACKUPS.iterdir()), ['credentials.reg', 'studio.reg'])
        self.assertEqual(stat.S_IMODE(studio.BACKUPS.stat().st_mode), 0o700)
        for path in studio.BACKUPS.iterdir():
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual((studio.BACKUPS / 'studio.reg').read_text(), r'exported HKCU\Software\Roblox\RobloxStudio')

    def test_a_key_that_does_not_exist_yet_is_skipped_and_leaves_an_older_backup_alone(self):
        studio.backup_settings(self.options())
        with patch.dict(os.environ, {'FAKE_MISSING_KEYS': studio.BACKUP_KEYS['credentials']}):
            (studio.BACKUPS / 'studio.reg').write_text('old')
            studio.backup_settings(self.options())
        self.assertEqual((studio.BACKUPS / 'credentials.reg').read_text(), r'exported HKCU\Software\Wine\Credential Manager')
        self.assertEqual(sorted(path.name for path in studio.BACKUPS.iterdir()), ['credentials.reg', 'studio.reg'])

    def test_there_is_nothing_to_back_up_without_a_prefix(self):
        (studio.PREFIX / 'system.reg').unlink()
        self.assertFalse(studio.backup_settings(self.options()))
        self.assertFalse(studio.BACKUPS.exists())

    def test_a_saved_backup_is_imported_into_a_new_prefix(self):
        studio.backup_settings(self.options())
        self.log.unlink()
        self.assertTrue(studio.restore_settings(self.options()))
        imports = [args for args in self.wine_commands() if args[:2] == ['reg', 'import']]
        self.assertEqual(len(imports), 2)
        self.assertTrue(all(args[2].startswith('Z:\\') for args in imports))

    def test_restoring_with_no_backup_does_nothing(self):
        self.assertFalse(studio.restore_settings(self.options()))
        self.assertEqual(self.wine_commands(), [])


class PrefixTests(StudioFixture):
    def test_a_new_prefix_gets_its_folders_and_the_saved_sign_in(self):
        shutil.rmtree(studio.PREFIX)
        studio.BACKUPS.mkdir(parents=True)
        (studio.BACKUPS / 'studio.reg').write_text('saved')
        state = {'wine': 'stable+1'}
        studio._ensure_prefix(state, self.progress, self.options())
        commands = self.wine_commands()
        self.assertEqual(commands[0], ['wineboot', '--init'])
        regedit = [call['regedit'] for call in self.calls() if 'regedit' in call][0]
        self.assertIn(str(studio.APPDATA).replace('/', '\\\\'), regedit)
        self.assertIn('"Local AppData"', regedit)
        self.assertTrue(any(args[:2] == ['reg', 'import'] for args in commands))
        self.assertIn({'wineserver': ['-k']}, self.calls())
        self.assertEqual(state['prefix'], 'stable+1')
        self.assertTrue(studio.APPDATA.is_dir())

    def test_an_existing_prefix_of_the_same_wine_is_left_alone(self):
        (studio.PREFIX / 'system.reg').write_text('x')
        state = {'wine': 'stable+1', 'prefix': 'stable+1'}
        studio._ensure_prefix(state, self.progress, self.options())
        self.assertEqual(self.wine_commands(), [])

    def test_dxvk_left_in_the_prefix_is_removed_even_when_wine_did_not_change(self):
        system32 = studio.PREFIX / 'drive_c/windows/system32'
        system32.mkdir(parents=True)
        (studio.PREFIX / 'system.reg').write_text('x')
        (system32 / 'd3d11.dll').write_bytes(b'MZ DXVK 2.7')
        state = {'wine': 'stable+1', 'prefix': 'stable+1', 'dxvk': 'v2.7'}
        studio._ensure_prefix(state, self.progress, self.options())
        self.assertFalse((system32 / 'd3d11.dll').exists())
        self.assertNotIn('dxvk', state)
        self.assertEqual(self.wine_commands(), [['wineboot', '-u']], 'one update, after the DLLs were removed')

    def test_a_new_wine_updates_the_prefix_without_touching_its_folders_or_sign_in(self):
        (studio.PREFIX / 'system.reg').write_text('x')
        state = {'wine': 'stable+2', 'prefix': 'stable+1', 'dxvk_applied': 'dxvk-v3'}
        studio._ensure_prefix(state, self.progress, self.options())
        commands = self.wine_commands()
        self.assertEqual(commands, [['wineboot', '-u']])
        self.assertEqual(state['prefix'], 'stable+2')

    def test_a_wine_folder_of_your_own_is_its_own_identity(self):
        custom = self.base / 'my-wine'
        for name, text in (('wine', FAKE_WINE), ('wineserver', FAKE_WINESERVER)):
            (custom / 'bin').mkdir(parents=True, exist_ok=True)
            (custom / 'bin' / name).write_text(text)
            (custom / 'bin' / name).chmod(0o755)
        (studio.PREFIX / 'system.reg').write_text('x')
        state = {'wine': 'stable+1', 'prefix': 'stable+1'}
        studio._ensure_prefix(state, self.progress, self.options(wine_root=str(custom)))
        self.assertEqual(state['prefix'], f'custom:{custom}')
        self.assertEqual(self.wine_commands(), [['wineboot', '-u']])

    def test_the_theme_follows_the_system_and_is_only_applied_when_it_changes(self):
        state = {}
        studio._apply_theme(state, self.options(), dark=True)
        studio._apply_theme(state, self.options(), dark=True)
        studio._apply_theme(state, self.options(), dark=False)
        applied = [call['regedit'] for call in self.calls() if 'regedit' in call]
        self.assertEqual(len(applied), 2)
        self.assertIn('"AppsUseLightTheme"=dword:00000000', applied[0])
        self.assertIn('"AppsUseLightTheme"=dword:00000001', applied[1])
        self.assertEqual(state['theme'], 'light')

    def test_the_theme_is_left_alone_when_switched_off(self):
        studio._apply_theme({}, self.options(theme=False), dark=True)
        self.assertEqual(self.wine_commands(), [])


class InstallTests(StudioFixture):
    """The order of the steps, and what a missing connection may skip."""

    def setUp(self):
        super().setUp()
        self.order = []
        for name in ('_ensure_wine', '_ensure_prefix', '_ensure_webview', '_install_studio', '_ensure_graphics'):
            patcher = patch.object(studio, name, side_effect=lambda *a, _name=name, **k: self.order.append(_name))
            patcher.start()
            self.addCleanup(patcher.stop)

    def settings(self, **values):
        return dict(core.DEFAULT_SETTINGS, **{f'studio_{key}': value for key, value in values.items()})

    def test_everything_installs_in_dependency_order(self):
        with patch.object(studio, 'deployment', return_value=('version-aaaaaaaaaaaaaaaa', '')):
            studio.install(self.progress, self.settings())
        self.assertEqual(self.order, ['_ensure_wine', '_ensure_prefix', '_ensure_webview', '_install_studio',
                                      '_ensure_graphics'], 'DXVK goes in after Studio, which replaces its folder')

    def test_no_download_of_wine_or_webview_when_they_are_not_wanted(self):
        custom = self.base / 'my-wine'
        (custom / 'bin').mkdir(parents=True)
        (custom / 'bin' / 'wine').write_text('')
        with patch.object(studio, 'deployment', return_value=('version-aaaaaaaaaaaaaaaa', '')):
            studio.install(self.progress, self.settings(wine_root=str(custom), webview=False))
        self.assertEqual(self.order, ['_ensure_prefix', '_install_studio', '_ensure_graphics'])

    def test_an_up_to_date_studio_is_not_downloaded_again(self):
        studio.EXECUTABLE.write_text('')
        studio._save_state({'studio': 'version-aaaaaaaaaaaaaaaa', 'channel': ''})
        with patch.object(studio, 'deployment', return_value=('version-aaaaaaaaaaaaaaaa', '')):
            studio.install(self.progress, self.settings())
        self.assertNotIn('_install_studio', self.order)

    def test_changing_the_channel_installs_that_channels_studio(self):
        studio.EXECUTABLE.write_text('')
        studio._save_state({'studio': 'version-aaaaaaaaaaaaaaaa', 'channel': ''})
        with patch.object(studio, 'deployment', return_value=('version-aaaaaaaaaaaaaaaa', 'zintegration')):
            studio.install(self.progress, self.settings(channel='zintegration'))
        self.assertIn('_install_studio', self.order)

    def test_offline_the_installed_studio_is_kept_and_the_rest_still_runs(self):
        studio.EXECUTABLE.write_text('')
        studio._save_state({'studio': 'version-aaaaaaaaaaaaaaaa'})
        with patch.object(studio, 'deployment', side_effect=OSError('offline')):
            studio.install(self.progress, self.settings())
        self.assertNotIn('_install_studio', self.order)
        self.assertIn('_ensure_graphics', self.order)

    def test_offline_without_studio_is_an_error(self):
        with patch.object(studio, 'deployment', side_effect=OSError('offline')):
            with self.assertRaises(OSError):
                studio.install(self.progress, self.settings())

    def test_a_channel_that_does_not_exist_is_reported_not_skipped(self):
        studio.EXECUTABLE.write_text('')
        studio._save_state({'studio': 'version-aaaaaaaaaaaaaaaa'})
        with patch.object(studio, 'deployment', side_effect=studio_deploy.BadChannel('nowhere')):
            with self.assertRaisesRegex(studio.ChannelError, 'nowhere'):
                studio.install(self.progress, self.settings(channel='nowhere'))

    def test_progress_runs_from_nothing_to_done(self):
        with patch.object(studio, 'deployment', return_value=('version-aaaaaaaaaaaaaaaa', '')):
            studio.install(self.progress, self.settings())
        self.assertEqual(self.progress.call_args.args[0], 1)


class SupervisorTests(StudioFixture):
    def process(self, log_lines=b''):
        log = self.base / 'studio.log'
        log.write_bytes(log_lines)
        process = Mock(pid=4242, log_path=log)
        process.wait.side_effect = lambda: None
        return process

    def test_only_the_first_supervisor_gets_the_lock(self):
        first = studio._supervisor_lock()
        self.assertIsNotNone(first)
        self.assertIsNone(studio._supervisor_lock())
        first.close()
        second = studio._supervisor_lock()
        self.assertIsNotNone(second)
        second.close()

    def test_gamemode_is_asked_for_and_the_backup_taken_when_studio_ends(self):
        (studio.PREFIX / 'system.reg').write_text('x')
        with patch.object(studio.studio_gamemode, 'register') as register:
            studio.supervise(self.process(), self.options(discord=False))
            threading.Event().wait(0.1)
        register.assert_called_once_with(4242)
        self.assertTrue((studio.BACKUPS / 'studio.reg').exists())
        self.assertIn({'wineserver': ['--wait']}, self.calls())

    def test_gamemode_and_backup_can_be_switched_off(self):
        (studio.PREFIX / 'system.reg').write_text('x')
        with patch.object(studio.studio_gamemode, 'register') as register:
            studio.supervise(self.process(), self.options(discord=False, gamemode=False, backup=False))
        register.assert_not_called()
        self.assertFalse(studio.BACKUPS.exists())

    def test_studios_log_lines_reach_discord_presence_as_they_are_written(self):
        from quadra import studio_presence
        lines = []
        presence = Mock(spec=studio_presence.StudioPresence)
        presence.feed.side_effect = lines.append
        log = self.base / 'follow.log'
        log.write_bytes(b'noise that is not a Studio log\n')
        stop = threading.Event()
        follower = threading.Thread(target=studio._follow, args=(log, presence.feed, stop))
        follower.start()
        def wait_for(count):
            for _attempt in range(100):  # up to 10 s: the follower looks every 0.3 s
                if len(lines) >= count:
                    return
                threading.Event().wait(0.1)
            self.fail(f'only {len(lines)} of {count} log lines arrived')

        with log.open('ab') as out:
            out.write(b'0024:warn:seh:dispatch_exception "2026,0,1,6 [FLog::CloseDataModel] Setting place ID 5"\n')
            out.write(b'half a line [FLog::Output] not ')
            out.flush()
            wait_for(1)
            self.assertEqual(len(lines), 1, 'a line that is not finished is not passed on')
            out.write(b'finished yet\n')
            out.flush()
            wait_for(2)
        stop.set()
        follower.join(5)
        self.assertEqual([line.split('] ')[1] for line in lines], ['Setting place ID 5"', 'not finished yet'])

    def test_a_studio_that_is_not_running_is_updated_first_and_one_that_is_running_is_not(self):
        with patch.object(studio, 'running', return_value=False), patch.object(studio, 'install') as install, \
                patch.object(studio, 'launch') as launch, patch.object(studio, 'supervise') as supervise:
            studio.run(['roblox-studio:1'], core.DEFAULT_SETTINGS)
        install.assert_called_once()
        launch.assert_called_once()
        supervise.assert_called_once()
        with patch.object(studio, 'running', return_value=True), patch.object(studio, 'install') as install, \
                patch.object(studio, 'launch'), patch.object(studio, 'supervise'):
            studio.run(['roblox-studio-auth:x'], core.DEFAULT_SETTINGS)
        install.assert_not_called()

    def test_a_second_start_hands_over_without_a_second_supervisor(self):
        held = studio._supervisor_lock()
        self.addCleanup(held.close)
        with patch.object(studio, 'running', return_value=True), patch.object(studio, 'launch') as launch, \
                patch.object(studio, 'supervise') as supervise:
            studio.run(['roblox-studio-auth:x'], core.DEFAULT_SETTINGS)
        launch.assert_called_once()
        supervise.assert_not_called()

    def test_an_update_that_fails_does_not_stop_an_installed_studio(self):
        studio.EXECUTABLE.write_text('')
        studio._save_state({'studio': 'version-a', 'wine': 'stable+1'})
        with patch.object(studio, 'running', return_value=False), \
                patch.object(studio, 'install', side_effect=OSError('offline')), \
                patch.object(studio, 'launch') as launch, patch.object(studio, 'supervise'):
            studio.run([], core.DEFAULT_SETTINGS)
        launch.assert_called_once()

    def test_the_launcher_window_starts_a_supervisor_process_of_its_own(self):
        with patch.object(studio.subprocess, 'Popen') as popen:
            studio.spawn(['roblox-studio:1'])
        command = popen.call_args.args[0]
        self.assertEqual(command[2:5], ['--studio', '--no-update', 'roblox-studio:1'])
        self.assertTrue(command[1].endswith('quadrahq-launcher'))
        self.assertTrue(popen.call_args.kwargs['start_new_session'])


class LaunchTests(StudioFixture):
    def test_launch_writes_the_flags_starts_wine_in_studios_folder_and_logs(self):
        studio.EXECUTABLE.write_text('')
        place = self.base / 'place.rbxl'
        place.write_text('')
        process = studio.launch([str(place), 'roblox-studio:1'], dict(core.DEFAULT_SETTINGS, studio_theme=False))
        process.wait(10)
        self.assertTrue((studio.APP / 'ClientSettings/ClientAppSettings.json').exists())
        self.assertEqual(process.log_path.parent, core.LOGS)
        self.assertEqual(self.wine_commands()[-1][0], str(studio.EXECUTABLE))
        self.assertEqual(self.wine_commands()[-1][1:], ['Z:' + str(place).replace('/', '\\'), 'roblox-studio:1'],
                         'a place file is passed as a Windows path, a link as it is')

    def test_only_the_ten_newest_logs_are_kept(self):
        studio.EXECUTABLE.write_text('')
        core.LOGS.mkdir(parents=True)
        for number in range(14):
            path = core.LOGS / f'studio-2026010{number % 10}-00000{number}.log'
            path.write_text('x')
            os.utime(path, (1000 + number, 1000 + number))
        studio.launch([], dict(core.DEFAULT_SETTINGS, studio_theme=False)).wait(10)
        self.assertEqual(len(list(core.LOGS.glob('studio-*.log'))), 10)


if __name__ == '__main__':
    unittest.main()
