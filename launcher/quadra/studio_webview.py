"""The Microsoft Edge WebView2 runtime in Studio's prefix. No GTK.

Studio shows its login, the Toolbox and Creator Hub pages in WebView2; without
the runtime it reports "Launch Failed" at sign-in. Microsoft publishes the
runtime through a download API; Vinegar's choice of version is kept because
newer runtimes are not known to work under Wine."""
import base64
import hashlib
import json
import re
import ssl
import urllib.request

from . import studio_registry
from .i18n import _

API = "https://msedge.api.cdp.microsoft.com/api/v1.1/contents/Browser/namespaces/Default/names/msedge-stable-win-x64"
VERSION = "144.0.3719.92"
INSTALL_ARGUMENTS = ("--msedgewebview", "--do-not-launch-msedge", "--system-level")
APPDEFAULTS = r"HKCU\Software\Wine\AppDefaults\msedgewebview2.exe"
EDGE_DIRECTORY = ("drive_c", "Program Files (x86)", "Microsoft", "EdgeWebView", "Application")

# The API's certificate chain ends in this root, which many systems do not trust.
MICROSOFT_ROOT = """-----BEGIN CERTIFICATE-----
MIIF7TCCA9WgAwIBAgIQP4vItfyfspZDtWnWbELhRDANBgkqhkiG9w0BAQsFADCB
iDELMAkGA1UEBhMCVVMxEzARBgNVBAgTCldhc2hpbmd0b24xEDAOBgNVBAcTB1Jl
ZG1vbmQxHjAcBgNVBAoTFU1pY3Jvc29mdCBDb3Jwb3JhdGlvbjEyMDAGA1UEAxMp
TWljcm9zb2Z0IFJvb3QgQ2VydGlmaWNhdGUgQXV0aG9yaXR5IDIwMTEwHhcNMTEw
MzIyMjIwNTI4WhcNMzYwMzIyMjIxMzA0WjCBiDELMAkGA1UEBhMCVVMxEzARBgNV
BAgTCldhc2hpbmd0b24xEDAOBgNVBAcTB1JlZG1vbmQxHjAcBgNVBAoTFU1pY3Jv
c29mdCBDb3Jwb3JhdGlvbjEyMDAGA1UEAxMpTWljcm9zb2Z0IFJvb3QgQ2VydGlm
aWNhdGUgQXV0aG9yaXR5IDIwMTEwggIiMA0GCSqGSIb3DQEBAQUAA4ICDwAwggIK
AoICAQCygEGqNThNE3IyaCJNuLLx/9VSvGzH9dJKjDbu0cJcfoyKrq8TKG/Ac+M6
ztAlqFo6be+ouFmrEyNozQwph9FvgFyPRH9dkAFSWKxRxV8qh9zc2AodwQO5e7BW
6KPeZGHCnvjzfLnsDbVU/ky2ZU+I8JxImQxCCwl8MVkXeQZ4KI2JOkwDJb5xalwL
54RgpJki49KvhKSn+9GY7Qyp3pSJ4Q6g3MDOmT3qCFK7VnnkH4S6Hri0xElcTzFL
h93dBWcmmYDgcRGjuKVB4qRTufcyKYMME782XgSzS0NHL2vikR7TmE/dQgfI6B0S
/Jmpaz6SfsjWaTr8ZL22CZ3K/QwLopt3YEsDlKQwaRLWQi3BQUzK3Kr9j1uDRprZ
/LHR47PJf0h6zSTwQY9cdNCssBAgBkm3xy0hyFfj0IbzA2j70M5xwYmZSmQBbP3s
MJHPQTySx+W6hh1hhMdfgzlirrSSL0fzC/hV66AfWdC7dJse0Hbm8ukG1xDo+mTe
acY1logC8Ea4PyeZb8txiSk190gWAjWP1Xl8TQLPX+uKg09FcYj5qQ1OcunCnAfP
SRtOBA5jUYxe2ADBVSy2xuDCZU7JNDn1nLPEfuhhbhNfFcRf2X7tHc7uROzLLoax
7Dj2cO2rXBPB2Q8Nx4CyVe0096yb5MPa50c8prWPMd/FS6/r8QIDAQABo1EwTzAL
BgNVHQ8EBAMCAYYwDwYDVR0TAQH/BAUwAwEB/zAdBgNVHQ4EFgQUci06AjGQQ7kU
BU7h6qfHMdEjiTQwEAYJKwYBBAGCNxUBBAMCAQAwDQYJKoZIhvcNAQELBQADggIB
AH9yzw+3xRXbm8BJyiZb/p4T5tPw0tuXX/JLP02zrhmu7deXoKzvqTqjwkGw5biR
nhOBJAPmCf0/V0A5ISRW0RAvS0CpNoZLtFNXmvvxfomPEf4YbFGq6O0JlbXlccmh
6Yd1phV/yX43VF50k8XDZ8wNT2uoFwxtCJJ+i92Bqi1wIcM9BhS7vyRep4TXPw8h
Ir1LAAbblxzYXtTFC1yHblCk6MM4pPvLLMWSZpuFXst6bJN8gClYW1e1QGm6CHmm
ZGIVnYeWRbVmIyADixxzoNOieTPgUFmG2y/lAiXqcyqfABTINseSO+lOAOzYVgm5
M0kS0lQLAausR7aRKX1MtHWAUgHoyoL2n8ysnI8X6i8msKtyrAv+nlEex0NVZ09R
s1fWtuzuUrc66U7h14GIvE+OdbtLqPA1qibUZ2dJsnBMO5PcHd94kIZysjik0dyS
TclY6ysSXNQ7roxrsIPlAT/4CTL2kzU0Iq/dNw13CYArzUgA8YyZGUcFAenRv9FO
0OYoQzeZpApKCNmacXPSqs0xE2N2oTdvkjgefRI8ZjLny23h/FKJ3crWZgWalmG+
oijHHKOnNlA8OqTfSm7mhzvO6/DggTedEzxSjr25HTTGHdUKaj2YKXCMiSrRq4IQ
SB/c9O+lxbtVGjhjhE63bK2VVOxlIhBJF7jAHscPrFRH
-----END CERTIFICATE-----
"""


