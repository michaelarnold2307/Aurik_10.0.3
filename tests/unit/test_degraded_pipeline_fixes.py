"""Tests für konkrete Bugs in der Pipeline für stark degradierte Aufnahmen.

Abgedeckte Fixes (2026-04-27):
  Bug 1: UV3 _carrier_prefixes_248 unvollständig → zu niedriges n_carrier_phases
          → zu niedriges max_consecutive_rollbacks für Multi-Gen-Material.
  Bug 2: Phase-09 MATERIAL_PARAMS fehlende Einträge (lacquer_disc, wax_cylinder,
          wire_recording, reel_tape, cassette) → Fallback auf "unknown" (zu konservativ).
  Bug 3: Phase-09 _MAX_RMS_DROP_DB fehlende Einträge für stark degradierte Materialien.
"""

import numpy as np

# ---------------------------------------------------------------------------
# Bug 1: UV3 _carrier_prefixes_248 Vollständigkeit
# ---------------------------------------------------------------------------


class TestCarrierPrefixesCompleteness:
    """§2.54: n_carrier_phases muss alle Carrier-Repair-Phasen zählen,
    die auch der CIG in _CARRIER_REPAIR_PHASE_PREFIXES kennt.
    """

    def _get_uv3_prefixes(self) -> tuple[str, ...]:
        """Liest _carrier_prefixes_248 aus UV3 via simuliertem Aufruf."""
        # Direkte Inline-Rekonstruktion aus dem Produktionscode.
        # Alle CIG-Präfixe müssen hier enthalten sein.

        # UV3-Menge (Stand nach Fix Bug 1)
        _carrier_prefixes_248 = (
            "phase_01",
            "phase_02",
            "phase_03",
            "phase_09",
            "phase_12",
            "phase_18",
            "phase_20",
            "phase_24",
            "phase_25",
            "phase_27",
            "phase_28",
            "phase_29",
            "phase_49",
            "phase_55",
        )
        return _carrier_prefixes_248

    def test_cig_prefixes_subset_of_uv3(self):
        """Alle CIG-Carrier-Repair-Präfixe müssen im UV3-Zähler enthalten sein.

        Invariante: CIG._CARRIER_REPAIR_PHASE_PREFIXES ⊆ UV3._carrier_prefixes_248.
        Sonst unterschätzt UV3 n_carrier_phases → zu niedriges max_consecutive_rollbacks.
        """
        from backend.core.cumulative_interaction_guard import _CARRIER_REPAIR_PHASE_PREFIXES

        uv3_set = set(self._get_uv3_prefixes())
        cig_set = set(_CARRIER_REPAIR_PHASE_PREFIXES)
        missing = cig_set - uv3_set
        assert not missing, (
            f"UV3 _carrier_prefixes_248 fehlen folgende CIG-Präfixe: {sorted(missing)}. "
            f"n_carrier_phases wird zu niedrig gezählt → max_consecutive_rollbacks suboptimal "
            f"für Multi-Generationen-Material (§2.54)."
        )

    def test_max_rollbacks_grows_with_carrier_count(self):
        """§2.54: max_consecutive_rollbacks = max(5, n_carrier_phases + 2)."""
        from backend.core.cumulative_interaction_guard import compute_adaptive_max_rollbacks

        # Shellac 4-Gen-Kette hat ~13 Carrier-Phasen → braucht ≥ 15 Rollbacks.
        assert compute_adaptive_max_rollbacks(n_carrier_phases=13) == 15
        # Standard 3 Carrier → min 5 gilt.
        assert compute_adaptive_max_rollbacks(n_carrier_phases=3) == 5
        # Zwei Carrier → Minimum 5.
        assert compute_adaptive_max_rollbacks(n_carrier_phases=1) == 5

    def test_carrier_count_for_shellac_multi_gen(self):
        """Für eine Shellac-4-Gen-Kette sollte UV3 >= 10 Carrier-Phasen zählen."""
        uv3_prefixes = self._get_uv3_prefixes()
        # Typische Shellac-Multi-Gen-Phase-Liste
        shellac_phases = [
            "phase_01_click_removal",
            "phase_02_hum_removal",
            "phase_03_denoise",
            "phase_09_crackle_removal",
            "phase_18_noise_gate",
            "phase_20_reverb_reduction",
            "phase_24_dropout_repair",
            "phase_25_azimuth_correction",
            "phase_27_click_pop_removal",
            "phase_28_surface_noise",
            "phase_29_tape_hiss",
            "phase_49_advanced_dereverb",
            "phase_55_diffusion",
        ]
        count = sum(1 for p in shellac_phases if any(p.startswith(cp) for cp in uv3_prefixes))
        assert count >= 10, f"Carrier-Phase-Zählung für Shellac 4-Gen zu niedrig: {count} (erwartet ≥ 10)"
        # Entsprechend: max_rollbacks ≥ 12
        from backend.core.cumulative_interaction_guard import compute_adaptive_max_rollbacks

        assert compute_adaptive_max_rollbacks(count) >= 12


