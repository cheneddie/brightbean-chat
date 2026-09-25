"""Platform-neutral follower relationship state.

The value is intentionally three-state. UNKNOWN means the platform could not
reliably answer (no consent/IGSID, rate limit, auth/API failure, or missing
field); callers must never reinterpret it as NOT_FOLLOWING.
"""

from enum import StrEnum

__all__ = ["FollowStatus"]


class FollowStatus(StrEnum):
    FOLLOWING = "following"
    NOT_FOLLOWING = "not_following"
    UNKNOWN = "unknown"
