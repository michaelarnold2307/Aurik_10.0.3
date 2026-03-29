"""
backend/core/community_rating_platform.py — Community rating aggregator
=======================================================================
"""

from __future__ import annotations


class CommunityRatingPlatform:
    """Collects community ratings and computes per-dimension averages."""

    def __init__(self) -> None:
        self._ratings: list[dict[str, float]] = []

    def add_rating(self, user: str, scores: dict[str, float]) -> None:
        """Add *scores* from community *user*."""
        self._ratings.append(dict(scores))

    def aggregate(self) -> dict[str, float]:
        """Return the mean score per dimension across all ratings."""
        if not self._ratings:
            return {}
        keys = self._ratings[0].keys()
        return {k: sum(r.get(k, 0.0) for r in self._ratings) / len(self._ratings) for k in keys}


# ---------------------------------------------------------------------------
# Singleton accessor (thread-safe, double-checked locking)
# ---------------------------------------------------------------------------
import threading as _threading

_community_rating_platform_instance = None
_community_rating_platform_lock = _threading.Lock()


def get_community_rating_platform() -> CommunityRatingPlatform:
    """Return the process-wide singleton CommunityRatingPlatform instance."""
    global _community_rating_platform_instance
    if _community_rating_platform_instance is None:
        with _community_rating_platform_lock:
            if _community_rating_platform_instance is None:
                _community_rating_platform_instance = CommunityRatingPlatform()
    return _community_rating_platform_instance
