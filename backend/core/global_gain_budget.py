"""§GGB-1 Global Gain Budget (v10.13).

Cross-phase gain accumulator that prevents cumulative loudness inflation.
Tracks makeup gains across all phases and caps the total at a configurable
limit. Individual phases request gain budget; the coordinator approves or
caps based on global remaining budget.

Design:
  - Singleton pattern (thread-safe)
  - Per-phase request: budget.request(phase_id, gain_db, priority)
  - Returns approved gain (≤ requested)
  - Caps: 6 dB total pipeline, 2 dB per phase (except loudness norm)
  - best_effort phases get 0 dB
"""

from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)


class GlobalGainBudget:
    """Thread-safe singleton managing cumulative gain across all phases."""

    _TOTAL_BUDGET_DB: float = 6.0
    _MAX_PER_PHASE_DB: float = 2.0
    _LOUDNESS_NORM_PHASES: frozenset[str] = frozenset({"phase_40_loudness_normalization"})

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cumulative_db: float = 0.0
        self._phase_gains: dict[str, float] = {}

    def request(self, phase_id: str, requested_db: float, priority: str = "normal") -> float:
        """Request gain budget for a phase. Returns approved gain in dB.

        Args:
            phase_id: Phase identifier (e.g. "phase_12_wow_flutter_fix").
            requested_db: Requested makeup gain in dB (positive values only).
            priority: "normal", "high", or "best_effort".

        Returns:
            Approved gain in dB (0.0 ≤ returned ≤ requested).
        """
        requested = float(max(0.0, requested_db))
        if requested <= 0.0:
            return 0.0

        with self._lock:
            # best_effort phases get nothing
            if priority == "best_effort":
                logger.debug("§GGB-1: %s best_effort → 0 dB", phase_id)
                return 0.0

            # Per-phase cap (except loudness normalization)
            if phase_id not in self._LOUDNESS_NORM_PHASES:
                requested = min(requested, self._MAX_PER_PHASE_DB)

            # Global cap
            remaining = max(0.0, self._TOTAL_BUDGET_DB - self._cumulative_db)
            approved = min(requested, remaining)

            self._cumulative_db += approved
            self._phase_gains[phase_id] = approved

            if approved < requested:
                logger.info(
                    "§GGB-1: %s requested %.2f dB → approved %.2f dB "
                    "(cap: total %.2f/%.2f dB, remaining %.2f dB)",
                    phase_id, requested_db, approved,
                    self._cumulative_db, self._TOTAL_BUDGET_DB, remaining - approved,
                )

            return approved

    def reset(self) -> None:
        """Reset budget for a new pipeline run."""
        with self._lock:
            self._cumulative_db = 0.0
            self._phase_gains.clear()

    @property
    def cumulative_db(self) -> float:
        with self._lock:
            return self._cumulative_db

    @property
    def remaining_db(self) -> float:
        with self._lock:
            return max(0.0, self._TOTAL_BUDGET_DB - self._cumulative_db)


# Thread-safe singleton
_instance: GlobalGainBudget | None = None
_lock: threading.Lock = threading.Lock()


def get_global_gain_budget() -> GlobalGainBudget:
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = GlobalGainBudget()
    return _instance
