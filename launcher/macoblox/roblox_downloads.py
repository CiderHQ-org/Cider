"""Public Roblox deployment requests, with Quadra's mirror as a 403 fallback.

Account, game and login requests must never pass through the mirror.
"""
import logging
import re
import urllib.error
import urllib.parse
import urllib.request

from . import __version__

MIRROR = "https://vps.korona.lat/quadra/roblox"
VERSION_PATH = re.compile(r"/v2/client-version/MacPlayer(?:/channel/[A-Za-z0-9_-]{1,64})?")
ARCHIVE_PATH = re.compile(r"/mac/version-[0-9a-fA-F]{16,64}-RobloxPlayer\.zip")


def mirror_url(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or parsed.query or parsed.fragment or parsed.username or parsed.password:
        return None
    if ((parsed.netloc == 'clientsettingscdn.roblox.com' and VERSION_PATH.fullmatch(parsed.path))
            or (parsed.netloc == 'setup.rbxcdn.com' and ARCHIVE_PATH.fullmatch(parsed.path))):
        return MIRROR + parsed.path
    return None


def open_public(url, *, timeout=30, on_fallback=None):
    """Try Roblox first. Retry only an HTTP 403 for an allowed public path."""
    headers = {'User-Agent': f'Quadra/{__version__}'}
    try:
        return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout)
    except urllib.error.HTTPError as error:
        fallback = mirror_url(url)
        if error.code != 403 or fallback is None:
            raise
        error.close()
    logging.getLogger(__name__).warning('Roblox returned HTTP 403; trying the Quadra download mirror')
    if on_fallback:
        on_fallback()
    # A cold archive cache must finish fetching and validating the upstream
    # download before it can return a complete, length-checked response.
    mirror_timeout = 120 if ARCHIVE_PATH.fullmatch(urllib.parse.urlsplit(url).path) else 40
    return urllib.request.urlopen(urllib.request.Request(fallback, headers=headers),
                                  timeout=max(timeout, mirror_timeout))
