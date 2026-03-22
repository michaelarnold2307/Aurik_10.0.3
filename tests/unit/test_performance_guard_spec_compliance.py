from __future__ import annotations

import time

import pytest

from backend.core.performance_guard import PerformanceGuard, QualityMode


class TestPerformanceGuardSpecCompliance:
    """Spec-Compliance für PerformanceGuard (§RT8/2026)."""

    def test_limits_match_2026_spec(self) -> None:
        assert PerformanceGuard.LIMIT_FAST == pytest.approx(3.0)
        assert PerformanceGuard.LIMIT_BALANCED == pytest.approx(8.0)
        assert PerformanceGuard.LIMIT_QUALITY == pytest.approx(10.0)
        assert PerformanceGuard.LIMIT_MAXIMUM == pytest.approx(15.0)
        assert PerformanceGuard.RT8_EXCELLENCE_BUDGET == pytest.approx(8.0)

    def test_target_mapping_uses_quality_budget(self) -> None:
        fast_guard = PerformanceGuard(mode=QualityMode.FAST, enforce_limit=True, enable_adaptive_skipping=True)
        balanced_guard = PerformanceGuard(mode=QualityMode.BALANCED, enforce_limit=True, enable_adaptive_skipping=True)
        quality_guard = PerformanceGuard(mode=QualityMode.QUALITY, enforce_limit=True, enable_adaptive_skipping=True)

        assert fast_guard.target_rt_factor == pytest.approx(3.0)
        assert balanced_guard.target_rt_factor == pytest.approx(8.0)
        assert quality_guard.target_rt_factor == pytest.approx(10.0)

    def test_start_phase_uses_monotonic_clock(self) -> None:
        guard = PerformanceGuard(mode=QualityMode.BALANCED, enforce_limit=True, enable_adaptive_skipping=True)
        guard.start_monitoring(10.0)
        phase_start = guard.start_phase("denoise")
        now = time.perf_counter()
        assert phase_start <= now
        assert now - phase_start < 1.0

    def test_quality_mode_can_skip_low_priority_near_budget(self) -> None:
        guard = PerformanceGuard(mode=QualityMode.QUALITY, enforce_limit=True, enable_adaptive_skipping=True)
        guard.start_monitoring(10.0)
        # Simulate that ~9.95x RT are already spent on a 10s file.
        guard.start_time = time.perf_counter() - 99.5
        guard.audio_duration = 10.0

        should_skip = guard.should_skip_phase(
            phase_id="metadata_embedding",
            estimated_time_seconds=1.5,
            remaining_phases=2,
        )
        assert should_skip is True

    def test_quality_mode_rt_exceeded_no_early_exit_below_30min(self) -> None:
        """§2.38 KMV: RT-Limit-Überschreitung → Warnung, KEIN Abbruch.

        Nur das 30-Minuten-Absolutlimit darf die Pipeline abbrechen.
        """
        guard = PerformanceGuard(mode=QualityMode.QUALITY, enforce_limit=True, enable_adaptive_skipping=True)
        guard.start_monitoring(10.0)
        guard.current_rt_factor = 10.1

        # RT exceeded, but <30min absolute → pipeline continues
        assert guard.check_early_exit(remaining_phases=3) is False

    def test_absolute_30min_limit_triggers_early_exit(self) -> None:
        """§9.5: 30-Minuten-Absolutlimit ist der einzige harte Abbruchgrund."""
        guard = PerformanceGuard(mode=QualityMode.QUALITY, enforce_limit=True, enable_adaptive_skipping=True)
        guard.start_monitoring(10.0)
        # Simulate 1801 seconds elapsed (>30min)
        guard.start_time = time.perf_counter() - 1801.0
        guard.current_rt_factor = 180.0

        assert guard.check_early_exit(remaining_phases=3) is True

    def test_musical_excellence_phase_never_skipped_even_near_limit(self) -> None:
        guard = PerformanceGuard(mode=QualityMode.BALANCED, enforce_limit=True, enable_adaptive_skipping=True)
        guard.start_monitoring(10.0)
        guard.start_time = time.perf_counter() - 79.0
        guard.audio_duration = 10.0

        should_skip = guard.should_skip_phase(
            phase_id="excellence_optimizer",
            estimated_time_seconds=3.0,
            remaining_phases=1,
        )
        assert should_skip is False
