"""Which Studio to install, and where from. No GTK.

Roblox publishes Studio as numbered deployments on channels. Without a choice
the signed-in account's channel is used, as Roblox's own installer does (most
accounts are on the public one); a channel or version can be set instead.
Packages come from setup.rbxcdn.com, with Roblox's own alternate hosts for when
that one refuses or fails."""
import json
import logging
import urllib.error
import urllib.request

from . import __version__

VERSION_URL = "https://clientsettingscdn.roblox.com/v2/client-version/WindowsStudio64"
VERSION_ALTERNATE_URL = "https://clientsettings.roblox.com/v2/client-version/WindowsStudio64"
USER_CHANNEL_URL = "https://clientsettings.roblox.com/v2/user-channel?binaryType=WindowsStudio64"
PACKAGE_HOSTS = ("https://setup.rbxcdn.com", "https://setup-aws.rbxcdn.com", "https://setup-ak.rbxcdn.com",
                 "https://s3.amazonaws.com/setup.roblox.com")
# A refusal or a failing server moves on to the next host; anything else is the answer.
RETRY_STATUSES = {403, 404, 408, 429, 500, 502, 503, 504}

log = logging.getLogger(__name__)


class BadChannel(RuntimeError):
    """The channel does not exist or the account may not use it."""


def is_live(channel):
    return (channel or "").lower() in ("", "live")


def _request(url, headers=None):
    return urllib.request.Request(url, headers={"User-Agent": f"Quadra/{__version__}", **(headers or {})})


def _json(url, headers=None, opener=urllib.request.urlopen, timeout=15):
    with opener(_request(url, headers), timeout=timeout) as response:
        return json.load(response)


def user_channel(cookie, opener=urllib.request.urlopen):
    """(channel, token) of the signed-in account's Studio deployment channel."""
    data = _json(USER_CHANNEL_URL, {"Cookie": f".ROBLOSECURITY={cookie}"}, opener)
    return data["channel"], data.get("token", "")


def newest(channel="", token="", opener=urllib.request.urlopen):
    """The newest deployment's id ("version-...") on `channel`."""
    path = "" if is_live(channel) else f"/channel/{channel}"
    headers = {"Roblox-Channel-Token": token} if token else None
    last = None
    for base in (VERSION_URL, VERSION_ALTERNATE_URL):
        try:
            return _json(base + path, headers, opener)["clientVersionUpload"]
        except urllib.error.HTTPError as error:
            if error.code == 401 and not is_live(channel):
                error.close()
                raise BadChannel(channel) from None
            if error.code != 403:
                raise
            last = error
        except (urllib.error.URLError, TimeoutError):
            if base is VERSION_ALTERNATE_URL:
                raise
    raise last


def resolve(version="", channel="", cookie=lambda: None, opener=urllib.request.urlopen):
    """(version, channel) to install. `cookie()` gives the saved sign-in, only
    when the account's own channel is needed."""
    if version:
        return version, channel
    token = ""
    if not channel:
        saved = cookie()
        if saved:
            try:
                channel, token = user_channel(saved, opener)
            except (OSError, ValueError, KeyError):
                # Roblox could not say; the public deployment is a safe default.
                log.warning("Could not look up the account's Studio channel; using the public one")
                channel, token = "", ""
    return newest(channel, token, opener), channel


def package_urls(version, channel, name):
    """The package's address on each host, in the order to try them."""
    middle = "" if is_live(channel) else "/channel/common"
    return [f"{host}{middle}/{version}-{name}" for host in PACKAGE_HOSTS]


def open_first(urls, opener=urllib.request.urlopen, timeout=60):
    """The first host that answers; the hosts that refuse or fail are skipped."""
    last = None
    for url in urls:
        try:
            return opener(_request(url), timeout=timeout)
        except urllib.error.HTTPError as error:
            if error.code not in RETRY_STATUSES:
                raise
            error.close()
            last = error
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            last = error
        log.warning("Studio download from %s failed (%s); trying the next host", url.split("/")[2], last)
    raise last if last else OSError("no download address")