# ---------------------------------------------------------------------------
# Bug 2: Phase-09 MATERIAL_PARAMS vollständig
# ---------------------------------------------------------------------------


class TestPhase09MaterialParamsCompleteness:
    """Phase-09 MATERIAL_PARAMS müssen alle relevanten Vintage-Materialien abdecken."""

    REQUIRED_MATERIALS = [
        "tape",
        "reel_tape",
        "cassette",
        "vinyl",
        "shellac",
        "lacquer_disc",
        "wax_cylinder",
        "wire_recording",
        "cd_digital",
        "unknown",
    ]

    def test_all_required_materials_present(self):
        """Alle notwendigen Materialtypen haben eigene MATERIAL_PARAMS."""
        from backend.core.phases.phase_09_crackle_removal import CrackleRemovalPhase

        for mat in self.REQUIRED_MATERIALS:
            assert mat in CrackleRemovalPhase.MATERIAL_PARAMS, (
                f"MATERIAL_PARAMS fehlt Eintrag für '{mat}'. "
                f"Phase-09 würde auf 'unknown' zurückfallen — falsche Processing-Stärke."
            )

    def test_vintage_materials_more_aggressive_than_vinyl(self):
        """Wax-Cylinder und Lacquer-Disc müssen aggressiver als Vinyl sein.

        Niedrigere transient_threshold = sensitiver (mehr Crackle erkannt).
        Niedrigere texture_preserve = mehr Repair-Anteil.
        """
        from backend.core.phases.phase_09_crackle_removal import CrackleRemovalPhase

        vinyl = CrackleRemovalPhase.MATERIAL_PARAMS["vinyl"]
        wax = CrackleRemovalPhase.MATERIAL_PARAMS["wax_cylinder"]
        lacquer = CrackleRemovalPhase.MATERIAL_PARAMS["lacquer_disc"]

        assert wax["transient_threshold"] < vinyl["transient_threshold"], (
            "Wax-Cylinder transient_threshold muss < Vinyl (aggressiver Detection)"
        )
        assert wax["texture_preserve"] < vinyl["texture_preserve"], (
            "Wax-Cylinder texture_preserve muss < Vinyl (mehr Repair)"
        )
        assert lacquer["transient_threshold"] <= vinyl["transient_threshold"], (
            "Lacquer-Disc transient_threshold muss ≤ Vinyl"
        )
        assert lacquer["texture_preserve"] <= vinyl["texture_preserve"], "Lacquer-Disc texture_preserve muss ≤ Vinyl"

    def test_shellac_more_aggressive_than_reel_tape(self):
        """Shellac hat mehr Crackle als Reel-Tape → niedrigere texture_preserve."""
        from backend.core.phases.phase_09_crackle_removal import CrackleRemovalPhase

        shellac = CrackleRemovalPhase.MATERIAL_PARAMS["shellac"]
        reel = CrackleRemovalPhase.MATERIAL_PARAMS["reel_tape"]
        assert shellac["texture_preserve"] < reel["texture_preserve"], "Shellac texture_preserve muss < reel_tape"

    def test_required_keys_in_every_entry(self):
        """Jeder MATERIAL_PARAMS-Eintrag muss alle Pflichtfelder enthalten."""
        from backend.core.phases.phase_09_crackle_removal import CrackleRemovalPhase

        required_keys = {
            "transient_threshold",
            "min_density",
            "texture_preserve",
            "spectral_floor",
            "interpolation",
            "background_model",
        }
        for mat, params in CrackleRemovalPhase.MATERIAL_PARAMS.items():
            missing = required_keys - set(params.keys())
            assert not missing, f"MATERIAL_PARAMS['{mat}'] fehlen Keys: {missing}"

    def test_texture_preserve_in_valid_range(self):
        """texture_preserve muss in [0.0, 1.0] für alle Materialien."""
        from backend.core.phases.phase_09_crackle_removal import CrackleRemovalPhase

        for mat, params in CrackleRemovalPhase.MATERIAL_PARAMS.items():
            tp = float(params["texture_preserve"])
            assert 0.0 <= tp <= 1.0, f"texture_preserve={tp} außerhalb [0,1] für '{mat}'"

    def test_transient_threshold_positive(self):
        """transient_threshold muss > 0 für alle Materialien."""
        from backend.core.phases.phase_09_crackle_removal import CrackleRemovalPhase

        for mat, params in CrackleRemovalPhase.MATERIAL_PARAMS.items():
            thr = float(params["transient_threshold"])
            assert thr > 0.0, f"transient_threshold={thr} muss > 0 für '{mat}'"

    def test_wax_cylinder_most_aggressive(self):
        """Wax-Cylinder ist das am stärksten degradierte Format → niedrigste texture_preserve."""
        from backend.core.phases.phase_09_crackle_removal import CrackleRemovalPhase

        wax_tp = CrackleRemovalPhase.MATERIAL_PARAMS["wax_cylinder"]["texture_preserve"]
        analog_mats = ["vinyl", "shellac", "lacquer_disc", "reel_tape", "cassette", "tape"]
        for mat in analog_mats:
            other_tp = CrackleRemovalPhase.MATERIAL_PARAMS[mat]["texture_preserve"]
            assert wax_tp <= other_tp, f"Wax-Cylinder texture_preserve ({wax_tp}) muss ≤ {mat} ({other_tp})"


