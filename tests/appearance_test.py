"""Saved appearance choices stay compatible with pre-redesign settings."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from quadra import core


class AppearanceSettingsTests(unittest.TestCase):
    def test_old_settings_choose_grid_without_losing_existing_preferences(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "settings.json"
            file.write_text(json.dumps({"renderer": "vulkan", "mouse_sensitivity": 1.75}))
            with patch.object(core, "SETTINGS_FILE", file):
                settings = core.load_settings()
                self.assertEqual(settings["launcher_appearance"], "grid")
                self.assertEqual(settings["renderer"], "vulkan")
                self.assertEqual(settings["mouse_sensitivity"], 1.75)

    def test_each_appearance_persists_and_invalid_values_use_grid(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / "settings.json"
            with patch.object(core, "SETTINGS_FILE", file):
                for code in ("grid", "gnome", "monochrome"):
                    core.save_settings(dict(core.DEFAULT_SETTINGS, launcher_appearance=code))
                    self.assertEqual(core.load_settings()["launcher_appearance"], code)
                for code in (None, True, 2, [], {}, "unknown", "../../style.css"):
                    file.write_text(json.dumps({"launcher_appearance": code}))
                    self.assertEqual(core.load_settings()["launcher_appearance"], "grid")
