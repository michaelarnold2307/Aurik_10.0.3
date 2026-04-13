"""Regression tests for MusicalQualityAssurance processing intensity handling."""

from __future__ import annotations

import pytest

from backend.core.musical_quality_assurance import (
    IntegrityCheckResult,
    MediumType,
    MusicalQualityAssurance,
    ProcessingMode,
)
from backend.core.quality_prediction import QualityEstimate, QualityLevel


def _quality(overall: float = 80.0) -> QualityEstimate:
    return QualityEstimate(
        overall_score=overall,
        quality_level=QualityLevel.GOOD,
        snr_db=65.0,
        dynamic_range_db=18.0,
        thd_percent=0.3,
        clarity=0.8,
        warmth=0.7,
        brightness=0.6,
        naturalness=0.8,
        authenticity=0.85,
        confidence=0.9,
        bandwidth_hz=(20.0, 18000.0),
        has_artifacts=False,
        artifact_types=[],
    )


def _integrity_ok() -> IntegrityCheckResult:
    return IntegrityCheckResult(
        passed=True,
        overall_integrity=0.95,
        violations=[],
        violation_details={},
        naturalness_change=0.0,
        character_preservation=1.0,
        overprocessing_risk=0.1,
        recommendations=[],
        should_rollback=False,
        should_stop_processing=False,
    )


def test_validate_final_quality_uses_unique_modules_for_intensity(monkeypatch):
    """Duplicate module names must not inflate processing intensity."""
    mqa = MusicalQualityAssurance()

    monkeypatch.setattr(mqa.analyzer, "analyze_quality", lambda _audio, _sr: _quality())
    monkeypatch.setattr(mqa, "check_quality_gate", lambda *_args, **_kwargs: (True, "ok"))
    monkeypatch.setattr(mqa, "check_musical_integrity", lambda *_args, **_kwargs: _integrity_ok())

    report = mqa.validate_final_quality(
        original_audio=[0.0, 0.0],
        processed_audio=[0.0, 0.0],
        sample_rate=48000,
        medium_type=MediumType.VINYL_33,
        processing_mode=ProcessingMode.RESTORATION,
        modules_applied=[
            "denoise",
            "denoise",
            "declip",
            "declip",
            "denoise",
            "declip",
            "denoise",
            "declip",
            "denoise",
            "declip",
        ],
    )

    # §2.54: Divisor ist jetzt 50 (Aurik-9-Pipeline-Max), nicht 8.
    # 2 unique modules / 50 = 0.04 — Deduplizierung ist weiterhin korrekt.
    assert report.processing_intensity == pytest.approx(2 / 50.0, abs=1e-6)
    assert report.overprocessed is False
    assert "OVERPROCESSED" not in report.verdict
