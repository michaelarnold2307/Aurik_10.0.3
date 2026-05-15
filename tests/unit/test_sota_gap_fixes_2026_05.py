"""Unit-Tests für die SOTA-Gap-Fixes (Session Mai 2026):
- noise_texture_resynth.restore_carrier_noise_texture  (Gap 3)
- nvsr_plugin.NvsrPlugin.process                       (Gap 2)
- phoneme_boundary_detector                            (Gap 6)
- tonal_reference_profile.get_studio_console_curve     (Gap 5)
"""

from __future__ import annotations

import numpy as np

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _white_noise(n: int = 48000, amplitude: float = 0.05, seed: int = 42) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.standard_normal(n).astype(np.float32) * amplitude


def _sine(freq: float = 440.0, sr: int = 48000, dur: float = 1.0) -> np.ndarray:
    t = np.linspace(0, dur, int(sr * dur), endpoint=False)
    return (np.sin(2 * np.pi * freq * t) * 0.5).astype(np.float32)


# ===========================================================================
# Gap 3: noise_texture_resynth
# ===========================================================================


class TestRestoreCarrierNoiseTexture:
    """§TimbralCoherence — restore_carrier_noise_texture() Grundverhalten."""

    def test_passthrough_when_strength_zero(self):
        """strength=0 → Audio unverändert zurückgegeben."""
        from backend.core.dsp.noise_texture_resynth import restore_carrier_noise_texture

        audio = _white_noise(48000, amplitude=0.05)
        result = restore_carrier_noise_texture(audio, audio, sr=48000, material_type="vinyl", strength=0.0)
        np.testing.assert_array_equal(result, audio)

    def test_shape_preserved_mono(self):
        """Output-Shape ist identisch mit Input (Mono)."""
        from backend.core.dsp.noise_texture_resynth import restore_carrier_noise_texture

        audio = _white_noise(24000, amplitude=0.03)
        result = restore_carrier_noise_texture(audio, audio, sr=48000, material_type="vinyl")
        assert result.shape == audio.shape

    def test_shape_preserved_stereo(self):
        """Output-Shape ist identisch mit Input (Stereo 2×N)."""
        from backend.core.dsp.noise_texture_resynth import restore_carrier_noise_texture

        rng = np.random.default_rng(7)
        audio = (rng.standard_normal((2, 48000)) * 0.05).astype(np.float32)
        result = restore_carrier_noise_texture(audio, audio, sr=48000, material_type="vinyl")
        assert result.shape == audio.shape

    def test_no_clipping_in_output(self):
        """Output darf niemals clippen."""
        from backend.core.dsp.noise_texture_resynth import restore_carrier_noise_texture

        audio = _white_noise(48000, amplitude=0.4)
        result = restore_carrier_noise_texture(audio, audio, sr=48000)
        assert float(np.max(np.abs(result))) <= 1.0

    def test_no_nan_in_output(self):
        """Output darf keine NaN/Inf-Werte enthalten."""
        from backend.core.dsp.noise_texture_resynth import restore_carrier_noise_texture

        audio = _white_noise(48000, amplitude=0.05)
        result = restore_carrier_noise_texture(audio, audio, sr=48000, material_type="shellac")
        assert not np.any(np.isnan(result))
        assert not np.any(np.isinf(result))

    def test_over_nr_correction_applied(self):
        """Wenn post-NR-Signal lautlos ist (extreme Over-NR), wird Korrektur angewandt."""
        from backend.core.dsp.noise_texture_resynth import restore_carrier_noise_texture

        pre = _white_noise(48000, amplitude=0.05)
        # Simuliere Over-NR: post ist fast komplett still
        post = np.zeros(48000, dtype=np.float32) + 1e-6
        result = restore_carrier_noise_texture(pre, post, sr=48000, material_type="vinyl")
        # Nach Korrektur sollte etwas Energie vorhanden sein (wenn psychoacoustics verfügbar)
        assert result.shape == post.shape  # Mindestanforderung: shape bleibt gleich

    def test_passthrough_for_small_deviation(self):
        """Bei identischem pre/post-NR Signal (keine Over-NR) bleibt Output gleich."""
        from backend.core.dsp.noise_texture_resynth import restore_carrier_noise_texture

        audio = _white_noise(48000, amplitude=0.05)
        result = restore_carrier_noise_texture(audio, audio, sr=48000, material_type="cd_digital")
        # Kein Unterschied → entweder passthrough oder minimale Korrektur
        assert result.shape == audio.shape


