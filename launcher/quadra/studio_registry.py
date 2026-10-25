"""Wine registry files for Studio's prefix. No GTK, no Wine process needed.

Reads the prefix's user.reg / system.reg, writes small .reg files for
`wine regedit /S`, and decrypts the sign-in Wine's credential manager keeps
for Studio (the same way Vinegar does)."""
import re

CREDENTIALS_KEY = r"Software\Wine\Credential Manager"
ROBLOX_AUTH = "Generic: https://www.roblox.com:RobloxStudioAuth"
WEBVIEW_KEY = r"Software\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Microsoft EdgeWebView"

_SECTION = re.compile(r"^\[(.*)\](?: \d+)?\s*$")
_VALUE = re.compile(r'^(@|"(?:[^"\\]|\\.)*")=(.*)$')


def _unescape(text):
    return re.sub(r"\\(.)", r"\1", text)


def _parse_value(raw):
    """(kind, data) for the value forms Wine writes; None for the rest."""
    raw = raw.strip()
    if raw.startswith('"') and raw.endswith('"'):
        return "string", _unescape(raw[1:-1])
    if raw.startswith("dword:"):
        return "dword", int(raw[6:], 16)
    match = re.fullmatch(r"hex(?:\((\w+)\))?:(.*)", raw, re.S)
    if match:
        digits = re.findall(r"[0-9a-fA-F]{2}", match[2])
        return ("hex" if match[1] is None else f"hex({match[1]})"), bytes(int(pair, 16) for pair in digits)
    return None


def parse(text):
    """{key: {name: (kind, data)}}, keys with single backslashes. Registry key
    names are case-insensitive: look them up with find()."""
    keys, current = {}, None
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        while line.endswith("\\") and index < len(lines) and _VALUE.match(line):
            line = line[:-1] + lines[index].strip()
            index += 1
        section = _SECTION.match(line)
        if section:
            current = keys.setdefault(section[1].replace("\\\\", "\\"), {})
            continue
        value = _VALUE.match(line)
        if value and current is not None:
            name = "" if value[1] == "@" else _unescape(value[1][1:-1])
            parsed = _parse_value(value[2])
            if parsed is not None:
                current[name] = parsed
    return keys


def find(keys, path):
    wanted = path.lower()
    for name, values in keys.items():
        if name.lower() == wanted:
            return values
    return None


def installed_webview(system_reg_text):
    """The Edge WebView2 runtime version installed in the prefix, or ''."""
    values = find(parse(system_reg_text), WEBVIEW_KEY) or {}
    version = values.get("DisplayVersion")
    return version[1] if version and version[0] == "string" else ""


def rc4(key, data):
    state = list(range(256))
    j = 0
    for i in range(256):
        j = (j + state[i] + key[i % len(key)]) & 255
        state[i], state[j] = state[j], state[i]
    i = j = 0
    out = bytearray()
    for byte in data:
        i = (i + 1) & 255
        j = (j + state[i]) & 255
        state[i], state[j] = state[j], state[i]
        out.append(byte ^ state[(state[i] + state[j]) & 255])
    return bytes(out)


def _text(blob):
    """A credential's text: ASCII/UTF-8, or UTF-16 if that is how it was saved."""
    if len(blob) >= 2 and blob[1] == 0:
        return blob.decode("utf-16-le", "replace").rstrip("\x00")
    return blob.decode("utf-8", "replace").rstrip("\x00")


def roblosecurity(user_reg_text):
    """The signed-in Roblox account's .ROBLOSECURITY cookie from Studio's saved
    sign-in, or None. Wine encrypts each credential with RC4 under the
    credential manager's EncryptionKey, restarting the key stream per value."""
    keys = parse(user_reg_text)
    manager = find(keys, CREDENTIALS_KEY)
    key = manager.get("EncryptionKey") if manager else None
    if not key or key[0] != "hex" or not key[1]:
        return None

    def secret(name):
        values = find(keys, f"{CREDENTIALS_KEY}\\{ROBLOX_AUTH}{name}")
        blob = values.get("Password") if values else None
        return rc4(key[1], blob[1]) if blob and blob[0] == "hex" else None

    user = secret("userid")
    if not user:
        return None
    cookie = secret(".ROBLOSECURITY" + _text(user))
    return _text(cookie) if cookie else None


