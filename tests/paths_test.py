"""Preserve user data when moving Cider and MacOBlox installations to Quadra."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from macoblox import paths


class UserDirectoryMigrationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        paths.user_directory.cache_clear()
        self.addCleanup(paths.user_directory.cache_clear)

    def directory(self, name, contents):
        directory = self.base / name
        directory.mkdir(parents=True)
        file = directory / 'settings.json'
        file.write_text(contents)
        file.chmod(0o600)
        return directory

    def test_cider_wins_over_older_macoblox_and_keeps_permissions(self):
        cider = self.directory('ciderhq', 'current settings')
        older = self.directory('macoblox', 'older settings')
        with patch.dict(os.environ, XDG_CONFIG_HOME=str(self.base)):
            target = paths.user_directory('CONFIG')
        self.assertEqual(target, self.base / 'quadrahq')
        self.assertEqual((target / 'settings.json').read_text(), 'current settings')
        self.assertEqual((target / 'settings.json').stat().st_mode & 0o777, 0o600)
        self.assertFalse(cider.exists())
        self.assertEqual((older / 'settings.json').read_text(), 'older settings')

    def test_existing_quadra_data_is_never_replaced(self):
        target = self.directory('quadrahq', 'Quadra settings')
        cider = self.directory('ciderhq', 'Cider settings')
        result = paths.migrate_directories(target, cider, self.base / 'macoblox')
        self.assertEqual(result, target)
        self.assertEqual((target / 'settings.json').read_text(), 'Quadra settings')
        self.assertEqual((cider / 'settings.json').read_text(), 'Cider settings')

    def test_older_session_migrates_when_cider_session_is_absent(self):
        legacy = self.directory('Library/MacOBlox', 'session')
        target = self.base / 'Library/QuadraHQ'
        target.mkdir()
        self.assertEqual(paths.migrate_directories(target, self.base / 'Library/CiderHQ', legacy), target)
        self.assertEqual((target / 'settings.json').read_text(), 'session')
        self.assertFalse(legacy.exists())

    def test_failed_move_uses_cider_without_falling_back_to_older_data(self):
        cider = self.directory('ciderhq', 'current settings')
        older = self.directory('macoblox', 'older settings')
        with patch.object(Path, 'rename', side_effect=OSError('permission denied')):
            result = paths.migrate_directories(self.base / 'quadrahq', cider, older)
        self.assertEqual(result, cider)
        self.assertEqual((cider / 'settings.json').read_text(), 'current settings')
        self.assertEqual((older / 'settings.json').read_text(), 'older settings')