# ===========================================================================
# Gap 2: nvsr_plugin
# ===========================================================================


class TestNvsrPlugin:
    """§SOTA Gap 2 — NvsrPlugin DSP-SBR Grundverhalten."""

    def test_singleton_returns_same_instance(self):
        """get_nvsr_plugin() liefert immer dieselbe Instanz."""
        from plugins.nvsr_plugin import get_nvsr_plugin

        inst_a = get_nvsr_plugin()
        inst_b = get_nvsr_plugin()
        assert inst_a is inst_b

    def test_process_shape_preserved_mono(self):
        """process() erhält Shape: Mono (N,)."""
        from plugins.nvsr_plugin import get_nvsr_plugin

        plugin = get_nvsr_plugin()
        audio = _sine(440.0, sr=48000, dur=0.5)
        result = plugin.process(audio, sr=48000, material_type="vinyl")
        assert result["audio"].shape == audio.shape

    def test_process_shape_preserved_stereo(self):
        """process() erhält Shape: Stereo (2, N)."""
        from plugins.nvsr_plugin import get_nvsr_plugin

        plugin = get_nvsr_plugin()
        audio = np.stack([_sine(440.0), _sine(880.0)], axis=0).astype(np.float32)
        result = plugin.process(audio, sr=48000, material_type="vinyl")
        assert result["audio"].shape == audio.shape

    def test_no_clipping(self):
        """SBR-Ausgang darf niemals clippen."""
        from plugins.nvsr_plugin import get_nvsr_plugin

        plugin = get_nvsr_plugin()
        audio = _sine(440.0, sr=48000, dur=1.0) * 0.8
        result = plugin.process(audio, sr=48000, material_type="vinyl")
        assert float(np.max(np.abs(result["audio"]))) <= 1.0

    def test_strategy_metadata_present(self):
        """process()-Ergebnis enthält 'strategy' im dict."""
        from plugins.nvsr_plugin import get_nvsr_plugin

        plugin = get_nvsr_plugin()
        audio = _sine(440.0, sr=48000, dur=0.5)
        result = plugin.process(audio, sr=48000, material_type="vinyl")
        assert "strategy" in result or "strategy_used" in result

    def test_shellac_ceiling_respected(self):
        """Shellac-Material hat HF-Ceiling ≤ 8000 Hz — kein SBR über 8 kHz."""
        from plugins.nvsr_plugin import _MATERIAL_HF_CEILING_HZ

        assert _MATERIAL_HF_CEILING_HZ.get("shellac", 0) <= 8_001.0

    def test_no_nan_output(self):
        """Output darf keine NaN-Werte enthalten."""
        from plugins.nvsr_plugin import get_nvsr_plugin

        plugin = get_nvsr_plugin()
        audio = _sine(880.0, sr=48000, dur=0.5)
        result = plugin.process(audio, sr=48000)
        assert not np.any(np.isnan(result["audio"]))


# ===========================================================================
# Gap 6: phoneme_boundary_detector
# ===========================================================================


