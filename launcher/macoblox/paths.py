"""Quadra user directories and migration from Cider and MacOBlox installations."""
import logging
import os
from functools import lru_cache
from pathlib import Path


def migrate_directory(source, target):
    """Move a legacy directory only when the destination has no user data.

    Renaming preserves cookie/keychain permissions. Existing Quadra data wins;
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


def migrate_directories(target, *sources):
    """Prefer the most recent legacy directory, retaining it if a move fails."""
    target = Path(target)
    for source in map(Path, sources):
        if source.is_dir():
            return migrate_directory(source, target)
    return target


@lru_cache(maxsize=3)
def user_directory(kind):
    defaults = {"CONFIG": Path.home() / ".config", "CACHE": Path.home() / ".cache",
                "DATA": Path.home() / ".local" / "share"}
    base = Path(os.environ.get(f"XDG_{kind}_HOME", defaults[kind]))
    return migrate_directories(base / "quadrahq", base / "ciderhq", base / "macoblox")
