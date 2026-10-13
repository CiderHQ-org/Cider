import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from macoblox import core, hardware_report


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


if __name__ == '__main__':
    unittest.main()
