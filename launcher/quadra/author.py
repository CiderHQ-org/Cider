"""Author card and community links for the Info page. No GTK here."""

import http.client
import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

from . import core, dns

NAME = "Narezany"
ROBLOX_USER = "H4Ru_456"
ROBLOX_ID = 8847914296
PROFILE_URL = f"https://www.roblox.com/users/{ROBLOX_ID}/profile"
DISCORD_URL = "https://discord.gg/jCjHYYNq48"
GITHUB_URL = "https://github.com/QuadraHQ/Quadra"

# Maintainer of this version; the picture ships with the launcher.
MAINTAINER = "aubree.wtf"
MAINTAINER_URL = "https://aubree.wtf"
MAINTAINER_AVATAR = core.PROJECT / "branding" / "contributors" / "aubree.png"

UI_CONTRIBUTOR = "TinyTosha"
UI_CONTRIBUTOR_URL = "https://github.com/amethyst-bin"
UI_CONTRIBUTOR_AVATAR = core.CACHE_DIR / "tinytosha-avatar.png"
TINYTOSHA_AVATAR_URL = "https://avatars.githubusercontent.com/u/259899852"

AVATAR = core.CACHE_DIR / "author-avatar.png"
THUMBNAIL_API = ("https://thumbnails.roblox.com/v1/users/avatar-headshot"
                 f"?userIds={ROBLOX_ID}&size=150x150&format=Png&isCircular=false")


class _PinnedHTTPS(http.client.HTTPSConnection):
    """HTTPS to a known IP while still checking the certificate for `host`."""

    def __init__(self, host, address, timeout):
        super().__init__(host, timeout=timeout)
        self.address = address

    def connect(self):
        raw = socket.create_connection((self.address, 443), self.timeout)
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)


def _get(url, provider, timeout=10):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.read()
    except urllib.error.URLError as error:
        # Roblox image hosts often do not resolve through ISP resolvers
        # (the same reason the game has its own DNS setting).
        if not isinstance(error.reason, socket.gaierror):
            raise
    parts = urllib.parse.urlsplit(url)
    for address in dns.resolve_a(parts.hostname, provider):
        connection = _PinnedHTTPS(parts.hostname, address, timeout)
        try:
            path = parts.path + ("?" + parts.query if parts.query else "")
            connection.request("GET", path, headers={"User-Agent": "Quadra"})
            response = connection.getresponse()
            if response.status == 200:
                return response.read()
        except OSError:
            continue
        finally:
            connection.close()
    raise OSError(f"could not download {url}")


def avatar(settings, max_age=86400):
    """Path to the cached avatar headshot, refreshed once a day. Returns the
    old copy (or None) when Roblox is unreachable."""
    try:
        if time.time() - AVATAR.stat().st_mtime < max_age:
            return AVATAR
    except OSError:
        pass
    provider = settings.get("dns")
    provider = provider if provider in dns.PROVIDERS else "quad9"
    try:
        info = json.loads(_get(THUMBNAIL_API, provider))
        image = _get(info["data"][0]["imageUrl"], provider)
        if not image.startswith(b"\x89PNG"):
            raise ValueError("not a PNG")
        core.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        partial = AVATAR.with_suffix(".part")
        partial.write_bytes(image)
        partial.replace(AVATAR)
    except (OSError, ValueError, KeyError, IndexError):
        pass
    return AVATAR if AVATAR.exists() else None


def tinytosha_avatar(max_age=86400):
    """Path to the cached GitHub avatar for TinyTosha, refreshed once a day."""
    try:
        if time.time() - UI_CONTRIBUTOR_AVATAR.stat().st_mtime < max_age:
            return UI_CONTRIBUTOR_AVATAR
    except OSError:
        pass
    try:
        req = urllib.request.Request(TINYTOSHA_AVATAR_URL, headers={"User-Agent": "Quadra"})
        with urllib.request.urlopen(req, timeout=5) as response:
            image = response.read()
        core.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        partial = UI_CONTRIBUTOR_AVATAR.with_suffix(".part")
        partial.write_bytes(image)
        partial.replace(UI_CONTRIBUTOR_AVATAR)
    except (OSError, urllib.error.URLError):
        pass
    return UI_CONTRIBUTOR_AVATAR if UI_CONTRIBUTOR_AVATAR.exists() else None
