"""No activation switch: a reviewed source release is required. Import is inert."""


def release_enabled():
    return False


def require_release():
    if not release_enabled():
        raise ValueError("HOST71_LIVE_HARD_BLOCKED")