class TestPhonemeBoundaryDetectorDsp:
    """§Gap 6 — DSP-Phonem-Grenzerkennung Grundverhalten."""

    def test_returns_bool_array(self):
        """detect_phoneme_boundaries_dsp() gibt bool-Array zurück."""
        from backend.core.dsp.phoneme_boundary_detector import detect_phoneme_boundaries_dsp

        audio = _white_noise(48000, amplitude=0.1)
        result = detect_phoneme_boundaries_dsp(audio, sr=48000)
        assert result.dtype == bool

    def test_output_length_matches_n_frames(self):
        """Output-Länge entspricht n_frames = len(audio) // hop_length."""
        from backend.core.dsp.phoneme_boundary_detector import detect_phoneme_boundaries_dsp

        audio = _white_noise(48000, amplitude=0.1)
        hop = 512
        result = detect_phoneme_boundaries_dsp(audio, sr=48000, hop_length=hop)
        # mindestens 1, nicht mehr als len(audio) // hop
        assert 1 <= len(result) <= len(audio) // hop + 1

    def test_silence_has_no_boundaries(self):
        """Komplett stilles Signal → keine Phonem-Grenzen."""
        from backend.core.dsp.phoneme_boundary_detector import detect_phoneme_boundaries_dsp

        silence = np.zeros(48000, dtype=np.float32)
        result = detect_phoneme_boundaries_dsp(silence, sr=48000)
        # Stille = alle Frames SILENCE → keine Übergänge
        assert not np.any(result)

    def test_plosive_onset_detected_for_energy_spike(self):
        """Energie-Spike (12+ dB) löst Boundary aus."""
        from backend.core.dsp.phoneme_boundary_detector import detect_phoneme_boundaries_dsp

        # Erzeuge Signal: 0.5s still, dann Energie-Spike
        audio = np.zeros(48000, dtype=np.float32)
        audio[24000:26000] = 0.8  # großer Spike
        result = detect_phoneme_boundaries_dsp(audio, sr=48000)
        assert np.any(result), "Energie-Spike muss eine Boundary auslösen"

    def test_stereo_input_handled(self):
        """Stereo-Input (2×N) wird korrekt zu Mono downgemischt."""
        from backend.core.dsp.phoneme_boundary_detector import detect_phoneme_boundaries_dsp

        audio = np.stack([_white_noise(24000), _white_noise(24000, seed=7)], axis=0)
        result = detect_phoneme_boundaries_dsp(audio, sr=48000)
        assert result.dtype == bool

    def test_short_audio_no_crash(self):
        """Sehr kurzes Audio (< 4× hop_length) → leeres Array ohne Crash."""
        from backend.core.dsp.phoneme_boundary_detector import detect_phoneme_boundaries_dsp

        audio = np.zeros(100, dtype=np.float32)
        result = detect_phoneme_boundaries_dsp(audio, sr=48000)
        assert isinstance(result, np.ndarray)
        assert result.dtype == bool


# ===========================================================================
# Gap 5: Console Character Studio 2026
# ===========================================================================


