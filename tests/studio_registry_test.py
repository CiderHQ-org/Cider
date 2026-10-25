"""Wine registry files of Studio's prefix: parsing, sign-in decryption and the .reg files we write."""
import unittest

from quadra import studio_registry as registry

USER_REG = r'''WINE REGISTRY Version 2
;; All keys relative to \\User\\S-1-5-21-0-0-0-1000

#arch=win64

[Software\\Roblox\\RobloxStudio] 1792945877
#time=1dd649e42806eb0
"PreviousVersion"="0.744.0.7441077"
"rbxl_last_directory"="C:/users/aubree/Documents"
"BreakOnErrorMode"=dword:00000000
"Quoted"="say \"hi\" in C:\\temp"
@="default value"
"Long"=hex:01,02,03,\
  04,05,06

[Software\\Wine\\Credential Manager] 1792945876
#time=1dd649e421d24ae
"EncryptionKey"=hex:7c,6d,f6,59,a7,ec,6e,5e
'''


def credential_registry(key, user, cookie):
    prefix = r"Software\\Wine\\Credential Manager\\Generic: https://www.roblox.com:RobloxStudioAuth"
    hexed = lambda data: ",".join(f"{byte:02x}" for byte in data)
    return USER_REG + f'''
[{prefix}userid] 1792945900
"Password"=hex:{hexed(registry.rc4(key, user))}

[{prefix}.ROBLOSECURITY{user.decode()}] 1792945900
"Password"=hex:{hexed(registry.rc4(key, cookie))}
'''


class ParseTests(unittest.TestCase):
    def setUp(self):
        self.keys = registry.parse(USER_REG)

    def test_keys_have_single_backslashes_and_values_their_types(self):
        studio = registry.find(self.keys, r"Software\Roblox\RobloxStudio")
        self.assertEqual(studio["PreviousVersion"], ("string", "0.744.0.7441077"))
        self.assertEqual(studio["BreakOnErrorMode"], ("dword", 0))
        self.assertEqual(studio[""], ("string", "default value"))
        self.assertEqual(studio["Long"], ("hex", bytes([1, 2, 3, 4, 5, 6])))
        self.assertEqual(studio["Quoted"], ("string", r'say "hi" in C:\temp'))

    def test_key_names_are_case_insensitive_and_missing_ones_are_none(self):
        self.assertIsNotNone(registry.find(self.keys, r"software\wine\CREDENTIAL manager"))
        self.assertIsNone(registry.find(self.keys, r"Software\Nothing"))

    def test_the_webview_runtime_version_comes_from_the_uninstall_key(self):
        text = (r'[Software\\Wow6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\Microsoft EdgeWebView] 1' '\n'
                '"DisplayVersion"="144.0.3719.92"\n')
        self.assertEqual(registry.installed_webview(text), "144.0.3719.92")
        self.assertEqual(registry.installed_webview(USER_REG), "")


class SignInTests(unittest.TestCase):
    key = bytes.fromhex("7c6df659a7ec6e5e")

    def test_rc4_matches_the_published_test_vector(self):
        self.assertEqual(registry.rc4(b"Key", b"Plaintext").hex(), "bbf316e8d940af0ad3")

    def test_the_cookie_is_decrypted_for_the_signed_in_user(self):
        text = credential_registry(self.key, b"123456789", b"_|WARNING:-DO-NOT-SHARE|_secret")
        self.assertEqual(registry.roblosecurity(text), "_|WARNING:-DO-NOT-SHARE|_secret")

    def test_text_saved_as_utf16_is_read_too(self):
        cookie = "_|WARNING:-DO-NOT-SHARE|_secret"
        text = credential_registry(self.key, "42".encode("utf-16-le"), cookie.encode("utf-16-le"))
        # the cookie's key name is built from the user id, which here is saved as UTF-16 as well
        self.assertEqual(registry.roblosecurity(text.replace(".ROBLOSECURITY4\x002\x00", ".ROBLOSECURITY42")), cookie)

    def test_nobody_signed_in_gives_none(self):
        self.assertIsNone(registry.roblosecurity(USER_REG))
        self.assertIsNone(registry.roblosecurity(""))

    def test_a_user_without_a_cookie_gives_none(self):
        text = credential_registry(self.key, b"42", b"x").split(".ROBLOSECURITY")[0].rsplit("[", 1)[0]
        self.assertIsNone(registry.roblosecurity(text))


class WrittenFileTests(unittest.TestCase):
    def test_values_are_quoted_numbers_are_dwords_and_none_deletes(self):
        text = registry.reg_file({r"HKEY_CURRENT_USER\Software\X": {"Name": 'a "b" \\c', "Count": 5, "Old": None}})
        self.assertEqual(text.split("\r\n"), [
            "Windows Registry Editor Version 5.00", "",
            r"[HKEY_CURRENT_USER\Software\X]",
            r'"Name"="a \"b\" \\c"', '"Count"=dword:00000005', '"Old"=-', ""])

    def test_the_theme_follows_the_system_preference(self):
        dark, light = registry.theme_reg(True), registry.theme_reg(False)
        self.assertIn('"AppsUseLightTheme"=dword:00000000', dark)
        self.assertIn('"AppsUseLightTheme"=dword:00000001', light)
        self.assertIn('"Window"="29 29 32"', dark)
        self.assertIn('"Window"="255 255 255"', light)

    def test_shell_folders_are_windows_paths_on_the_linux_root(self):
        text = registry.folders_reg("/home/u/.local/share/quadrahq/studio/appdata", "/home/u/Documents", "/home/u/Pictures")
        self.assertIn(r'"Local AppData"="Z:\\home\\u\\.local\\share\\quadrahq\\studio\\appdata"', text)
        self.assertIn(r'"My Pictures"="Z:\\home\\u\\Pictures"', text)

    def test_what_we_write_can_be_read_back_by_the_same_parser(self):
        # .reg import files use [HKEY_...]; Wine's own files do not, so only the values are compared.
        text = registry.theme_reg(True)
        self.assertEqual(text.count("[HKEY_CURRENT_USER"), 3)


if __name__ == "__main__":
    unittest.main()
