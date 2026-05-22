"""Unit-Tests: PrintThroughReductionPhase._compute_print_through_profile() (§2.56)."""

import numpy as np

from backend.core.phases.phase_57_print_through_reduction import (
    PrintThroughReductionPhase,
    _find_delays,
    _spectral_coherence,
)


def _profile(material: str, qm: str = "balanced", rest: float = 50.0) -> dict:
    return PrintThroughReductionPhase._compute_print_through_profile(material, qm, rest)


def test_tape_more_sensitive_than_cd():
    tape = _profile("reel_tape")
    cd = _profile("cd_digital")
    assert tape["min_print_through_score"] < cd["min_print_through_score"]


def test_quality_adjustment():
    base = _profile("reel_tape", "balanced", 60.0)
    q = _profile("reel_tape", "quality", 60.0)
    assert q["min_print_through_score"] < base["min_print_through_score"]
    assert q["coherence_floor"] > base["coherence_floor"]


def test_fast_adjustment():
    base = _profile("reel_tape", "balanced", 60.0)
    fast = _profile("reel_tape", "fast", 60.0)
    assert fast["min_print_through_score"] > base["min_print_through_score"]


def test_low_restorability_adjustment():
    high_rest = _profile("reel_tape", "balanced", 80.0)
    low_rest = _profile("reel_tape", "balanced", 20.0)
    assert low_rest["min_print_through_score"] < high_rest["min_print_through_score"]


def test_profile_bounds():
    for material in ["reel_tape", "tape", "cd_digital", "unknown"]:
        p = _profile(material, "maximum", 10.0)
        assert 0.05 <= p["min_print_through_score"] <= 0.30
        assert 0.90 <= p["coherence_floor"] <= 0.99


def test_process_metadata_contains_profile():
    phase = PrintThroughReductionPhase()
    audio = np.random.uniform(-0.2, 0.2, 48000).astype(np.float32)

    result = phase.process(
        audio,
        sample_rate=48000,
        quality_mode="quality",
        restorability_score=35.0,
        material_type="reel_tape",
        defect_scores={"print_through": 0.25},
        strength=0.5,
    )

    assert result.success
    assert "print_through_profile" in result.metadata
    assert "min_print_through_score" in result.metadata
    assert "coherence_floor" in result.metadata


def test_find_delays_detects_synthetic_post_echo():
    sr = 48000
    n = sr
    x = np.zeros(n, dtype=np.float64)
    x[5000:5010] = 1.0
    delay = int(0.040 * sr)
    x[5000 + delay : 5010 + delay] += 0.25

    d_pre, d_post = _find_delays(x, max_delay=int(0.100 * sr))
    assert d_post > 0
    assert abs(d_post - delay) < int(0.010 * sr)
    assert d_pre >= 0


def test_spectral_coherence_band_focus_penalizes_midband_damage():
    sr = 48000
    t = np.linspace(0.0, 1.0, sr, endpoint=False)
    clean = 0.5 * np.sin(2 * np.pi * 1000.0 * t)

    rng = np.random.default_rng(1234)
    noise = rng.normal(0.0, 1.0, size=clean.shape[0])
    # Bandbegrenzter Midband-Schaden (80 Hz-12 kHz Fokus der Kohärenzmetrik).
    from scipy import signal as sps

    sos = sps.butter(4, [800.0, 3200.0], btype="band", fs=sr, output="sos")
    band_noise = sps.sosfiltfilt(sos, noise)
    band_noise = 0.45 * band_noise / (np.max(np.abs(band_noise)) + 1e-9)
    damaged = clean + band_noise

    coh = _spectral_coherence(clean.astype(np.float64), damaged.astype(np.float64), sr)
    assert 0.0 <= coh <= 1.0
    assert coh < 0.90
