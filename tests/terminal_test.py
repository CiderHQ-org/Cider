import unittest

from macoblox import terminal

ARGV = ["bash", "-c", "exit 0", "quadra-runtime-install"]


def installed(*names):
    return lambda name: f"/usr/bin/{name}" if name in names else None


class TerminalCommandTests(unittest.TestCase):
    def test_xdg_terminal_exec_comes_first(self):
        self.assertEqual(terminal.command(ARGV, {"TERMINAL": "kitty"}, installed("kitty", "xdg-terminal-exec")),
                         ["/usr/bin/xdg-terminal-exec", "--", *ARGV])

    def test_terminal_variable_keeps_its_options(self):
        self.assertEqual(terminal.command(ARGV, {"TERMINAL": "kitty -1"}, installed("kitty", "xterm")),
                         ["/usr/bin/kitty", "-1", *ARGV])

    def test_unknown_terminal_variable_gets_dash_e(self):
        self.assertEqual(terminal.command(ARGV, {"TERMINAL": "myterm"}, installed("myterm")),
                         ["/usr/bin/myterm", "-e", *ARGV])

    def test_unusable_terminal_variable_is_skipped(self):
        for value in ("missing-term", "'unclosed"):
            with self.subTest(value=value):
                self.assertEqual(terminal.command(ARGV, {"TERMINAL": value}, installed("alacritty")),
                                 ["/usr/bin/alacritty", "-e", *ARGV])

    def test_desktop_terminal_preferred(self):
        self.assertEqual(terminal.command(ARGV, {"XDG_CURRENT_DESKTOP": "KDE"}, installed("xterm", "konsole")),
                         ["/usr/bin/konsole", "-e", *ARGV])
        self.assertEqual(terminal.command(ARGV, {"XDG_CURRENT_DESKTOP": "ubuntu:GNOME"},
                                          installed("xterm", "gnome-terminal")),
                         ["/usr/bin/gnome-terminal", "--", *ARGV])

    def test_debian_alternative_before_the_generic_list(self):
        self.assertEqual(terminal.command(ARGV, {}, installed("xterm", "x-terminal-emulator")),
                         ["/usr/bin/x-terminal-emulator", "-e", *ARGV])

    def test_terminals_older_glib_does_not_know(self):
        expected = {"kitty": [], "alacritty": ["-e"], "foot": ["--"], "wezterm": ["start", "--"],
                    "ghostty": ["-e"]}
        for name, arguments in expected.items():
            with self.subTest(name=name):
                self.assertEqual(terminal.command(ARGV, {}, installed(name)),
                                 [f"/usr/bin/{name}", *arguments, *ARGV])

    def test_no_terminal(self):
        self.assertIsNone(terminal.command(ARGV, {"TERMINAL": ""}, installed()))


if __name__ == "__main__":
    unittest.main()