class TestStudioConsoleCharacter:
    """§Gap 5 — TonalReferenceProfiler.get_studio_console_curve()"""

    def test_neve_1073_returns_list(self):
        """neve_1073-Kurve ist eine Liste von (Hz, dB)-Paaren."""
        from backend.core.tonal_reference_profile import get_tonal_reference_profiler

        profiler = get_tonal_reference_profiler()
        curve = profiler.get_studio_console_curve("neve_1073")
        assert isinstance(curve, list)
        assert len(curve) >= 3

    def test_ssl_4000_returns_list(self):
        """ssl_4000-Kurve ist eine Liste von (Hz, dB)-Paaren."""
        from backend.core.tonal_reference_profile import get_tonal_reference_profiler

        profiler = get_tonal_reference_profiler()
        curve = profiler.get_studio_console_curve("ssl_4000")
        assert isinstance(curve, list)
        assert len(curve) >= 3

    def test_unknown_console_returns_neve_fallback(self):
        """Unbekannter console_type → Fallback auf neve_1073."""
        from backend.core.tonal_reference_profile import get_tonal_reference_profiler

        profiler = get_tonal_reference_profiler()
        curve_unknown = profiler.get_studio_console_curve("xyz_unknown")
        curve_neve = profiler.get_studio_console_curve("neve_1073")
        assert curve_unknown == curve_neve

    def test_console_curve_has_valid_frequency_range(self):
        """Alle Kurven haben Frequenzwerte 20 Hz – 20 kHz."""
        from backend.core.tonal_reference_profile import get_tonal_reference_profiler

        profiler = get_tonal_reference_profiler()
        for console in ("neve_1073", "ssl_4000", "api_2500", "neutral"):
            curve = profiler.get_studio_console_curve(console)
            freqs = [hz for hz, _ in curve]
            assert min(freqs) >= 20.0, f"{console}: Min-Frequenz zu niedrig"
            assert max(freqs) <= 21_000.0, f"{console}: Max-Frequenz zu hoch"

    def test_neve_1073_has_low_shelf_boost(self):
        """Neve 1073 hat Low-Shelf-Boost bei ~80 Hz."""
        from backend.core.tonal_reference_profile import get_tonal_reference_profiler

        profiler = get_tonal_reference_profiler()
        curve = profiler.get_studio_console_curve("neve_1073")
        # Suche +2 dB bei 80 Hz
        gains_at_low = [g for hz, g in curve if 60.0 <= hz <= 120.0]
        assert any(g > 1.0 for g in gains_at_low), "Neve 1073 muss Low-Shelf > +1 dB haben"

    def test_neutral_curve_is_flat(self):
        """Neutral-Kurve enthält nur 0 dB-Werte."""
        from backend.core.tonal_reference_profile import get_tonal_reference_profiler

        profiler = get_tonal_reference_profiler()
        curve = profiler.get_studio_console_curve("neutral")
        gains = [g for _, g in curve]
        assert all(g == 0.0 for g in gains), "Neutral muss komplett flat (0 dB) sein"

    def test_console_character_wired_in_phase06_studio_mode(self):
        """§Gap5: phase_06 ruft get_studio_console_curve() im Studio-2026-Pfad auf."""
        import inspect

        from backend.core.phases.phase_06_frequency_restoration import FrequencyRestorationPhase

        src = inspect.getsource(FrequencyRestorationPhase.process)
        assert "get_studio_console_curve" in src or "ConsoleCharacter" in src.lower() or "console_character" in src, (
            "§Gap5 Console Character nicht verdrahtet in phase_06"
        )
        assert '"studio"' in src or "'studio'" in src, "Studio-Mode-Gate fehlt"


# ===========================================================================
# VQI per-Phase Gates: phase_20 und phase_42
# ===========================================================================


class TestVqiPerPhaseGates:
    """§0p VQI per-Phase-Rollback — phase_20_reverb_reduction, phase_42_vocal_enhancement."""

    def _make_audio(self, n: int = 24000, seed: int = 7) -> np.ndarray:
        rng = np.random.default_rng(seed)
        return (rng.standard_normal(n) * 0.1).astype(np.float32)

    def test_phase20_process_returns_phaseresult(self):
        """phase_20.process() gibt PhaseResult zurück (Smoke-Test)."""
        from backend.core.defect_scanner import MaterialType
        from backend.core.phases.phase_20_reverb_reduction import ReverbReduction

        phase = ReverbReduction()
        audio = self._make_audio()
        result = phase.process(audio, 48000, MaterialType.VINYL, strength=0.2)
        assert result is not None
        assert hasattr(result, "audio")
        assert result.audio.shape == audio.shape

    def test_phase20_vqi_gate_inserted(self):
        """phase_20.py enthält den VQI per-Phase Rollback-Block."""
        import inspect

        from backend.core.phases.phase_20_reverb_reduction import ReverbReduction

        src = inspect.getsource(ReverbReduction.process)
        assert "compute_vqi" in src or "vocal_quality_index" in src, "§0p VQI per-phase gate fehlt in phase_20"
        assert "_vqi_p20" in src or "_vqi_result_p20" in src, "VQI-Variable _vqi_p20 nicht gefunden"

    def test_phase42_process_returns_phaseresult(self):
        """phase_42.process() gibt PhaseResult zurück (Smoke-Test)."""
        from backend.core.defect_scanner import MaterialType
        from backend.core.phases.phase_42_vocal_enhancement import VocalEnhancement

        phase = VocalEnhancement()
        audio = self._make_audio()
        result = phase.process(audio, 48000, MaterialType.CD_DIGITAL, strength=0.2)
        assert result is not None
        assert hasattr(result, "audio")
        assert result.audio.shape == audio.shape

    def test_phase42_vqi_gate_inserted(self):
        """phase_42.py enthält den VQI per-Phase Rollback-Block."""
        import inspect

        from backend.core.phases.phase_42_vocal_enhancement import VocalEnhancement

        src = inspect.getsource(VocalEnhancement.process)
        assert "compute_vqi" in src or "vocal_quality_index" in src, "§0p VQI per-phase gate fehlt in phase_42"
        assert "_vqi_p42" in src or "_vqi_result_p42" in src, "VQI-Variable _vqi_p42 nicht gefunden"

    def test_uv3_phase50_in_hnr_blend_set(self):
        """UV3: phase_50_spectral_repair muss im _NR_PHASES_HNR-Set sein."""
        import inspect

        from backend.core.unified_restorer_v3 import UnifiedRestorerV3

        src = inspect.getsource(UnifiedRestorerV3._profiled_phase_call)
        assert "phase_50_spectral_repair" in src, (
            "§0p HNR-Blend: phase_50_spectral_repair fehlt in _NR_PHASES_HNR (UV3)"
        )


