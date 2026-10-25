"""Opaque Roblox browser URI handoff.

The browser's protocol argument is deliberately treated as an opaque byte
sequence.  Roblox's launch protocol contains ``+`` separated fields and
encoded values, but that format belongs to the macOS client; the Linux
launcher must not inspect or rebuild it.
"""

import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

import fcntl
from .paths import user_directory


CACHE_DIR = user_directory("CACHE")
PENDING_URI = CACHE_DIR / "pending-uri"
LAST_URI = CACHE_DIR / "last-uri.txt"
PENDING_LOCK = CACHE_DIR / "pending-uri.lock"
# A join link is only worth starting shortly after the click. The file keeps
# the raw URI (the shim reads it as a fallback), so its age is its mtime.
PENDING_MAX_AGE = 10 * 60


def _raw(uri):
    """Return the command-line value in the filesystem's original encoding."""
    if not isinstance(uri, str) or not uri:
        raise ValueError("a non-empty URI is required")
    # fsencode/fsdecode preserve surrogateescaped bytes, so this round trip
    # does not normalize the browser argument as UTF-8 text.
    return os.fsencode(uri)


def _atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


@contextmanager
def _pending_lock(shared=False):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with PENDING_LOCK.open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def receive(uri):
    """Record one browser argument without changing its contents."""
    data = _raw(uri)
    with _pending_lock():
        _atomic_write(PENDING_URI, data)
        _atomic_write(LAST_URI, data)


def _expired(path, now=None):
    try:
        age = (time.time() if now is None else now) - path.stat().st_mtime
    except OSError:
        return False
    # A clock set back makes the age negative: treat that as stale too.
    return not -60 <= age <= PENDING_MAX_AGE


def expire_pending():
    """Delete a pending argument older than PENDING_MAX_AGE; True if one was."""
    with _pending_lock():
        if not _expired(PENDING_URI):
            return False
        try:
            PENDING_URI.unlink()
        except OSError:
            return False
        return True


def peek_pending():
    """Read the pending argument, leaving it available for a later retry.
    An expired one is deleted instead: an old click must not start a game."""
    expire_pending()
    with _pending_lock(shared=True):
        try:
            return os.fsdecode(PENDING_URI.read_bytes())
        except (FileNotFoundError, OSError):
            return None


def clear_pending(uri=None):
    """Remove the pending argument after it has been handed to Roblox.

    When *uri* is supplied, only remove the file if it still contains that
    same argument.  A newer browser click that arrived while startup was in
    progress is therefore not lost.
    """
    with _pending_lock():
        try:
            data = PENDING_URI.read_bytes()
        except (FileNotFoundError, OSError):
            return
        if uri is not None and data != _raw(uri):
            return
        try:
            PENDING_URI.unlink()
        except OSError:
            pass
