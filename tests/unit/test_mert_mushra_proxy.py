"""Tests for backend.core.mert_mushra_proxy — MERT-based MUSHRA proxy evaluator.

Tests cover:
- Basic proxy scoring with synthetic audio pairs
- DSP-only fallback (MERT not loaded)
- Component metric ranges and monotonicity
- Edge cases (silence, identical audio, noise-only, short audio)
- Confidence levels with/without MERT
- Grade assignment thresholds
- Serialization via as_dict()
- Mono/stereo handling
- NaN/Inf guard
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from backend.core.mert_mushra_proxy import (
    MertMushraProxy,
    MushraProxyResult,
    _cosine_similarity,
    _extract_dsp_embedding,
    _grade,
    _to_mono,
    estimate_mushra_proxy,
    get_proxy_evaluator,
)

SR = 48_000
DURATION = 2.0  # seconds


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_tone(freq: float = 440.0, duration: float = DURATION, sr: int = SR) -> np.ndarray:
    """Generate a pure sine tone."""
    t = np.linspace(0, duration, int(sr * duration), dtype=np.float32)
    return 0.5 * np.sin(2 * np.pi * freq * t)


def _make_harmonic(f0: float = 220.0, n_harmonics: int = 5, duration: float = DURATION) -> np.ndarray:
    """Generate a harmonic signal with f0 and overtones."""
    t = np.linspace(0, duration, int(SR * duration), dtype=np.float32)
    sig = np.zeros_like(t)
    for k in range(1, n_harmonics + 1):
        sig += (0.3 / k) * np.sin(2 * np.pi * f0 * k * t)
    return np.clip(sig, -1.0, 1.0).astype(np.float32)


def _add_noise(audio: np.ndarray, snr_db: float = 20.0) -> np.ndarray:
    """Add white noise at a specified SNR."""
    rng = np.random.default_rng(42)
    rms_signal = np.sqrt(np.mean(audio ** 2) + 1e-12)
    rms_noise = rms_signal / (10 ** (snr_db / 20))
    noise = rng.standard_normal(len(audio)).astype(np.float32) * rms_noise
    return np.clip(audio + noise, -1.0, 1.0).astype(np.float32)


# ---------------------------------------------------------------------------
# Test: Singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_get_proxy_evaluator_returns_same_instance(self):
        a = get_proxy_evaluator()
        b = get_proxy_evaluator()
        assert a is b

    def test_instance_type(self):
        assert isinstance(get_proxy_evaluator(), MertMushraProxy)


# ---------------------------------------------------------------------------
# Test: Basic scoring
# ---------------------------------------------------------------------------


class TestBasicScoring:
    def test_identical_audio_high_score(self):
        """Identical reference and test should yield high proxy score."""
        ref = _make_harmonic()
        result = estimate_mushra_proxy(ref, ref, SR)
        assert result.proxy_score >= 85.0
        assert result.grade in ("Excellent", "Good")

    def test_noisy_audio_lower_score(self):
        """Adding noise should lower the proxy score."""
        ref = _make_harmonic()
        noisy = _add_noise(ref, snr_db=10.0)
        result = estimate_mushra_proxy(ref, noisy, SR)
        # Must be lower than identical
        result_ident = estimate_mushra_proxy(ref, ref, SR)
        assert result.proxy_score < result_ident.proxy_score

    def test_different_frequency_lower_score(self):
        """Completely different tonal content should score lower."""
        ref = _make_tone(440.0)
        test = _make_tone(880.0)
        result = estimate_mushra_proxy(ref, test, SR)
        assert result.proxy_score < 90.0

    def test_score_range(self):
        """Score must be in [0, 100]."""
        ref = _make_harmonic()
        test = _add_noise(ref, snr_db=5.0)
        result = estimate_mushra_proxy(ref, test, SR)
        assert 0.0 <= result.proxy_score <= 100.0

    def test_monotonicity_with_snr(self):
        """Higher SNR (less noise) should yield higher scores."""
        ref = _make_harmonic()
        score_20 = estimate_mushra_proxy(ref, _add_noise(ref, 20.0), SR).proxy_score
        score_10 = estimate_mushra_proxy(ref, _add_noise(ref, 10.0), SR).proxy_score
        score_5 = estimate_mushra_proxy(ref, _add_noise(ref, 5.0), SR).proxy_score
        assert score_20 >= score_10 >= score_5


# ---------------------------------------------------------------------------
# Test: Component metrics
# ---------------------------------------------------------------------------


class TestComponentMetrics:
    def test_nsim_range(self):
        ref = _make_harmonic()
        result = estimate_mushra_proxy(ref, ref, SR)
        assert 0.0 <= result.nsim <= 1.0

    def test_mcd_zero_for_identical(self):
        ref = _make_harmonic()
        result = estimate_mushra_proxy(ref, ref, SR)
        assert result.mcd_db < 1.0  # Near zero for identical

    def test_chroma_high_for_identical(self):
        ref = _make_harmonic()
        result = estimate_mushra_proxy(ref, ref, SR)
        assert result.chroma_corr >= 0.95

    def test_lufs_small_for_identical(self):
        ref = _make_harmonic()
        result = estimate_mushra_proxy(ref, ref, SR)
        assert abs(result.lufs_diff_lu) < 0.5

    def test_component_scores_dict_populated(self):
        ref = _make_harmonic()
        result = estimate_mushra_proxy(ref, ref, SR)
        assert "nsim" in result.component_scores
        assert "mcd" in result.component_scores
        assert "chroma" in result.component_scores
        assert "lufs" in result.component_scores


# ---------------------------------------------------------------------------
# Test: Confidence and MERT availability
# ---------------------------------------------------------------------------


class TestConfidence:
    def test_dsp_fallback_confidence(self):
        """Without MERT loaded, confidence should be DSP-only level."""
        ref = _make_harmonic()
        result = estimate_mushra_proxy(ref, ref, SR)
        # MERT is not loaded in test environment → DSP-only
        assert result.confidence <= 0.70
        assert math.isnan(result.mert_cosine)

    def test_calibration_stage_is_1(self):
        ref = _make_harmonic()
        result = estimate_mushra_proxy(ref, ref, SR)
        assert result.calibration_stage == 1


# ---------------------------------------------------------------------------
# Test: Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_silence(self):
        silence = np.zeros(int(SR * 1.0), dtype=np.float32)
        result = estimate_mushra_proxy(silence, silence, SR)
        assert 0.0 <= result.proxy_score <= 100.0

    def test_very_short_audio(self):
        ref = _make_tone(duration=0.05)  # 50 ms
        result = estimate_mushra_proxy(ref, ref, SR)
        assert 0.0 <= result.proxy_score <= 100.0

    def test_empty_audio(self):
        empty = np.array([], dtype=np.float32)
        result = estimate_mushra_proxy(empty, empty, SR)
        assert result.proxy_score == 0.0

    def test_nan_input_guarded(self):
        ref = _make_harmonic()
        bad = ref.copy()
        bad[100:200] = np.nan
        result = estimate_mushra_proxy(ref, bad, SR)
        assert 0.0 <= result.proxy_score <= 100.0
        assert not math.isnan(result.proxy_score)

    def test_inf_input_guarded(self):
        ref = _make_harmonic()
        bad = ref.copy()
        bad[50] = np.inf
        result = estimate_mushra_proxy(ref, bad, SR)
        assert not math.isnan(result.proxy_score)

    def test_different_lengths(self):
        """Ref and test with different lengths should not crash."""
        ref = _make_tone(duration=2.0)
        test = _make_tone(duration=1.5)
        result = estimate_mushra_proxy(ref, test, SR)
        assert 0.0 <= result.proxy_score <= 100.0


# ---------------------------------------------------------------------------
# Test: Stereo / mono handling
# ---------------------------------------------------------------------------


class TestStereoMono:
    def test_stereo_input(self):
        ref_mono = _make_harmonic()
        ref_stereo = np.stack([ref_mono, ref_mono])
        result = estimate_mushra_proxy(ref_stereo, ref_stereo, SR)
        assert result.proxy_score >= 80.0

    def test_mono_vs_stereo_similar(self):
        ref = _make_harmonic()
        ref_stereo = np.stack([ref, ref])
        r_mono = estimate_mushra_proxy(ref, ref, SR)
        r_stereo = estimate_mushra_proxy(ref_stereo, ref_stereo, SR)
        # Should be close since stereo is just duplicated mono
        assert abs(r_mono.proxy_score - r_stereo.proxy_score) < 5.0


# ---------------------------------------------------------------------------
# Test: Grade assignment
# ---------------------------------------------------------------------------


class TestGrade:
    def test_grade_excellent(self):
        assert _grade(95.0) == "Excellent"

    def test_grade_good(self):
        assert _grade(85.0) == "Good"

    def test_grade_fair(self):
        assert _grade(65.0) == "Fair"

    def test_grade_poor(self):
        assert _grade(45.0) == "Poor"

    def test_grade_bad(self):
        assert _grade(15.0) == "Bad"

    def test_grade_boundary_91(self):
        assert _grade(91.0) == "Excellent"

    def test_grade_boundary_80(self):
        assert _grade(80.0) == "Good"

    def test_grade_boundary_60(self):
        assert _grade(60.0) == "Fair"

    def test_grade_boundary_40(self):
        assert _grade(40.0) == "Poor"


# ---------------------------------------------------------------------------
# Test: Serialization
# ---------------------------------------------------------------------------


class TestSerialization:
    def test_as_dict_keys(self):
        ref = _make_harmonic()
        result = estimate_mushra_proxy(ref, ref, SR)
        d = result.as_dict()
        assert "proxy_score" in d
        assert "grade" in d
        assert "confidence" in d
        assert "calibration_stage" in d
        assert "nsim" in d

    def test_as_dict_types(self):
        ref = _make_harmonic()
        d = estimate_mushra_proxy(ref, ref, SR).as_dict()
        assert isinstance(d["proxy_score"], float)
        assert isinstance(d["grade"], str)
        assert isinstance(d["calibration_stage"], int)

    def test_passes_threshold(self):
        ref = _make_harmonic()
        result = estimate_mushra_proxy(ref, ref, SR)
        # Identical audio should pass 80
        assert result.passes_threshold(80.0)


# ---------------------------------------------------------------------------
# Test: Cosine similarity
# ---------------------------------------------------------------------------


class TestCosineSimilarity:
    def test_identical_vectors(self):
        v = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        assert abs(_cosine_similarity(v, v) - 1.0) < 1e-6

    def test_orthogonal_vectors(self):
        a = np.array([1.0, 0.0], dtype=np.float32)
        b = np.array([0.0, 1.0], dtype=np.float32)
        assert abs(_cosine_similarity(a, b)) < 1e-6

    def test_zero_vector(self):
        a = np.array([1.0, 2.0], dtype=np.float32)
        b = np.zeros(2, dtype=np.float32)
        assert _cosine_similarity(a, b) == 0.0

    def test_parallel_vectors(self):
        a = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        b = 5.0 * a
        assert abs(_cosine_similarity(a, b) - 1.0) < 1e-6


# ---------------------------------------------------------------------------
# Test: DSP embedding extraction
# ---------------------------------------------------------------------------


class TestDSPEmbedding:
    def test_output_shape(self):
        audio = _make_harmonic(duration=1.0)
        emb = _extract_dsp_embedding(audio, SR)
        assert emb.shape == (512,)

    def test_l2_normalized(self):
        audio = _make_harmonic(duration=1.0)
        emb = _extract_dsp_embedding(audio, SR)
        norm = np.linalg.norm(emb)
        assert abs(norm - 1.0) < 0.01 or norm < 1e-6  # either unit or zero

    def test_no_nan(self):
        audio = _make_harmonic(duration=1.0)
        emb = _extract_dsp_embedding(audio, SR)
        assert np.isfinite(emb).all()

    def test_different_audio_different_embedding(self):
        a = _make_tone(440.0, duration=1.0)
        b = _make_tone(880.0, duration=1.0)
        emb_a = _extract_dsp_embedding(a, SR)
        emb_b = _extract_dsp_embedding(b, SR)
        cos = _cosine_similarity(emb_a, emb_b)
        assert cos < 0.99  # Different audio → different embedding


# ---------------------------------------------------------------------------
# Test: _to_mono utility
# ---------------------------------------------------------------------------


class TestToMono:
    def test_mono_passthrough(self):
        mono = np.ones(100, dtype=np.float32)
        result = _to_mono(mono)
        assert result.ndim == 1
        assert len(result) == 100

    def test_stereo_to_mono(self):
        stereo = np.ones((2, 100), dtype=np.float32)
        result = _to_mono(stereo)
        assert result.ndim == 1

    def test_nan_replaced(self):
        bad = np.array([1.0, np.nan, 0.5], dtype=np.float32)
        result = _to_mono(bad)
        assert np.isfinite(result).all()
