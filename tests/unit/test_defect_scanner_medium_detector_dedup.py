"""Regression tests for medium detector deduplication in DefectScanner.scan()."""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import patch

import numpy as np

from backend.core.defect_scanner import DefectScanner, MaterialType


@dataclass
class _StubForensicMedium:
    transfer_chain: list[str] = field(default_factory=lambda: ["vinyl", "mp3_low"])
    primary_material: str = "vinyl"
    confidence: float = 0.81


def _silence(sr: int = 48_000, duration_s: float = 0.1) -> np.ndarray:
    n = int(sr * duration_s)
    return np.zeros(n, dtype=np.float32)


def test_scan_uses_cached_forensic_medium_without_second_detect_call() -> None:
    """If forensic_medium_result is provided, no second MediumDetector call is allowed."""
    scanner = DefectScanner()
    cached_medium = _StubForensicMedium()

    with patch(
        "backend.core.forensics.medium_detector.MediumDetector",
        side_effect=AssertionError("MediumDetector must not be instantiated when cached forensic result is provided"),
    ):
        result = scanner.scan(
            _silence(),
            48_000,
            material_type=MaterialType.VINYL,
            file_ext=".mp3",
            forensic_medium_result=cached_medium,
        )

    assert result.transfer_chain_raw is cached_medium
    assert "vinyl" in str(result.transfer_chain_str)


def test_scan_calls_medium_detector_once_when_no_cached_forensic_result() -> None:
    """Without cached forensic medium, exactly one MediumDetector.detect() call is expected."""
    scanner = DefectScanner()
    calls = {"init": 0, "detect": 0}

    class _FakeMediumDetector:
        def __init__(self) -> None:
            calls["init"] += 1

        def detect(self, audio: np.ndarray, sr: int, file_ext: str | None = None):
            calls["detect"] += 1
            return _StubForensicMedium(transfer_chain=["tape", "mp3_low"], primary_material="tape", confidence=0.77)

    with patch("backend.core.forensics.medium_detector.MediumDetector", _FakeMediumDetector):
        result = scanner.scan(
            _silence(),
            48_000,
            material_type=MaterialType.TAPE,
            file_ext=".mp3",
            forensic_medium_result=None,
        )

    assert calls == {"init": 1, "detect": 1}
    assert "tape" in str(result.transfer_chain_str)
