"""Public Roblox deployments: official alternate origins, then Quadra's mirror.

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
ALTERNATE_RETRY_STATUSES = {403, 404, 408, 429, 500, 502, 503, 504}


def mirror_url(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or parsed.query or parsed.fragment or parsed.username or parsed.password:
        return None
    if ((parsed.netloc == 'clientsettingscdn.roblox.com' and VERSION_PATH.fullmatch(parsed.path))
            or (parsed.netloc == 'setup.rbxcdn.com' and ARCHIVE_PATH.fullmatch(parsed.path))):
        return MIRROR + parsed.path
    return None


def official_alternates(url):
    """Identical deployment paths on Roblox's own alternate origins."""
    if mirror_url(url) is None:
        return ()
    parsed = urllib.parse.urlsplit(url)
    hosts = ("clientsettings.roblox.com",) if VERSION_PATH.fullmatch(parsed.path) else (
        "setup-aws.rbxcdn.com", "setup-ak.rbxcdn.com")
    return tuple("https://" + host + parsed.path for host in hosts)


def open_public(url, *, timeout=30, on_fallback=None):
    """A public 403 tries official alternates before the independent mirror.

    Initial non-403 failures retain their normal behavior. After a 403, an
    unavailable, lagging or overloaded alternate must not block the mirror.
    Authentication errors still propagate without trying another source.
    """
    headers = {'User-Agent': f'Quadra/{__version__}'}
    try:
        return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout)
    except urllib.error.HTTPError as error:
        fallback = mirror_url(url)
        if error.code != 403 or fallback is None:
            raise
        error.close()
    logging.getLogger(__name__).warning('Roblox returned HTTP 403; trying alternate official download servers')
    if on_fallback:
        on_fallback()
    for alternate in official_alternates(url):
        try:
            return urllib.request.urlopen(urllib.request.Request(alternate, headers=headers), timeout=timeout)
        except urllib.error.HTTPError as error:
            if error.code not in ALTERNATE_RETRY_STATUSES:
                raise
            error.close()
        except (urllib.error.URLError, TimeoutError):
            continue
    logging.getLogger(__name__).warning('Official download alternates unavailable; trying the Quadra download mirror')
    # A cold archive cache must finish fetching and validating the upstream
    # download before it can return a complete, length-checked response.
    mirror_timeout = 120 if ARCHIVE_PATH.fullmatch(urllib.parse.urlsplit(url).path) else 40
    return urllib.request.urlopen(urllib.request.Request(fallback, headers=headers),
                                  timeout=max(timeout, mirror_timeout))
