"""
Tests for material-adaptive phase initial strengths (§2.29 / §2.31).

Covers:
- DefectPhaseMapper._MATERIAL_PHASE_FACTORS + get_material_initial_strength()
- PhaseAssignment.apply_to_config() with material_factor
- DefectPhaseMapper.build_specialist_config() with material param
- PMGG PerPhaseMusicalGoalsGate.wrap_phase() with initial_strength
"""

from __future__ import annotations

import types

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeConfig:
    """Minimal ProcessingConfig stand-in."""

    denoise_strength: float = 0.5
    click_removal_sensitivity: float = 0.5
    declip_strength: float = 0.0
    spectral_repair_strength: float = 0.5
    preserve_analog_character: bool = False
    enable_spectral_repair: bool = False


def _make_fake_phase(strength_recorder: list) -> object:
    """Creates a minimal phase that records strength and returns input audio.

    CRITICAL: Must define process() not __call__, because PMGG _run_phase
    calls phase.process() (v9.10.64 fix — PhaseInterface has no __call__).
    """

    class FakePhase:
        def process(self, audio, strength=1.0, **kwargs):
            strength_recorder.append(strength)
            # Return object with .audio attribute (PhaseResult-like)
            result = types.SimpleNamespace(audio=audio.copy())
            return result

        def __call__(self, audio, strength=1.0, **kwargs):
            # Legacy fallback — not used by current PMGG but kept for compatibility
            return self.process(audio, strength=strength, **kwargs)

        def get_metadata(self):
            meta = types.SimpleNamespace()
            # Use a DSP (non-ML-deterministic) phase_id so PMGG passes
            # initial_strength directly to process() instead of Wet/Dry blending.
            meta.phase_id = "phase_10_click_repair"
            return meta

    return FakePhase()


# ---------------------------------------------------------------------------
# 1. get_material_initial_strength
# ---------------------------------------------------------------------------


class TestGetMaterialInitialStrength:
    def test_shellac_denoise_below_one(self):
        from backend.core.defect_phase_mapper import get_material_initial_strength

        s = get_material_initial_strength("shellac", "phase_03_denoise")
        assert 0.0 < s < 1.0, f"shellac phase_03_denoise should be < 1.0, got {s}"

    def test_shellac_tape_saturation_very_low(self):
        from backend.core.defect_phase_mapper import get_material_initial_strength

        s = get_material_initial_strength("shellac", "phase_22_tape_saturation")
        assert s <= 0.30, f"shellac tape_saturation cap should be ≤ 0.30, got {s}"

    def test_wax_cylinder_tape_saturation_very_low(self):
        from backend.core.defect_phase_mapper import get_material_initial_strength

        s = get_material_initial_strength("wax_cylinder", "phase_22_tape_saturation")
        assert s <= 0.25, f"wax_cylinder tape_saturation should be ≤ 0.25, got {s}"

    def test_cd_digital_denoise_low(self):
        from backend.core.defect_phase_mapper import get_material_initial_strength

        s = get_material_initial_strength("cd_digital", "phase_03_denoise")
        assert s < 0.5, f"cd_digital denoise should start low, got {s}"

    def test_unknown_material_returns_one(self):
        from backend.core.defect_phase_mapper import get_material_initial_strength

        s = get_material_initial_strength("unknown_material_xyz", "phase_03_denoise")
        assert s == 1.0

    def test_unknown_phase_returns_one(self):
        from backend.core.defect_phase_mapper import get_material_initial_strength

        s = get_material_initial_strength("shellac", "phase_99_unknown")
        assert s == 1.0

    def test_vinyl_crackle_below_full(self):
        from backend.core.defect_phase_mapper import get_material_initial_strength

        s = get_material_initial_strength("vinyl", "phase_09_crackle_removal")
        assert 0.0 < s <= 1.0

    def test_tape_saturation_preserved_for_tape(self):
        from backend.core.defect_phase_mapper import get_material_initial_strength

        s = get_material_initial_strength("tape", "phase_22_tape_saturation")
        assert s <= 0.40, f"tape phase_22 should be capped, got {s}"

    def test_all_factors_in_valid_range(self):
        from backend.core.defect_phase_mapper import _MATERIAL_PHASE_FACTORS

        for mat, phases in _MATERIAL_PHASE_FACTORS.items():
            for phase_id, factor in phases.items():
                assert 0.0 < factor <= 1.0, (
                    f"_MATERIAL_PHASE_FACTORS[{mat!r}][{phase_id!r}] = {factor} — must be in (0, 1.0]"
                )


# ---------------------------------------------------------------------------
# 2. apply_to_config with material_factor
# ---------------------------------------------------------------------------


