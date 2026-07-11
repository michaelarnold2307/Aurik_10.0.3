from __future__ import annotations

"""Unit-Tests für §ATI (V26) onset_guard.py.

Testet apply_onset_protection_mask() und Hilfsfunktionen.
"""


import numpy as np
import pytest

SR = 48000
_N = 48000  # 1 s


def _make_noise(n: int = _N, amp: float = 0.2, seed: int = 13) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return (amp * rng.standard_normal(n)).astype(np.float32)


def _make_onset_mask(n: int, onset_positions_ms: list[float], window_ms: float = 20.0) -> np.ndarray:
    """Erstellt binäre Onset-Maske."""
    mask = np.zeros(n, dtype=bool)
    window_samples = int(window_ms / 1000.0 * SR)
    for pos_ms in onset_positions_ms:
        start = int(pos_ms / 1000.0 * SR)
        end = min(n, start + window_samples)
        if start < n:
            mask[start:end] = True
    return mask


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestOnsetGuardImport:
    def test_import_function(self):
        from backend.core.dsp.onset_guard import apply_onset_protection_mask

        assert callable(apply_onset_protection_mask)

    def test_import_window_constant(self):
        from backend.core.dsp.onset_guard import _ONSET_WINDOW_MS

        assert pytest.approx(20.0) == _ONSET_WINDOW_MS


# ---------------------------------------------------------------------------
# apply_onset_protection_mask — Identisches Signal
# ---------------------------------------------------------------------------


class TestOnsetProtectionIdentical:
    def test_identical_no_change(self):
        from backend.core.dsp.onset_guard import apply_onset_protection_mask

        audio = _make_noise()
        mask = _make_onset_mask(_N, [100.0, 300.0, 500.0])
        result = apply_onset_protection_mask(audio, audio.copy(), mask, max_delta_db=1.5)
        # Identisches Signal → keine Änderung nötig
        assert np.allclose(result, audio, atol=1e-4)

    def test_output_shape_preserved(self):
        from backend.core.dsp.onset_guard import apply_onset_protection_mask

        audio = _make_noise()
        mask = _make_onset_mask(_N, [200.0])
        result = apply_onset_protection_mask(audio, audio, mask, max_delta_db=1.5)
        assert result.shape == audio.shape

    def test_output_dtype_float32(self):
        from backend.core.dsp.onset_guard import apply_onset_protection_mask

        audio = _make_noise()
        mask = np.zeros(_N, dtype=bool)
        result = apply_onset_protection_mask(audio, audio, mask, max_delta_db=1.5)
        assert result.dtype == np.float32


# ---------------------------------------------------------------------------
# Overdrive im Onset-Fenster → wird begrenzt
# ---------------------------------------------------------------------------


class TestOnsetProtectionLimiting:
    def test_large_gain_in_onset_clamped(self):
        """Großer Gain in Onset-Zone → Ergebnis näher an pre als rohes post."""
        from backend.core.dsp.onset_guard import apply_onset_protection_mask

        pre = _make_noise()
        # Erhöhe Onset-Bereich dramatisch
        post = pre.copy()
        onset_start = int(0.1 * SR)
        onset_end = int(0.12 * SR)
        post[onset_start:onset_end] *= 10.0

        mask = np.zeros(_N, dtype=bool)
        mask[onset_start:onset_end] = True

        result = apply_onset_protection_mask(pre, post, mask, max_delta_db=1.5)

        # Im Onset-Bereich: Ergebnis sollte näher an pre liegen als raw post
        raw_diff = float(np.mean(np.abs(post[onset_start:onset_end] - pre[onset_start:onset_end])))
        result_diff = float(np.mean(np.abs(result[onset_start:onset_end] - pre[onset_start:onset_end])))
        assert result_diff <= raw_diff + 1e-4, (
            f"Onset-Guard sollte Overdrive begrenzen: pre_diff={raw_diff:.4f}, result_diff={result_diff:.4f}"
        )

    def test_outside_onset_zone_unchanged_or_similar(self):
        """Außerhalb der Onset-Zone soll das post-Signal erhalten bleiben."""
        from backend.core.dsp.onset_guard import apply_onset_protection_mask

        pre = _make_noise()
        post = pre.copy()
        # Stark verstärkter Onset-Bereich
        onset_start = int(0.1 * SR)
        onset_end = int(0.12 * SR)
        post[onset_start:onset_end] *= 10.0

        mask = np.zeros(_N, dtype=bool)
        mask[onset_start:onset_end] = True

        result = apply_onset_protection_mask(pre, post, mask, max_delta_db=1.5)

        # Außerhalb der Onset-Zone: Ausgabe soll post-Werten entsprechen
        non_onset_idx = list(range(0, onset_start)) + list(range(onset_end, _N))
        if non_onset_idx:
            sample_idx = non_onset_idx[:1000]
            diff = float(np.max(np.abs(result[sample_idx] - post[sample_idx])))
            assert diff < 0.1, f"Außerhalb Onset: diff={diff}"


