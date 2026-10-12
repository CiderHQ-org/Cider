"""RobloxSession objects for tests: the constructor's state, nothing started."""
from unittest.mock import patch

from macoblox import core


def bare_session(settings=None):
    """Built by the real constructor, so new session state cannot be missed;
    only its removal of a stale quit sentinel is skipped."""
    with patch.object(type(core.QUIT_SENTINEL), "unlink"):
        return core.RobloxSession(dict(core.DEFAULT_SETTINGS) if settings is None else settings)