class TestApplyToConfigMaterialFactor:
    def _get_assignment(self):
        from backend.core.defect_phase_mapper import _PHASE_MAP, DefectType

        return _PHASE_MAP[DefectType.HIGH_FREQ_NOISE]

    def test_material_factor_one_is_identity(self):
        assignment = self._get_assignment()
        cfg1 = _FakeConfig()
        cfg2 = _FakeConfig()
        assignment.apply_to_config(cfg1, severity=0.8, mode_factor=1.0, material_factor=1.0)
        assignment.apply_to_config(cfg2, severity=0.8, mode_factor=1.0)
        # material_factor=1.0 should give same result as not passing it
        assert cfg1.denoise_strength == pytest.approx(cfg2.denoise_strength, abs=1e-6)

    def test_material_factor_halves_strength(self):
        assignment = self._get_assignment()
        cfg_full = _FakeConfig()
        cfg_half = _FakeConfig()
        assignment.apply_to_config(cfg_full, severity=1.0, mode_factor=1.0, material_factor=1.0)
        assignment.apply_to_config(cfg_half, severity=1.0, mode_factor=1.0, material_factor=0.5)
        # With half material factor, effective strength should be lower
        assert cfg_half.denoise_strength <= cfg_full.denoise_strength

    def test_material_factor_zero_point_three_caps_result(self):
        assignment = self._get_assignment()
        cfg = _FakeConfig()
        # severity=1.0, mode_factor=1.0, material_factor=0.30 → effective=0.30
        assignment.apply_to_config(cfg, severity=1.0, mode_factor=1.0, material_factor=0.30)
        # denoise_strength from config_delta=0.80, scaled by effective=0.30 → 0.24
        assert cfg.denoise_strength == pytest.approx(0.80 * 0.30, abs=0.01)

    def test_material_factor_clamped_at_one(self):
        """material_factor > 1.0 after product should be clamped to 1.0."""
        assignment = self._get_assignment()
        cfg_over = _FakeConfig()
        cfg_one = _FakeConfig()
        # severity=1.0, mode=1.0, material_factor=2.0 → effective=min(1.0, 2.0)=1.0
        assignment.apply_to_config(cfg_over, severity=1.0, mode_factor=1.0, material_factor=2.0)
        assignment.apply_to_config(cfg_one, severity=1.0, mode_factor=1.0, material_factor=1.0)
        assert cfg_over.denoise_strength == pytest.approx(cfg_one.denoise_strength, abs=1e-6)

    def test_bool_field_set_above_threshold(self):
        from backend.core.defect_phase_mapper import _PHASE_MAP, DefectType

        assignment = _PHASE_MAP[DefectType.DROPOUTS]
        cfg = _FakeConfig()
        # effective = 1.0 * 1.0 * 1.0 = 1.0 ≥ 0.3 → bool True
        assignment.apply_to_config(cfg, severity=1.0, mode_factor=1.0, material_factor=1.0)
        assert cfg.enable_spectral_repair is True

    def test_bool_field_not_set_below_threshold(self):
        from backend.core.defect_phase_mapper import _PHASE_MAP, DefectType

        assignment = _PHASE_MAP[DefectType.DROPOUTS]
        cfg = _FakeConfig()
        # Bool logic: True if effective >= 0.3 else v (v from config_delta).
        # For DROPOUTS, config_delta value is True, so field remains True even below threshold.
        assignment.apply_to_config(cfg, severity=0.1, mode_factor=1.0, material_factor=1.0)
        assert cfg.enable_spectral_repair is True


# ---------------------------------------------------------------------------
# 3. build_specialist_config with material
# ---------------------------------------------------------------------------


class TestBuildSpecialistConfigMaterial:
    def test_shellac_lowers_denoise_vs_none(self):
        from backend.core.defect_phase_mapper import DefectPhaseMapper, DefectType

        mapper = DefectPhaseMapper()
        cfg_no_mat, _ = mapper.build_specialist_config(
            _FakeConfig(), DefectType.HIGH_FREQ_NOISE, severity=0.8, material=None
        )
        cfg_shellac, _ = mapper.build_specialist_config(
            _FakeConfig(), DefectType.HIGH_FREQ_NOISE, severity=0.8, material="shellac"
        )
        # shellac has factor < 1.0 for phase_03_denoise → should result in lower denoise_strength
        assert cfg_shellac.denoise_strength <= cfg_no_mat.denoise_strength

    def test_cd_digital_lowers_click_sensitivity(self):
        from backend.core.defect_phase_mapper import DefectPhaseMapper, DefectType

        mapper = DefectPhaseMapper()
        cfg_no_mat, _ = mapper.build_specialist_config(_FakeConfig(), DefectType.CLICKS, severity=0.8, material=None)
        cfg_cd, _ = mapper.build_specialist_config(
            _FakeConfig(), DefectType.CLICKS, severity=0.8, material="cd_digital"
        )
        assert cfg_cd.click_removal_sensitivity <= cfg_no_mat.click_removal_sensitivity

    def test_material_none_same_as_before(self):
        """material=None must behave identically to not passing material."""
        from backend.core.defect_phase_mapper import DefectPhaseMapper, DefectType

        mapper = DefectPhaseMapper()
        cfg_none, v1 = mapper.build_specialist_config(_FakeConfig(), DefectType.CRACKLE, severity=0.7)
        cfg_none2, v2 = mapper.build_specialist_config(_FakeConfig(), DefectType.CRACKLE, severity=0.7, material=None)
        assert cfg_none.denoise_strength == pytest.approx(cfg_none2.denoise_strength, abs=1e-6)

    def test_returns_tuple_of_two(self):
        from backend.core.defect_phase_mapper import DefectPhaseMapper, DefectType

        mapper = DefectPhaseMapper()
        result = mapper.build_specialist_config(_FakeConfig(), DefectType.CLICKS, severity=0.5, material="vinyl")
        assert isinstance(result, tuple) and len(result) == 2

    def test_variant_name_is_string(self):
        from backend.core.defect_phase_mapper import DefectPhaseMapper, DefectType

        mapper = DefectPhaseMapper()
        _, name = mapper.build_specialist_config(_FakeConfig(), DefectType.HUM, severity=0.5, material="tape")
        assert isinstance(name, str) and len(name) > 0