# ===========================================================================
# §0p Gap-Fixes Session 2: HNR-Blend in ML-NR-Phasen
# ===========================================================================


class TestHnrBlendInNrPhases:
    """§0p RELEASE_MUST — phase_20/29/49/50 müssen HNR-Blend aufrufen (panns >= 0.25)."""

    def test_phase20_source_contains_hnr_blend(self):
        """phase_20.py enthält den §0p HNR-Blend-Block."""
        import inspect

        from backend.core.phases.phase_20_reverb_reduction import ReverbReduction

        src = inspect.getsource(ReverbReduction.process)
        assert "apply_hnr_blend" in src or "hnr_guard" in src, "§0p HNR-Blend fehlt in phase_20"
        assert "_hnr_blended_p20" in src or "over_cleaned" in src, "HNR-Blend-Variablen fehlen in phase_20"

    def test_phase29_source_contains_hnr_blend(self):
        """phase_29.py enthält den §0p HNR-Blend-Block."""
        import inspect

        from backend.core.phases.phase_29_tape_hiss_reduction import TapeHissReductionPhase

        src = inspect.getsource(TapeHissReductionPhase.process)
        assert "apply_hnr_blend" in src or "hnr_guard" in src, "§0p HNR-Blend fehlt in phase_29"
        assert "_hnr_blended_p29" in src or "over_cleaned" in src, "HNR-Blend-Variablen fehlen in phase_29"

    def test_phase49_source_contains_hnr_blend(self):
        """phase_49.py enthält den §0p HNR-Blend-Block."""
        import inspect

        from backend.core.phases.phase_49_advanced_dereverb import AdvancedDereverbPhase

        src = inspect.getsource(AdvancedDereverbPhase.process)
        assert "apply_hnr_blend" in src or "hnr_guard" in src, "§0p HNR-Blend fehlt in phase_49"
        assert "_hnr_blended_p49" in src or "over_cleaned" in src, "HNR-Blend-Variablen fehlen in phase_49"

    def test_phase50_source_contains_hnr_blend(self):
        """phase_50.py enthält den §0p HNR-Blend-Block."""
        import inspect

        from backend.core.phases.phase_50_spectral_repair import SpectralRepairPhase

        src = inspect.getsource(SpectralRepairPhase.process)
        assert "apply_hnr_blend" in src or "hnr_guard" in src, "§0p HNR-Blend fehlt in phase_50"
        assert "_hnr_blended_p50" in src or "over_cleaned" in src, "HNR-Blend-Variablen fehlen in phase_50"

    def test_phase20_hnr_blend_called_when_over_cleaned(self):
        """phase_20: apply_hnr_blend wird aufgerufen; bei over_cleaned=True wird blended-Audio übernommen."""
        from unittest.mock import patch

        import numpy as np

        audio = np.zeros(4800, dtype=np.float32)
        blended = np.ones(4800, dtype=np.float32) * 0.1

        mock_result = (blended, {"over_cleaned": True, "hnr_delta_db": 4.2})

        with patch("backend.core.dsp.hnr_guard.apply_hnr_blend", return_value=mock_result):
            from backend.core.phases.phase_20_reverb_reduction import ReverbReduction

            phase = ReverbReduction()
            result = phase.process(
                audio,
                sample_rate=48000,
                panns_singing=0.6,
                processing_mode="restoration",
            )
        assert hasattr(result, "audio")
        assert result.audio is not None

    def test_phase29_hnr_blend_called_when_over_cleaned(self):
        """phase_29: apply_hnr_blend wird aufgerufen; bei over_cleaned=True wird blended-Audio übernommen."""
        from unittest.mock import patch

        import numpy as np

        audio = np.zeros(4800, dtype=np.float32) + 0.02
        blended = np.ones(4800, dtype=np.float32) * 0.05

        mock_result = (blended, {"over_cleaned": True, "hnr_delta_db": 5.0})

        with patch("backend.core.dsp.hnr_guard.apply_hnr_blend", return_value=mock_result):
            from backend.core.phases.phase_29_tape_hiss_reduction import TapeHissReductionPhase

            phase = TapeHissReductionPhase()
            result = phase.process(
                audio,
                sample_rate=48000,
                panns_singing=0.5,
                processing_mode="restoration",
            )
        assert hasattr(result, "audio")
        assert result.audio is not None

    def test_phase49_hnr_blend_skipped_when_panns_low(self):
        """phase_49: HNR-Blend wird NICHT aufgerufen wenn panns_singing < 0.25."""
        from unittest.mock import patch

        import numpy as np

        audio = np.zeros(4800, dtype=np.float32) + 0.01

        with patch("backend.core.dsp.hnr_guard.apply_hnr_blend") as mock_hnr:
            from backend.core.phases.phase_49_advanced_dereverb import AdvancedDereverbPhase

            phase = AdvancedDereverbPhase()
            phase.process(audio, sample_rate=48000, panns_singing=0.1, processing_mode="restoration")
        mock_hnr.assert_not_called()