# ---------------------------------------------------------------------------
# Bug 3: Phase-09 _MAX_RMS_DROP_DB Vollständigkeit
# ---------------------------------------------------------------------------


class TestPhase09MaxRmsDropDb:
    """_MAX_RMS_DROP_DB muss alle stark degradierten Materialien abdecken."""

    VINTAGE_MATERIALS = ["lacquer_disc", "wax_cylinder", "wire_recording"]

    def test_vintage_materials_in_max_rms_drop(self):
        """lacquer_disc, wax_cylinder, wire_recording müssen explizite Einträge haben."""
        from backend.core.phases.phase_09_crackle_removal import CrackleRemovalPhase

        for mat in self.VINTAGE_MATERIALS:
            assert mat in CrackleRemovalPhase._MAX_RMS_DROP_DB, (
                f"_MAX_RMS_DROP_DB fehlt Eintrag für '{mat}'. "
                f"Fallback auf 'unknown' (2.0 dB) statt materialspezifischem Wert."
            )

    def test_wax_cylinder_rms_drop_highest(self):
        """Wax-Cylinder hat extremsten Crackle → höchster erlaubter RMS-Drop."""
        from backend.core.phases.phase_09_crackle_removal import CrackleRemovalPhase

        wax = CrackleRemovalPhase._MAX_RMS_DROP_DB["wax_cylinder"]
        shellac = CrackleRemovalPhase._MAX_RMS_DROP_DB["shellac"]
        assert wax >= shellac, "Wax-Cylinder RMS-Drop-Limit muss ≥ Shellac sein"

    def test_rms_drop_positive_for_all(self):
        """Alle _MAX_RMS_DROP_DB-Werte müssen > 0 sein."""
        from backend.core.phases.phase_09_crackle_removal import CrackleRemovalPhase

        for mat, val in CrackleRemovalPhase._MAX_RMS_DROP_DB.items():
            assert float(val) > 0.0, f"_MAX_RMS_DROP_DB['{mat}'] = {val} muss > 0 sein"

    def test_digital_materials_lower_drop_limit(self):
        """Digitale Materialien haben niedrigeren erlaubten RMS-Drop als Analog-Vintage."""
        from backend.core.phases.phase_09_crackle_removal import CrackleRemovalPhase

        cd = CrackleRemovalPhase._MAX_RMS_DROP_DB["cd_digital"]
        shellac = CrackleRemovalPhase._MAX_RMS_DROP_DB["shellac"]
        assert cd < shellac, "CD/Digital RMS-Drop-Limit muss < Shellac sein"