def _context():
    context = ssl.create_default_context()
    context.load_verify_locations(cadata=MICROSOFT_ROOT)
    return context


def runtime_download(version=VERSION, opener=urllib.request.urlopen):
    """{url, size, sha256 (hex)} of the full x64 runtime installer for `version`."""
    request = urllib.request.Request(f"{API}/versions/{version}/files?action=GenerateDownloadInfo", method="POST",
                                     headers={"User-Agent": "Quadra"})
    with opener(request, timeout=30, context=_context()) as response:
        files = json.load(response)
    for entry in files:
        # The runtime is the file without a second version (that one is an update from it).
        if re.fullmatch(rf"MicrosoftEdge_X64_{re.escape(version)}\.exe", entry.get("FileId", "")):
            digest = base64.b64decode(entry["Hashes"]["Sha256"]).hex()
            return {"url": entry["Url"], "size": entry["SizeInBytes"], "sha256": digest}
    raise RuntimeError(_("Microsoft has no WebView2 runtime {version}", version=version))


def installed(prefix):
    try:
        return studio_registry.installed_webview((prefix / "system.reg").read_text(errors="replace"))
    except OSError:
        return ""


def ensure(prefix, wine, download, cache, version, progress):
    """Makes `version` the installed runtime; True when it installed something.

    wine(*arguments) runs Wine in the prefix and waits; download(url, target,
    progress, label, digest) is the launcher's resumable-free downloader."""
    current = installed(prefix)
    if current == version:
        return False
    info = runtime_download(version)
    installer = cache / f"webview-{version}.exe"
    if not installer.exists() or hashlib.sha256(installer.read_bytes()).hexdigest() != info["sha256"]:
        digest = hashlib.sha256()
        download(info["url"], installer, progress, "WebView2", digest)
        if digest.hexdigest() != info["sha256"]:
            installer.unlink(missing_ok=True)
            raise RuntimeError(_("The WebView2 download failed its checksum"))
    if current:
        progress(1, _("Removing WebView2 {version}", version=current))
        setup = prefix.joinpath(*EDGE_DIRECTORY, current, "Installer", "setup.exe")
        # The uninstaller reports a failure status even when it worked: look at the result instead.
        wine(str(setup), "--msedgewebview", "--uninstall", "--system-level", "--force-uninstall")
    # WebView2 needs Windows 7 behaviour from Wine's default.
    if not studio_registry.find(studio_registry.parse((prefix / "user.reg").read_text(errors="replace")),
                                r"Software\Wine\AppDefaults\msedgewebview2.exe"):
        wine("reg", "add", APPDEFAULTS, "/v", "Version", "/d", "win7", "/f")
    progress(1, _("Installing WebView2 {version}", version=version))
    wine(str(installer), *INSTALL_ARGUMENTS)
    if installed(prefix) != version:
        raise RuntimeError(_("WebView2 {version} did not install", version=version))
    return True


def browser_arguments(renderer):
    """Chromium arguments for the runtime's GPU process: Wine cannot share GPU
    memory between processes, and the Angle backend follows Studio's renderer."""
    backend = "gl" if renderer in ("d3d11", "d3d11fl10") else "vulkan"
    return f"--in-process-gpu --use-angle={backend}"