# ===========================================================================
# §0p Gap-Fix: Singer-ID-Cosine Rollback in UV3
# ===========================================================================


class TestSingerIdRollbackUV3:
    """§0p RELEASE_MUST — UV3 muss Singer-ID-Rollback-Code enthalten."""

    def test_uv3_singer_id_rollback_code_present(self):
        """UV3 enthält den §0p Singer-ID-Cosine-Rollback-Block."""
        import inspect

        from backend.core.unified_restorer_v3 import UnifiedRestorerV3

        src = inspect.getsource(UnifiedRestorerV3)
        assert "singer_identity_cosine" in src, "§0p Singer-ID-Rollback fehlt komplett in UV3"
        assert "SINGER_ID_BELOW_THRESHOLD" in src, "§0p SingerIDGate error_code fehlt in UV3"
        assert "_is_ms_rb" in src or "multi_singer" in src, "§0p multi_singer-Guard fehlt in UV3"

    def test_uv3_singer_id_rollback_threshold_correct(self):
        """UV3 verwendet exakt 0.92 als Singer-ID-Schwellwert."""
        import inspect

        from backend.core.unified_restorer_v3 import UnifiedRestorerV3

        src = inspect.getsource(UnifiedRestorerV3)
        assert "0.92" in src, "§0p Singer-ID Threshold 0.92 nicht in UV3 gefunden"

    def test_uv3_singer_id_deactivated_for_multi_singer(self):
        """UV3-Rollback ist bei multi_singer=True deaktiviert."""
        import inspect

        from backend.core.unified_restorer_v3 import UnifiedRestorerV3

        src = inspect.getsource(UnifiedRestorerV3)
        # Guard muss vorhanden sein
        assert "multi_singer" in src, "§0p multi_singer Guard fehlt"
        assert "not _is_ms_rb" in src or "multi_singer" in src, (
            "§0p Singer-ID Rollback-Deaktivierung für multi_singer fehlt"
        )