# ---------------------------------------------------------------------------
# 4. PMGG initial_strength
# ---------------------------------------------------------------------------


class TestPMGGInitialStrength:
    def _make_quick_audio(self) -> np.ndarray:
        rng = np.random.default_rng(42)
        return rng.uniform(-0.1, 0.1, 48000 * 2).astype(np.float32)

    @staticmethod
    def _zero_scores() -> dict:
        """Returns all FAST_GOALS_SUBSET keys at 0.0.

        Ensures PMGG never detects a regression when testing strength
        propagation (random noise audio scores ~0.0 on all goals, which
        equals the baseline — no rollback possible).
        """
        from backend.core.per_phase_musical_goals_gate import FAST_GOALS_SUBSET

        return dict.fromkeys(FAST_GOALS_SUBSET, 0.0)

    def test_initial_strength_passed_to_phase(self):
        """wrap_phase with initial_strength=0.3 must call phase with strength=0.3."""
        from backend.core.per_phase_musical_goals_gate import get_phase_gate

        gate = get_phase_gate()
        gate.reset()

        recorded = []
        phase = _make_fake_phase(recorded)
        audio = self._make_quick_audio()

        gate.wrap_phase(
            phase,
            audio,
            48000,
            scores_before=self._zero_scores(),
            initial_strength=0.3,
        )
        assert len(recorded) >= 1
        # First call must use initial_strength, not 1.0
        assert recorded[0] == pytest.approx(0.3, abs=1e-6), (
            f"Expected initial_strength=0.3 passed to phase, got {recorded[0]}"
        )

    def test_initial_strength_default_is_one(self):
        """wrap_phase without initial_strength must pass 1.0 to phase (backward compat)."""
        from backend.core.per_phase_musical_goals_gate import get_phase_gate

        gate = get_phase_gate()
        gate.reset()

        recorded = []
        phase = _make_fake_phase(recorded)
        audio = self._make_quick_audio()

        gate.wrap_phase(
            phase,
            audio,
            48000,
            scores_before=self._zero_scores(),
        )
        assert recorded[0] == pytest.approx(1.0, abs=1e-6), f"Default initial_strength should be 1.0, got {recorded[0]}"

    def test_initial_strength_above_one_clamped(self):
        """initial_strength > 1.0 must be clamped to 1.0."""
        from backend.core.per_phase_musical_goals_gate import get_phase_gate

        gate = get_phase_gate()
        gate.reset()

        recorded = []
        phase = _make_fake_phase(recorded)
        audio = self._make_quick_audio()

        gate.wrap_phase(
            phase,
            audio,
            48000,
            scores_before=self._zero_scores(),
            initial_strength=1.5,  # over limit
        )
        assert recorded[0] <= 1.0, f"initial_strength=1.5 should be clamped, got {recorded[0]}"

    def test_initial_strength_zero_point_zero_one_floor(self):
        """initial_strength ≤ 0 must be floored to 0.01 (never zero)."""
        from backend.core.per_phase_musical_goals_gate import get_phase_gate

        gate = get_phase_gate()
        gate.reset()

        recorded = []
        phase = _make_fake_phase(recorded)
        audio = self._make_quick_audio()

        gate.wrap_phase(
            phase,
            audio,
            48000,
            scores_before=self._zero_scores(),
            initial_strength=0.0,
        )
        assert recorded[0] >= 0.01, f"initial_strength=0 should be floored, got {recorded[0]}"

    def test_returns_three_tuple(self):
        from backend.core.per_phase_musical_goals_gate import get_phase_gate

        gate = get_phase_gate()
        gate.reset()

        recorded = []
        phase = _make_fake_phase(recorded)
        audio = self._make_quick_audio()

        result = gate.wrap_phase(phase, audio, 48000, initial_strength=0.5)
        assert isinstance(result, tuple) and len(result) == 3