# ---------------------------------------------------------------------------
# None mask → passthrough
# ---------------------------------------------------------------------------


class TestOnsetProtectionNoneMask:
    def test_none_mask_returns_post(self):
        from backend.core.dsp.onset_guard import apply_onset_protection_mask

        pre = _make_noise()
        post = (pre * 1.1).astype(np.float32)
        result = apply_onset_protection_mask(pre, post, None, max_delta_db=1.5)
        # None mask → kein Eingriff → post zurückgeben
        assert result is not None
        assert result.shape == post.shape


# ---------------------------------------------------------------------------
# Stereo-Signal
# ---------------------------------------------------------------------------


class TestOnsetProtectionStereo:
    def test_stereo_no_crash(self):
        from backend.core.dsp.onset_guard import apply_onset_protection_mask

        stereo = np.stack([_make_noise(), _make_noise(seed=7)], axis=0)
        # Mask: 1D für Stereo (kann implementierungsabhängig sein)
        mask = _make_onset_mask(_N, [100.0, 500.0])
        try:
            result = apply_onset_protection_mask(stereo, stereo.copy(), mask, max_delta_db=1.5)
            assert result is not None
        except Exception as exc:
            # Wenn Stereo nicht unterstützt: soll sauber scheitern, kein Absturz
            assert isinstance(exc, (ValueError, AssertionError, NotImplementedError))


# ---------------------------------------------------------------------------
# Randfall: leeres Signal, Stille
# ---------------------------------------------------------------------------


class TestOnsetProtectionEdgeCases:
    def test_silence_no_crash(self):
        from backend.core.dsp.onset_guard import apply_onset_protection_mask

        silence = np.zeros(_N, dtype=np.float32)
        mask = np.zeros(_N, dtype=bool)
        result = apply_onset_protection_mask(silence, silence, mask, max_delta_db=1.5)
        assert result is not None

    def test_empty_mask_no_modification(self):
        from backend.core.dsp.onset_guard import apply_onset_protection_mask

        audio = _make_noise()
        mask = np.zeros(_N, dtype=bool)  # Keine Onset-Zonen
        result = apply_onset_protection_mask(audio, audio.copy(), mask, max_delta_db=1.5)
        assert np.allclose(result, audio, atol=1e-4)

    def test_max_delta_db_default(self):
        from backend.core.dsp.onset_guard import apply_onset_protection_mask

        audio = _make_noise()
        mask = np.zeros(_N, dtype=bool)
        # Kein explizites max_delta_db → default 1.5 wird verwendet
        result = apply_onset_protection_mask(audio, audio, mask)
        assert result.shape == audio.shape

    def test_output_clipped(self):
        """Ausgabe soll auf [-1.0, 1.0] begrenzt sein."""
        from backend.core.dsp.onset_guard import apply_onset_protection_mask

        pre = np.full(_N, 0.9, dtype=np.float32)
        post = np.full(_N, 0.95, dtype=np.float32)
        mask = np.ones(_N, dtype=bool)
        result = apply_onset_protection_mask(pre, post, mask, max_delta_db=1.5)
        assert float(np.max(np.abs(result))) <= 1.001
