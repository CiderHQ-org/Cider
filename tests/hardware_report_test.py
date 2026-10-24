import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from macoblox import core, graphics, hardware_report


class HardwareReportTests(unittest.TestCase):
    def test_inventory_preserves_unknown_gameplay_and_never_includes_account_environment(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(core, 'DARLING_SYSROOT', Path(directory) / 'runtime/libexec/darling'), \
                patch.object(hardware_report.gpus, 'enumerate_gpus', return_value=[{'vendor': 'AMD', 'pci': '0000:04:00.0'}]), \
                patch.dict(os.environ, {'ROBLOX_TOKEN': 'private-account-secret'}):
            path = hardware_report.collect(directory, graphics=True, gameplay={'join': 'fail'})
            report = json.loads(path.read_bytes())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(report['coverage']['host_graphics'], 'unavailable')
            self.assertEqual(report['coverage']['gameplay']['join'], 'fail')
            self.assertEqual(report['coverage']['gameplay']['startup'], 'not_tested')
            self.assertNotIn('private-account-secret', path.read_text())
            self.assertNotEqual(hardware_report.collect(directory), path)

    def test_invalid_gameplay_results_cannot_be_reported_as_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            for value in ({'unknown': 'pass'}, {'join': 'yes'}):
                with self.assertRaises(ValueError):
                    hardware_report.collect(directory, gameplay=value)

    def test_failed_graphics_probe_keeps_the_report_and_does_not_mark_gameplay_passed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helpers = root / 'runtime/libexec/ciderdarling'
            helpers.mkdir(parents=True)
            for name in ('hardware-matrix.py', 'cider-gl-probe'):
                (helpers / name).touch()
            with patch.object(core, 'DARLING_SYSROOT', root / 'runtime/libexec/darling'), \
                    patch.object(hardware_report.subprocess, 'run', side_effect=OSError('probe unavailable')):
                report = json.loads(hardware_report.collect(root, graphics=True).read_bytes())
            self.assertEqual(report['coverage']['host_graphics'], 'error')
            self.assertEqual(set(report['coverage']['gameplay'].values()), {'not_tested'})


class InputReportTests(unittest.TestCase):
    def test_the_report_names_the_session_and_the_mouse_lock_lines_without_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            logs = Path(directory) / 'logs'
            logs.mkdir()
            (logs / 'launch-1.log').write_text('[Quadra Input] old\n')
            newest = logs / 'launch-2.log'
            newest.write_text('noise /home/someone/secret\n[Quadra Input] mouse lock on (native window confined)\n'
                              'x [Quadra Input] no raw motion arrived, mouse lock uses pointer deltas\n'
                              '[Quadra Input] mouse lock on (native window confined)\n'
                              '[Quadra Input] addLocalMonitorForEventsMatchingMask mask=0x800\n')
            os.utime(logs / 'launch-1.log', (1, 1))
            settings = dict(core.DEFAULT_SETTINGS, display_backend='x11', raw_mouse=True)
            with patch.object(core, 'LOGS', logs), patch.object(core, 'load_settings', return_value=settings):
                report = hardware_report._input(core)
            self.assertEqual((report['display_backend'], report['raw_mouse']), ('x11', True))
            self.assertEqual(report['log'], [
                {'line': '[Quadra Input] mouse lock on (native window confined)', 'count': 2},
                {'line': '[Quadra Input] no raw motion arrived, mouse lock uses pointer deltas', 'count': 1}])
            self.assertNotIn('secret', json.dumps(report))

    def test_a_missing_log_or_xwayland_is_reported_as_nothing(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(core, 'LOGS', Path(directory) / 'none'), \
                patch.object(core, 'load_settings', return_value=dict(core.DEFAULT_SETTINGS)):
            self.assertEqual(hardware_report._input(core)['log'], [])
        with patch.object(hardware_report.shutil, 'which', return_value=None):
            self.assertIsNone(hardware_report._xwayland_version())
        environment = {'XDG_SESSION_TYPE': 'wayland', 'XDG_CURRENT_DESKTOP': 'Hyprland', 'WAYLAND_DISPLAY': 'wayland-1'}
        with patch.object(hardware_report, '_xwayland_version', return_value='24.1.4'):
            self.assertEqual(hardware_report._desktop(environment), {
                'wayland': True, 'x11': False, 'session_type': 'wayland', 'desktop': 'Hyprland', 'xwayland': '24.1.4'})


class MetalReportTests(unittest.TestCase):
    IDENTITY = {'name': 'Test GPU', 'kind': 'discrete', 'measured': False, 'driver_info': '1.2.3'}

    def report(self, code, data, stderr=''):
        with patch.object(graphics, '_run_metal_probe', return_value=(code, data, stderr)):
            return graphics.metal_report({}, '/host.so')

    def test_a_hardware_device_that_ran_the_copy_passes(self):
        report = self.report(0, {'device': 'Test GPU', 'identity': self.IDENTITY, 'self_test': True})
        self.assertEqual((report['status'], report['self_test']), ('pass', True))
        self.assertEqual(report['identity']['driver_info'], '1.2.3')

    def test_software_failure_and_unrunnable_probes_are_told_apart(self):
        cpu = dict(self.IDENTITY, kind='cpu')
        self.assertEqual(self.report(0, {'device': 'llvmpipe', 'identity': cpu})['status'], 'software')
        self.assertEqual(self.report(0, {'device': 'lavapipe (LLVM)', 'identity': None})['status'], 'software')
        failed = self.report(1, {'error': 'Test GPU: self test: the GPU did not finish'})
        self.assertEqual((failed['status'], failed['error']), ('fail', 'Test GPU: self test: the GPU did not finish'))
        self.assertEqual(self.report(2, {}, 'boom')['error'], 'boom')
        with patch.object(graphics, '_run_metal_probe', side_effect=RuntimeError('could not open')):
            self.assertEqual(graphics.metal_report({}, '/host.so'), {'status': 'fail', 'error': 'could not open'})

    def test_the_report_includes_it_only_where_the_host_is_built(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(core, 'DARLING_SYSROOT', Path(directory) / 'runtime/libexec/darling'), \
                patch.object(hardware_report.gpus, 'enumerate_gpus', return_value=[]):
            with patch.object(core, 'metal_built', return_value=False):
                report = json.loads(hardware_report.collect(directory, graphics=True).read_bytes())
            self.assertEqual(report['m2vk'], {'status': 'not_built'})
            self.assertEqual(report['coverage']['m2vk'], 'not_built')
            with patch.object(core, 'metal_built', return_value=True), \
                    patch.object(graphics, 'metal_report', return_value={'status': 'pass', 'identity': self.IDENTITY}):
                report = json.loads(hardware_report.collect(directory, graphics=True).read_bytes())
            self.assertEqual(report['coverage']['m2vk'], 'pass')
            self.assertEqual(report['m2vk']['identity']['name'], 'Test GPU')


if __name__ == '__main__':
    unittest.main()
