"""Cider user directories and migration from MacOBlox installations."""
import logging
import os
from functools import lru_cache
from pathlib import Path


def migrate_directory(source, target):
    """Move a legacy directory only when the destination has no user data.

    Renaming preserves cookie/keychain permissions. Existing Cider data wins;
    the legacy directory is then left available for manual recovery.
    """
    source, target = Path(source), Path(target)
    if source == target or not source.is_dir():
        return target
    try:
        if target.exists():
            if not target.is_dir() or any(target.iterdir()):
                return target
            target.rmdir()
        target.parent.mkdir(parents=True, exist_ok=True)
        source.rename(target)
    except OSError as error:
        logging.getLogger(__name__).warning("Could not migrate %s: %s; using legacy data", source, error)
        return source
    return target


@lru_cache(maxsize=3)
def user_directory(kind):
    defaults = {"CONFIG": Path.home() / ".config", "CACHE": Path.home() / ".cache",
                "DATA": Path.home() / ".local" / "share"}
    base = Path(os.environ.get(f"XDG_{kind}_HOME", defaults[kind]))
    return migrate_directory(base / "macoblox", base / "ciderhq")
