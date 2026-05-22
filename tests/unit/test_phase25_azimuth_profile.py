"""Unit tests for phase_25_azimuth_correction._compute_azimuth_profile (§2.56)."""

import numpy as np

from backend.core.defect_scanner import MaterialType
from backend.core.phases.phase_25_azimuth_correction import AzimuthCorrectionPhaseV2


class TestAzimuthProfile:
    def _p(self, material="tape", qm="restoration", rest=50.0):
        return AzimuthCorrectionPhaseV2._compute_azimuth_profile(material, qm, rest)

    def test_returns_required_keys(self):
        p = self._p()
        assert "xcorr_window_samples" in p

    def test_value_in_bounds(self):
        for mat in ("tape", "reel_tape", "shellac", "cassette", "cd_digital", "unknown"):
            for qm in ("fast", "restoration", "quality", "maximum"):
                p = self._p(mat, qm)
                assert 2048 <= p["xcorr_window_samples"] <= 8192, (
                    f"xcorr={p['xcorr_window_samples']} out of [2048,8192] mat={mat} qm={qm}"
                )

    def test_value_is_power_of_two(self):
        for mat in ("tape", "shellac", "cd_digital"):
            p = self._p(mat)
            v = p["xcorr_window_samples"]
            assert v & (v - 1) == 0, f"xcorr={v} is not a power of two"

    def test_quality_increases_window(self):
        base = self._p("tape", "restoration")
        qual = self._p("tape", "quality")
        assert qual["xcorr_window_samples"] >= base["xcorr_window_samples"]

    def test_fast_decreases_window(self):
        base = self._p("tape", "restoration")
        fast = self._p("tape", "fast")
        assert fast["xcorr_window_samples"] <= base["xcorr_window_samples"]

    def test_low_rest_decreases_window(self):
        high = self._p("tape", "restoration", 80.0)
        low = self._p("tape", "restoration", 20.0)
        assert low["xcorr_window_samples"] <= high["xcorr_window_samples"]

    def test_none_quality_mode(self):
        p = self._p("tape", None)
        assert 2048 <= p["xcorr_window_samples"] <= 8192

    def test_unknown_material(self):
        p = self._p("totally_unknown_xyz")
        assert 2048 <= p["xcorr_window_samples"] <= 8192


class TestAzimuthLocalityBlend:
    def test_process_applies_defect_locality_mask(self, monkeypatch):
        phase = AzimuthCorrectionPhaseV2()
        sr = 48000
        t = np.arange(sr, dtype=np.float32) / sr
        left = 0.25 * np.sin(2 * np.pi * 440.0 * t)
        right = 0.23 * np.sin(2 * np.pi * 443.0 * t)
        stereo = np.stack([left, right], axis=1).astype(np.float32)

        def _split_multiband(audio, sample_rate):
            return [audio.copy(), audio.copy(), audio.copy()]

        def _analyze_band_azimuth(band_audio, sample_rate, band_index):
            return type("AzErr", (), {"phase_shift_samples": 8.0, "confidence": 1.0})()

        def _correct_band_azimuth_timevarying(band_audio, sample_rate, azimuth_error, band_index):
            return (band_audio * 0.15).astype(np.float32)

        def _recombine_multiband(bands):
            return np.mean(np.stack(bands, axis=0), axis=0).astype(np.float32)

        monkeypatch.setattr(phase, "_split_multiband", _split_multiband)
        monkeypatch.setattr(phase, "_analyze_band_azimuth", _analyze_band_azimuth)
        monkeypatch.setattr(phase, "_correct_band_azimuth_timevarying", _correct_band_azimuth_timevarying)
        monkeypatch.setattr(phase, "_recombine_multiband", _recombine_multiband)
        monkeypatch.setattr(phase, "_restore_hf_content", lambda c, a, s, h: c)
        monkeypatch.setattr(phase, "_measure_hf_loss", lambda l, r, s: 8.0)

        result = phase.process(
            stereo,
            sr,
            MaterialType.TAPE,
            defect_locations={"azimuth_error": [(0.20, 0.30)]},
            strength=1.0,
        )

        diff = np.mean(np.abs(result.audio - stereo), axis=1)
        in_region = float(np.mean(diff[int(0.21 * sr) : int(0.29 * sr)]))
        out_region = float(np.mean(diff[int(0.70 * sr) : int(0.85 * sr)]))
        assert in_region > out_region * 2.0
        assert float(result.metadata.get("repair_locality_coverage", 0.0)) > 0.0