def _quote(text):
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def reg_file(keys):
    """A .reg import file. keys: {r"HKEY_CURRENT_USER\\Software\\X": {name: str | int | None}};
    None deletes the value."""
    lines = ["Windows Registry Editor Version 5.00", ""]
    for key, values in keys.items():
        lines.append(f"[{key}]")
        for name, value in values.items():
            if value is None:
                lines.append(f"{_quote(name)}=-")
            elif isinstance(value, int):
                lines.append(f"{_quote(name)}=dword:{value:08x}")
            else:
                lines.append(f"{_quote(name)}={_quote(value)}")
        lines.append("")
    return "\r\n".join(lines)


# Colours from Vinegar (GPL-3.0), which takes them from libadwaita's palette.
DARK_COLORS = {
    "ActiveBorder": "34 34 38", "ActiveTitle": "46 46 50", "AppWorkSpace": "45 45 49",
    "Background": "29 29 32", "ButtonAlternateFace": "98 160 234", "ButtonDkShadow": "22 22 25",
    "ButtonFace": "46 46 50", "ButtonHilight": "57 57 61", "ButtonLight": "53 53 57",
    "ButtonShadow": "25 25 28", "ButtonText": "255 255 255", "GradientActiveTitle": "46 46 50",
    "GradientInactiveTitle": "40 40 44", "GrayText": "136 136 136", "Hilight": "98 160 234",
    "HilightText": "255 255 255", "InactiveBorder": "40 40 44", "InactiveTitle": "40 40 44",
    "InactiveTitleText": "211 211 211", "InfoText": "255 255 255", "InfoWindow": "54 54 58",
    "Menu": "54 54 58", "MenuBar": "46 46 50", "MenuHilight": "98 160 234", "MenuText": "255 255 255",
    "Scrollbar": "46 46 50", "TitleText": "255 255 255", "Window": "29 29 32",
    "WindowFrame": "46 46 50", "WindowText": "255 255 255",
}
LIGHT_COLORS = {
    "ActiveBorder": "255 255 255", "ActiveTitle": "50 150 250", "AppWorkSpace": "128 128 128",
    "Background": "37 111 149", "ButtonAlternateFace": "255 255 255", "ButtonDkShadow": "106 106 106",
    "ButtonFace": "245 245 245", "ButtonHilight": "255 255 255", "ButtonLight": "227 227 227",
    "ButtonShadow": "166 166 166", "ButtonText": "0 0 0", "GradientActiveTitle": "50 150 250",
    "GradientInactiveTitle": "128 128 128", "GrayText": "106 106 106", "Hilight": "48 150 250",
    "HilightText": "255 255 255", "HotTrackingColor": "48 150 250", "InactiveBorder": "255 255 255",
    "InactiveTitle": "128 128 128", "InactiveTitleText": "200 200 200", "InfoText": "0 0 0",
    "InfoWindow": "255 255 255", "Menu": "255 255 255", "MenuBar": "255 255 255",
    "MenuHilight": "48 150 250", "MenuText": "0 0 0", "Scrollbar": "255 255 255",
    "TitleText": "0 0 0", "Window": "255 255 255", "WindowFrame": "158 158 158", "WindowText": "0 0 0",
}


def theme_reg(dark):
    """Wine's colours and the Windows app-theme switch, so Studio's own
    "Default" theme follows the system light/dark preference."""
    current = r"HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion"
    light = 0 if dark else 1
    return reg_file({
        rf"{current}\ThemeManager": {"ColorName": None, "DllName": None, "SizeName": None,
                                     "LoadedBefore": "0", "ThemeActive": "0"},
        rf"{current}\Themes\Personalize": {"AppsUseLightTheme": light, "SystemUsesLightTheme": light},
        r"HKEY_CURRENT_USER\Control Panel\Colors": DARK_COLORS if dark else LIGHT_COLORS,
    })


def folders_reg(local_appdata, documents, pictures):
    """Windows paths (Z:\\...) for the user's shell folders."""
    windows = lambda path: "Z:" + str(path).replace("/", "\\")
    return reg_file({
        r"HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders": {
            "Local AppData": windows(local_appdata), "Documents": windows(documents),
            "My Pictures": windows(pictures)},
    })
