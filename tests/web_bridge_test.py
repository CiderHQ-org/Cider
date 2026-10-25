"""Bridge protocol tests without GTK, a display, or a running game."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

gi = types.ModuleType("gi")
gi.require_version = Mock()
repository = types.ModuleType("gi.repository")
for name in ("Adw", "Gdk", "Gio", "GLib", "Gtk"):
    setattr(repository, name, types.SimpleNamespace())
repository.GLib.Error = RuntimeError
with patch.dict(sys.modules, {"gi": gi, "gi.repository": repository}):
    spec = importlib.util.spec_from_file_location(
        "quadra._web_protocol_test", Path(__file__).parents[1] / "launcher/quadra/web.py")
    web = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(web)


class WebBridgeTests(unittest.TestCase):
    def bridge(self):
        bridge = object.__new__(web.WebBridge)
        bridge.send = Mock()
        bridge.pages = {}
        bridge.session = Mock()
        bridge._page = Mock()
        return bridge

    def test_cookie_requests_do_not_create_a_dummy_web_view(self):
        bridge = self.bridge()
        bridge._cookies_get = Mock()
        bridge._handle({"op": "cookies-get", "request": 123})
        bridge._cookies_get.assert_called_once_with(123)
        bridge._page.assert_not_called()

    def test_invalid_cookie_and_javascript_requests_complete_with_errors(self):
        bridge = self.bridge()
        for cookie in (None, {"name": "session"}, {"name": "", "value": "x", "domain": "roblox.com"}):
            bridge._cookie_set(123, cookie)
            self.assertEqual(bridge.send.call_args.args[0]["request"], 123)
            self.assertIn("error", bridge.send.call_args.args[0])
        page = web._Page(22, Mock(), 0)
        bridge._eval(page, 124, None)
        self.assertEqual(bridge.send.call_args.args[0]["view"], 22)
        page.view.evaluate_javascript.assert_not_called()

    def test_request_for_closed_page_is_not_resurrected(self):
        bridge = self.bridge()
        bridge._handle({"op": "eval", "view": 22, "request": 1, "script": "1+1"})
        bridge._page.assert_not_called()
        self.assertIn("closed", bridge.send.call_args.args[0]["error"])

    def test_invalid_url_is_reported_without_loading(self):
        bridge = self.bridge()
        page = web._Page(4, Mock(), 0)
        bridge._event = Mock()
        bridge._load(page, {"url": "https://[invalid"})
        page.view.load_request.assert_not_called()
        bridge._event.assert_called_once()
        self.assertFalse(web._web_url("https://[invalid"))

    def test_full_reply_queue_disconnects_instead_of_losing_a_callback(self):
        bridge = self.bridge()
        del bridge.send
        bridge.peer = Mock()
        bridge.outgoing = [b"queued"] * 128
        bridge._drop_peer = Mock()
        bridge.send({"event": "reply", "request": 1})
        bridge._drop_peer.assert_called_once()
        self.assertEqual(len(bridge.outgoing), 128)

    def test_zero_length_socket_write_disconnects_without_looping(self):
        bridge = self.bridge()
        bridge.peer = Mock()
        bridge.peer.send.return_value = 0
        bridge.outgoing = [b"queued"]
        bridge._drop_peer = Mock()
        self.assertFalse(bridge._flush(0, 0))
        bridge._drop_peer.assert_called_once()


if __name__ == "__main__":
    unittest.main()
