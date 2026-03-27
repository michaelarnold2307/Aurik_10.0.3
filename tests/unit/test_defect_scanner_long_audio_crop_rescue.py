"""Regression tests for long-audio event detection outside center crop.

When scan() center-crops long audio to 60 s for performance, event defects
near intro/outro can be missed. These tests lock in the full-audio rescue pass
for cheap event detectors (clicks, clipping).
"""

from __future__ import annotations

import numpy as np
import backend.core.defect_scanner as defect_scanner_module

from backend.core.defect_scanner import DefectScanner, DefectType


SR = 48_000


def _long_base_audio(duration_s: float = 70.0) -> np.ndarray:
    t = np.arange(int(duration_s * SR), dtype=np.float64) / SR
    # Keep base signal low and stable so injected defects dominate detection.
    audio = 0.10 * np.sin(2.0 * np.pi * 440.0 * t)
    return audio.astype(np.float32)


def test_clicks_outside_center_crop_are_detected() -> None:
    """Clicks at intro (outside center 60 s crop) must still be detected."""
    audio = _long_base_audio()

    # For 70 s audio, center-crop spans ~5..65 s; inject clicks at ~1 s.
    click_positions = [int(1.00 * SR), int(1.30 * SR), int(1.60 * SR)]
    for pos in click_positions:
        audio[pos] = 1.0
        audio[pos + 1] = -1.0

    scanner = DefectScanner(sample_rate=SR)
    result = scanner.scan(audio, SR)

    score = result.scores[DefectType.CLICKS]
    assert score.severity > 0.0
    assert any(loc[0] < 5.0 for loc in score.locations)


def test_clipping_outside_center_crop_is_detected(monkeypatch) -> None:
    """Hard clipping near outro (outside center crop) must still be detected."""
    # Keep this test deterministic: use amplitude fallback detector path.
    monkeypatch.setattr(defect_scanner_module, "_CLIPPING_DETECTION_AVAILABLE", False)

    audio = _long_base_audio()

    # For 70 s audio, center-crop spans ~5..65 s; inject hard clipping at ~68 s.
    # Use overdriven sinusoid clipped to [-1, 1] to get stable odd-harmonic profile.
    start = int(68.0 * SR)
    end = int(69.0 * SR)
    t = np.arange(end - start, dtype=np.float64) / SR
    overdriven = 2.5 * np.sin(2.0 * np.pi * 1200.0 * t)
    audio[start:end] = np.clip(overdriven, -1.0, 1.0).astype(np.float32)

    scanner = DefectScanner(sample_rate=SR)
    result = scanner.scan(audio, SR)

    score = result.scores[DefectType.CLIPPING]
    assert score.severity > 0.0
    assert any(loc[0] > 65.0 for loc in score.locations)


def test_long_audio_center_crop_marks_locality_limited_for_non_rechecked_type() -> None:
    """Long audio scan should mark crop-locality limits for center-crop-only defect locations."""
    audio = _long_base_audio(duration_s=70.0)
    scanner = DefectScanner(sample_rate=SR)
    result = scanner.scan(audio, SR)

    score = result.scores[DefectType.HUM]
    assert isinstance(score.metadata, dict)
    assert score.metadata.get("confidence_calibrated") is True
    if score.locations:
        assert score.metadata.get("crop_locality_limited") is True
