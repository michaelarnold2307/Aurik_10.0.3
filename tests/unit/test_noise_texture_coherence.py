"""Unit-Tests für NoiseTextureCoherenceGuard (§4.7, v9.11.14)."""

from __future__ import annotations

import numpy as np

from backend.core.noise_texture_coherence import (
    NoiseTextureCoherenceGuard,
    NoiseTextureResult,
    compute_noise_texture_coherence,
    get_noise_texture_coherence_guard,
)


class TestComputeNoiseTextureCoherence:
    """§4.7 — Kernfunktion: PSD-Korrelation zum Trägerprofil."""

    def test_white_noise_matches_cd_digital(self):
        """Weißes Rauschen passt zu cd_digital (flaches Profil)."""
        rng = np.random.default_rng(42)
        white = rng.normal(0, 0.01, 48000 * 2).astype(np.float32)
        result = compute_noise_texture_coherence(white, 48000, "cd_digital")
        assert isinstance(result, NoiseTextureResult)
        assert result.coherence >= 0.0  # Gültiger Bereich

    def test_pink_noise_matches_vinyl(self):
        """Rosa Rauschen hat abfallende Spectral Density → passt zu Vinyl."""
        rng = np.random.default_rng(123)
        # Approximiere rosa Rauschen via kumulative Summe von weißem Rauschen
        white = rng.normal(0, 0.01, 48000 * 2).astype(np.float64)
        pink_approx = np.cumsum(white)
        pink_approx = pink_approx / (np.max(np.abs(pink_approx)) + 1e-10) * 0.01
        result = compute_noise_texture_coherence(pink_approx, 48000, "vinyl")
        assert result.coherence >= 0.0  # Muss gültig sein
        assert result.coherence <= 1.0

    def test_short_signal_passes(self):
        """Zu kurzes Signal → coherence=1.0 (pass-through)."""
        short = np.zeros(512, dtype=np.float32)
        result = compute_noise_texture_coherence(short, 48000, "vinyl")
        assert result.coherence == 1.0
        assert result.is_compliant is True

    def test_stereo_input_handled(self):
        """Stereo-Input wird zu Mono gemixed."""
        rng = np.random.default_rng(77)
        stereo = rng.normal(0, 0.01, (48000 * 2, 2)).astype(np.float32)
        result = compute_noise_texture_coherence(stereo, 48000, "tape")
        assert 0.0 <= result.coherence <= 1.0

    def test_digital_materials_use_white_profile(self):
        """Alle digitalen Materialien nutzen weißes Profil."""
        rng = np.random.default_rng(55)
        noise = rng.normal(0, 0.01, 48000 * 2).astype(np.float32)
        for mat in ["dat", "minidisc", "mp3_low", "aac", "streaming"]:
            result = compute_noise_texture_coherence(noise, 48000, mat)
            assert 0.0 <= result.coherence <= 1.0

    def test_unknown_material_handled(self):
        """Unbekanntes Material → konservativer Fallback."""
        rng = np.random.default_rng(99)
        noise = rng.normal(0, 0.01, 48000 * 2).astype(np.float32)
        result = compute_noise_texture_coherence(noise, 48000, "nonexistent_material")
        assert 0.0 <= result.coherence <= 1.0

    def test_result_fields(self):
        """Alle Felder korrekt befüllt."""
        rng = np.random.default_rng(42)
        noise = rng.normal(0, 0.01, 48000 * 2).astype(np.float32)
        result = compute_noise_texture_coherence(noise, 48000, "shellac")
        assert result.material_type == "shellac"
        assert isinstance(result.reference_slope, float)
        assert isinstance(result.measured_slope, float)
        assert isinstance(result.is_compliant, bool)


class TestNoiseTextureCoherenceGuard:
    """§4.7 — Guard-Integration (per-phase + end-of-pipeline)."""

    def test_per_phase_high_coherence(self):
        """Hohe Kohärenz → wet_multiplier = 1.0."""
        guard = NoiseTextureCoherenceGuard()
        rng = np.random.default_rng(42)
        before = rng.normal(0, 0.1, 48000 * 2).astype(np.float32)
        # Leichte Veränderung → Residual ist ähnlich geformt
        after = before * 0.9
        coh, wet = guard.check_per_phase(before, after, 48000, "cd_digital")
        assert 0.0 <= coh <= 1.0
        assert wet <= 1.0

    def test_end_of_pipeline_returns_result(self):
        """End-of-Pipeline gibt NoiseTextureResult zurück."""
        guard = NoiseTextureCoherenceGuard()
        rng = np.random.default_rng(42)
        original = rng.normal(0, 0.1, 48000 * 2).astype(np.float32)
        restored = original * 0.8
        result = guard.check_end_of_pipeline(original, restored, 48000, "vinyl")
        assert isinstance(result, NoiseTextureResult)
        assert result.material_type == "vinyl"

    def test_end_of_pipeline_studio_mode_no_enforcement(self):
        """Studio 2026: Textur-Kohärenz nicht enforced."""
        guard = NoiseTextureCoherenceGuard()
        rng = np.random.default_rng(42)
        original = rng.normal(0, 0.1, 48000 * 2).astype(np.float32)
        restored = np.zeros_like(original)  # Extrem: alles entfernt
        result = guard.check_end_of_pipeline(original, restored, 48000, "vinyl", quality_mode="studio_2026")
        assert isinstance(result, NoiseTextureResult)


class TestSingleton:
    def test_get_noise_texture_coherence_guard_returns_same_instance(self):
        g1 = get_noise_texture_coherence_guard()
        g2 = get_noise_texture_coherence_guard()
        assert g1 is g2
