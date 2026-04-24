"""
Regression test: phase_09 must detect and remove crackle even in harmonic/vocal passages.

Before the fix, _classify_crackle_regions() required harmonic_ratio < 0.4 on the full
1-second window. Vocal content makes harmonic_ratio >= 0.4, so crackle in vocal
passages was never repaired (crackle_regions_found == 0).

Fix: removed harmonic_ratio < 0.4 from is_crackle; ZCR > 0.3 + centroid > 3000
is sufficient to identify impulsive broadband noise even in harmonic contexts.
"""

import numpy as np
import pytest

SR = 48_000


def _make_vocal_with_crackle(duration_s: float = 1.2) -> np.ndarray:
    """Synthesise a harmonic vocal-like tone (440 Hz + harmonics) with superimposed clicks.

    The signal has harmonic_ratio >> 0.4 so the old code would never classify
    it as a crackle region.  The clicks add broadband energy and raise ZCR.

    Clicks are modelled as exponential-decaying broadband noise bursts — matching
    real vinyl crackle (short-duration, HF-dominant impulse response of stylus+groove
    damage).  A smooth Hanning envelope would keep ZCR < 0.1 (too low for the zcr>0.3
    criterion); broadband noise bursts yield ZCR ≈ 0.45 in the crackle windows.
    """
    rng = np.random.default_rng(42)
    t = np.arange(int(duration_s * SR), dtype=np.float32) / SR

    # Harmonic vocal: f0=440 Hz plus overtones
    vocal = (
        0.40 * np.sin(2 * np.pi * 440 * t)
        + 0.20 * np.sin(2 * np.pi * 880 * t)
        + 0.12 * np.sin(2 * np.pi * 1320 * t)
        + 0.07 * np.sin(2 * np.pi * 1760 * t)
    ).astype(np.float32)

    # Superimpose vinyl-like impulse crackle (25 clicks randomly distributed).
    # Each click = exponential-decaying broadband noise burst (2 ms): high ZCR + high centroid.
    audio = vocal.copy()
    n_clicks = 25
    click_positions = rng.integers(SR // 4, int(duration_s * SR) - SR // 4, size=n_clicks)
    click_len = int(0.002 * SR)  # 2 ms broadband burst
    for pos in click_positions:
        click_sign = rng.choice([-1.0, 1.0])
        noise_burst = rng.standard_normal(click_len).astype(np.float32)
        decay = np.exp(-np.arange(click_len, dtype=np.float32) * 3.0 / click_len)
        click = click_sign * 0.55 * noise_burst * decay
        s, e = pos, pos + click_len
        if s < 0 or e > len(audio):
            continue
        audio[s:e] += click

    audio = np.clip(audio, -1.0, 1.0)
    return audio


@pytest.fixture
def phase09():
    from backend.core.phases.phase_09_crackle_removal import CrackleRemovalPhase

    return CrackleRemovalPhase(sample_rate=SR)


def test_crackle_regions_detected_in_vocal_passage(phase09):
    """crackle_regions must be non-empty when clicks overlay a harmonic signal."""
    audio = _make_vocal_with_crackle()
    params = {
        # 3.5 σ: detects synthesized clicks (adaptive_threshold ≈ 0.37 < click peak ≈ 0.55).
        # Production uses 0.15 (more sensitive). 5.0 would yield adaptive_threshold ≈ 0.53
        # — too close to click amplitude for reliable detection on short windows.
        "transient_threshold": 3.5,
        "min_density": 2,
        "interpolation": "spectral",
        "background_model": False,
        "texture_preserve": 0.0,
    }
    t_short, t_medium, t_long = phase09._detect_transients_multiscale(audio, params)
    regions = phase09._classify_crackle_regions(audio, t_short, t_medium, t_long, params)
    assert len(regions) > 0, (
        "No crackle regions detected in vocal+crackle passage. "
        "harmonic_ratio guard likely still blocking vocal regions."
    )


def test_crackle_removed_in_vocal_passage(phase09):
    """Restored signal must have lower HF impulsive energy than input in vocal+crackle region."""
    audio = _make_vocal_with_crackle()

    result = phase09.process(
        audio,
        material_type="vinyl",
        strength=1.0,
        mode="restoration",
        context=None,
    )
    assert result.success, "process() must succeed"
    restored = result.audio
    assert restored.shape == audio.shape

    # Crackle regions must have been detected (guard was removed for vocal passages).
    n_regions = result.modifications.get("crackle_regions_found", 0)
    assert n_regions > 0, (
        "No crackle regions found — centroid/ZCR guard may have been re-introduced, "
        "blocking detection in harmonic-heavy vocal passages."
    )

    # The phase must report measurable crackle reduction (HF impulsive energy).
    # Even the DSP fallback (texture_preserve blend) attenuates click HF energy ≥ 1 dB.
    reduction_db = result.modifications.get("crackle_reduction_db", 0.0)
    assert reduction_db > 0.5, (
        f"Expected >0.5 dB crackle reduction, got {reduction_db:.1f} dB. "
        f"Phase 09 may have processed vocal passage as passthrough."
    )

    # The output must differ from the input (processing did happen).
    diff_energy = float(np.mean((audio.astype(np.float64) - restored.astype(np.float64)) ** 2))
    assert diff_energy > 1e-8, (
        f"Output identical to input (diff_energy={diff_energy:.2e}): "
        f"phase_09 skipped the vocal+crackle passage entirely."
    )


def test_pure_harmonic_not_over_processed(phase09):
    """A pure harmonic signal without crackle must not be silenced or distorted."""
    np.random.default_rng(7)
    t = np.arange(SR, dtype=np.float32) / SR
    # Clean vocal tone, no crackle
    audio = (
        0.40 * np.sin(2 * np.pi * 440 * t) + 0.20 * np.sin(2 * np.pi * 880 * t) + 0.08 * np.sin(2 * np.pi * 1320 * t)
    ).astype(np.float32)

    params = {
        "transient_threshold": 3.5,
        "min_density": 2,
        "interpolation": "spectral",
        "background_model": False,
        "texture_preserve": 0.0,
    }
    t_short, t_medium, t_long = phase09._detect_transients_multiscale(audio, params)
    regions = phase09._classify_crackle_regions(audio, t_short, t_medium, t_long, params)

    # Pure sine should generate very few or no crackle regions
    total_crackle_samples = sum(e - s for s, e in regions)
    assert total_crackle_samples <= SR * 0.10, (
        f"Pure harmonic signal falsely classified as crackle: {total_crackle_samples / SR:.2f}s of {1.0:.2f}s total"
    )