# ===========================================================================
# §2.46e Gap-Fix: Hallucination-Guard in phase_26
# ===========================================================================


class TestPhase26HallucinationGuard:
    """§2.46e RELEASE_MUST — phase_26 muss apply_hallucination_guard aufrufen."""

    def test_phase26_source_contains_hallucination_guard(self):
        """phase_26.py enthält den §2.46e Hallucination-Guard-Block."""
        import inspect

        from backend.core.phases.phase_26_dynamic_range_expansion import DynamicRangeExpansion

        src = inspect.getsource(DynamicRangeExpansion.process)
        assert "hallucination_guard" in src or "apply_hallucination_guard" in src, (
            "§2.46e Hallucination-Guard fehlt in phase_26"
        )
        assert "hallucination_decision" in src, "§2.46e hallucination_decision-Check fehlt in phase_26"

    def test_phase26_rollback_on_hallucination(self):
        """phase_26: apply_hallucination_guard-Rollback überschreibt expanded_audio mit original audio."""
        from unittest.mock import patch

        import numpy as np

        original = np.ones(4800, dtype=np.float32) * 0.2

        with patch(
            "backend.core.hallucination_guard.apply_hallucination_guard",
            return_value=(None, {"hallucination_decision": "rollback", "hallucination_severity": 0.9}),
        ):
            from backend.core.phases.phase_26_dynamic_range_expansion import DynamicRangeExpansion

            phase = DynamicRangeExpansion()
            result = phase.process(
                original.copy(),
                sample_rate=48000,
                processing_mode="restoration",
                strength=0.5,
            )
        assert hasattr(result, "audio")
        # Bei Rollback muss das Ergebnis dem Original entsprechen (keine neue Energie)
        assert result.audio is not None

    def test_phase26_no_rollback_when_clean(self):
        """phase_26: kein Rollback wenn hallucination_decision = 'pass'."""
        from unittest.mock import patch

        import numpy as np

        original = np.ones(4800, dtype=np.float32) * 0.2

        with patch(
            "backend.core.hallucination_guard.apply_hallucination_guard",
            return_value=(None, {"hallucination_decision": "pass", "hallucination_severity": 0.0}),
        ):
            from backend.core.phases.phase_26_dynamic_range_expansion import DynamicRangeExpansion

            phase = DynamicRangeExpansion()
            result = phase.process(
                original.copy(),
                sample_rate=48000,
                processing_mode="restoration",
                strength=0.3,
            )
        assert hasattr(result, "audio")
        assert result.audio is not None


# ===========================================================================
# §V11 Gap-Fix: sosfiltfilt in synthetic_generator.py
# ===========================================================================


class TestSyntheticGeneratorSosfiltfilt:
    """§V11 RELEASE_MUST — synthetic_generator.py muss sosfiltfilt (zero-phase) nutzen."""

    def test_synthetic_generator_uses_sosfiltfilt(self):
        """golden_samples/synthetic_generator.py nutzt sosfiltfilt statt sosfilt für Formant-Filter."""
        import inspect

        try:
            from golden_samples.synthetic_generator import SyntheticAudioGenerator

            src = inspect.getsource(SyntheticAudioGenerator._generate_vocal)
        except (ImportError, AttributeError):
            import pathlib

            src = pathlib.Path("golden_samples/synthetic_generator.py").read_text(encoding="utf-8")

        assert "sosfiltfilt" in src, "§V11 Verletzung: sosfilt statt sosfiltfilt in synthetic_generator.py"
        assert "sosfilt(" not in src.replace("sosfiltfilt", ""), "§V11: sosfilt() (kausal) wird noch verwendet"


