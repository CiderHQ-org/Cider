"""Run: PYTHONPATH=launcher python3 -m unittest discover -s tests -p '*_test.py'."""
import unittest
from unittest.mock import patch

from quadra import core, graphics
from session_fixture import bare_session


class MetalFallbackTests(unittest.TestCase):
    def session(self, **settings):
        return bare_session(dict(core.DEFAULT_SETTINGS, renderer="metal", **settings))

    def test_a_working_device_keeps_quadra_m2vk(self):
        session = self.session()
        with patch.object(graphics, "validate_metal", return_value="Test GPU") as validate:
            env, name = session._validated_metal({"MACOBLOX_METAL": "1"})
        validate.assert_called_once()
        self.assertEqual((env, name), ({"MACOBLOX_METAL": "1"}, "Quadra M2VK (Test GPU)"))
        self.assertEqual(session.settings["renderer"], "metal")
        self.assertFalse(hasattr(session, "metal_fallback_reason"))

    def test_a_failed_device_plays_with_opengl_this_once(self):
        session = self.session()
        problem = RuntimeError("Quadra M2VK is unavailable: no Vulkan device. Select OpenGL in Settings.")
        with patch.object(graphics, "validate_metal", side_effect=problem), \
                patch.object(session, "environment", return_value={"OPENGL": "1"}) as environment:
            env, name = session._validated_metal({"MACOBLOX_METAL": "1"})
        self.assertEqual((env, name), ({"OPENGL": "1"}, "OpenGL (Quadra M2VK could not start)"))
        environment.assert_called_once()
        self.assertEqual(session.settings["renderer"], "opengl", "the session's copy only")
        self.assertIn("no Vulkan device", session.metal_fallback_reason)
        self.assertTrue(any("this launch uses OpenGL" in note for note in session.notes))

    def test_the_fallback_can_be_turned_off(self):
        session = self.session(metal_fallback=False)
        with patch.object(graphics, "validate_metal", side_effect=RuntimeError("no device")):
            with self.assertRaisesRegex(RuntimeError, "no device"):
                session._validated_metal({})
        self.assertEqual(session.settings["renderer"], "metal")


class ProbeSelfTestTests(unittest.TestCase):
    def test_the_probe_calls_the_host_self_test_when_it_has_one(self):
        source = open(graphics.__file__).read()
        self.assertIn("quadra_metal_host_self_test", source)
        self.assertIn("release(device)\n            raise RuntimeError", source)


if __name__ == "__main__":
    unittest.main()