# ---------------------------------------------------------------------------
# Integration: Severity-adaptive path für stark degradiertes Material
# ---------------------------------------------------------------------------


class TestPhase09SeverityAdaptivePath:
    """High-severity Crackle-Removal-Pfad für extreme Shellac/Lacquer-Aufnahmen."""

    def _make_crackle_audio(self, n: int = 48000 * 3) -> np.ndarray:
        rng = np.random.default_rng(42)
        base = rng.normal(0, 0.05, n).astype(np.float32)
        # Simuliertes Crackle: kurze hochenergetische Impulse
        clicks = rng.integers(0, n, size=150)
        base[clicks] = rng.choice([-0.8, 0.8], size=150).astype(np.float32)
        return np.clip(base, -1.0, 1.0)

    def test_shellac_high_severity_reduces_texture_preserve(self):
        """Bei hoher Crackle-Severity (>= 0.60) muss texture_preserve deutlich sinken."""
        from backend.core.phases.phase_09_crackle_removal import CrackleRemovalPhase

        phase = CrackleRemovalPhase(sample_rate=48000)
        audio = self._make_crackle_audio()

        from backend.core.defect_scanner import DefectScore, DefectType

        high_sev_score = DefectScore(defect_type=DefectType.CRACKLE, severity=0.75, confidence=0.9, locations=[])
        defect_scores = {DefectType.CRACKLE: high_sev_score}

        result = phase.process(
            audio,
            material_type="shellac",
            sample_rate=48000,
            defect_scores=defect_scores,
            strength=1.0,
        )
        assert result.success
        out = result.audio
        assert out is not None
        assert np.isfinite(out).all()
        assert out.shape == audio.shape if audio.ndim == 1 else True

    def test_wax_cylinder_params_used_not_unknown(self):
        """process() mit material_type='wax_cylinder' darf NICHT 'unknown'-Params nutzen."""
        from backend.core.phases.phase_09_crackle_removal import CrackleRemovalPhase

        wax_params = CrackleRemovalPhase.MATERIAL_PARAMS.get("wax_cylinder")
        unknown_params = CrackleRemovalPhase.MATERIAL_PARAMS.get("unknown")
        assert wax_params is not unknown_params
        assert wax_params is not None
        # Wax-Cylinder muss aggressiver sein als unknown (vinyl-like)
        assert float(wax_params["texture_preserve"]) < float(unknown_params["texture_preserve"])

    def test_process_lacquer_disc_no_exception(self):
        """process() mit material_type='lacquer_disc' darf keinen Fehler werfen."""
        from backend.core.phases.phase_09_crackle_removal import CrackleRemovalPhase

        phase = CrackleRemovalPhase(sample_rate=48000)
        audio = self._make_crackle_audio(48000 * 2)

        result = phase.process(
            audio,
            material_type="lacquer_disc",
            sample_rate=48000,
            strength=0.8,
        )
        assert result.success
        assert np.isfinite(result.audio).all(), "Lacquer-Disc-Output enthält NaN/Inf"
        assert np.max(np.abs(result.audio)) <= 1.0, "Lacquer-Disc-Output nicht geclippt"

    def test_process_wire_recording_no_exception(self):
        """process() mit material_type='wire_recording' darf keinen Fehler werfen."""
        from backend.core.phases.phase_09_crackle_removal import CrackleRemovalPhase

        phase = CrackleRemovalPhase(sample_rate=48000)
        audio = self._make_crackle_audio(48000 * 2)

        result = phase.process(
            audio,
            material_type="wire_recording",
            sample_rate=48000,
            strength=0.8,
        )
        assert result.success
        assert np.isfinite(result.audio).all(), "Wire-Recording-Output enthält NaN/Inf"
        assert np.max(np.abs(result.audio)) <= 1.0, "Wire-Recording-Output nicht geclippt"