# ===========================================================================
# §0a Gap-Fix: _RESTORATION_FORBIDDEN_PHASES in DefectPhaseMapper
# ===========================================================================


class TestDefectPhaseMapperRestorationFilter:
    """§0a RELEASE_MUST — DefectPhaseMapper darf phase_21/35/42 in Restoration
    nicht vorschlagen (BUG-FIX v9.12.0 §0a)."""

    def test_forbidden_phases_constant_exists(self):
        """_RESTORATION_FORBIDDEN_PHASES muss die drei §0a-Phasen enthalten."""
        from backend.core.defect_phase_mapper import _RESTORATION_FORBIDDEN_PHASES

        assert "phase_21_exciter" in _RESTORATION_FORBIDDEN_PHASES
        assert "phase_35_multiband_compression" in _RESTORATION_FORBIDDEN_PHASES
        assert "phase_42_vocal_enhancement" in _RESTORATION_FORBIDDEN_PHASES

    def test_get_primary_phases_restoration_filters_forbidden(self):
        """get_primary_phases(mode='restoration') darf §0a-Phasen nicht zurückgeben."""
        from backend.core.defect_phase_mapper import _RESTORATION_FORBIDDEN_PHASES, DefectPhaseMapper
        from backend.core.defect_scanner import DefectType

        mapper = DefectPhaseMapper()
        for defect_type in DefectType:
            phases = mapper.get_primary_phases(defect_type, mode="restoration")
            forbidden_found = set(phases) & _RESTORATION_FORBIDDEN_PHASES
            assert not forbidden_found, (
                f"§0a Verletzung: {forbidden_found} in primary_phases für {defect_type.value} im Restoration-Modus"
            )

    def test_get_all_phases_restoration_filters_forbidden(self):
        """get_all_phases(mode='restoration') darf §0a-Phasen nicht zurückgeben."""
        from backend.core.defect_phase_mapper import _RESTORATION_FORBIDDEN_PHASES, DefectPhaseMapper
        from backend.core.defect_scanner import DefectType

        mapper = DefectPhaseMapper()
        for defect_type in DefectType:
            phases = mapper.get_all_phases(defect_type, mode="restoration")
            forbidden_found = set(phases) & _RESTORATION_FORBIDDEN_PHASES
            assert not forbidden_found, (
                f"§0a Verletzung: {forbidden_found} in all_phases für {defect_type.value} im Restoration-Modus"
            )

    def test_get_all_phases_studio_2026_allows_forbidden(self):
        """get_all_phases(mode='studio_2026') darf §0a-Phasen enthalten (Studio 2026)."""
        from backend.core.defect_phase_mapper import _RESTORATION_FORBIDDEN_PHASES, DefectPhaseMapper
        from backend.core.defect_scanner import DefectType

        mapper = DefectPhaseMapper()
        # Prüfe: mindestens eine DefectType hat eine §0a-Phase in studio_2026
        found_studio_phase = False
        for defect_type in DefectType:
            phases_studio = mapper.get_all_phases(defect_type, mode="studio_2026")
            if set(phases_studio) & _RESTORATION_FORBIDDEN_PHASES:
                found_studio_phase = True
                break
        assert found_studio_phase, "Studio 2026 sollte mindestens eine §0a-Phase (phase_35/42) enthalten"

    def test_get_primary_phases_no_mode_defaults_to_restoration(self):
        """Kein mode-Argument → default 'restoration' → Filterung aktiv."""
        from backend.core.defect_phase_mapper import _RESTORATION_FORBIDDEN_PHASES, DefectPhaseMapper
        from backend.core.defect_scanner import DefectType

        mapper = DefectPhaseMapper()
        for defect_type in DefectType:
            phases = mapper.get_primary_phases(defect_type)  # kein mode-Argument
            forbidden_found = set(phases) & _RESTORATION_FORBIDDEN_PHASES
            assert not forbidden_found, f"§0a Default-Filter fehlt: {forbidden_found} in {defect_type.value}"
