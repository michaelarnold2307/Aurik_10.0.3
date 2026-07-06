"""§AC: Intelligent Phase Pruning — nur hörbare Verbesserungen ausführen.

Nicht alle 39–64 Phasen bringen für jede Aufnahme einen hörbaren Gewinn.
Phase Pruning analysiert das Audio, die Defekte und das Material und
entscheidet pro Phase: ausführen, überspringen oder mit Minimal-Stärke.

Kriterien:
1. Defekt nicht vorhanden → Phase skip (z.B. kein Hum → phase_02 skip)
2. Defekt unterhalb psychoakustischer Hörschwelle → Phase skip
3. Material/Gerre schließt Phase aus → Phase skip
4. Phase nur bei bestimmten Defekt-Kombinationen nötig → check
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ── Phase → Defekt-Präsenz-Requirements ──────────────────────────────────────
_PHASE_DEFECT_REQUIREMENTS: dict[str, list[str]] = {
    "phase_01_click_removal": ["click", "pop"],
    "phase_02_hum_removal": ["hum", "buzz"],
    "phase_03_denoise": ["hiss", "noise", "surface_noise"],
    "phase_04_eq_correction": [],  # immer nützlich
    "phase_05_rumble_filter": ["rumble", "subsonic"],
    "phase_06_frequency_restoration": ["clipping", "bandwidth_limited"],
    "phase_07_harmonic_restoration": ["clipping", "distortion"],
    "phase_08_transient_preservation": ["click", "transient_loss"],
    "phase_09_crackle_removal": ["crackle"],
    "phase_12_wow_flutter_fix": ["wow_flutter", "speed_error"],
    "phase_13_stereo_enhancement": [],  # fast immer
    "phase_14_phase_correction": ["azimuth_error", "phase_error"],
    "phase_16_final_eq": [],  # immer
    "phase_23_spectral_repair": ["dropout", "spectral_gap"],
    "phase_24_dropout_repair": ["dropout"],
    "phase_25_azimuth_correction": ["azimuth_error"],
    "phase_29_tape_hiss_reduction": ["hiss", "tape_hiss"],
    "phase_31_speed_pitch_correction": ["speed_error", "pitch_error"],
    "phase_37_bass_enhancement": [],  # immer
    "phase_38_presence_boost": [],  # immer
    "phase_43_ml_deesser": ["sibilance", "ess"],
    "phase_49_advanced_dereverb": ["reverb_excess"],
    "phase_54_transparent_dynamics": [],  # immer
    "phase_56_spectral_band_gap_repair": ["bandwidth_limited", "spectral_gap"],
}

# ── Material-spezifische Skip-Phasen ──────────────────────────────────────────
_MATERIAL_SKIP_PHASES: dict[str, list[str]] = {
    "cd_digital": ["phase_02_hum_removal", "phase_05_rumble_filter",
                   "phase_09_crackle_removal", "phase_12_wow_flutter_fix",
                   "phase_25_azimuth_correction", "phase_29_tape_hiss_reduction"],
    "streaming": ["phase_02_hum_removal", "phase_05_rumble_filter",
                  "phase_09_crackle_removal", "phase_25_azimuth_correction"],
}


@dataclass
class PruningResult:
    """Ergebnis der Phase-Pruning-Analyse."""
    kept_phases: list[str] = field(default_factory=list)
    skipped_phases: list[str] = field(default_factory=list)
    reduced_phases: dict[str, float] = field(default_factory=dict)  # phase → reduzierte Stärke
    reasons: dict[str, str] = field(default_factory=dict)
    reduction_pct: float = 0.0


class IntelligentPhasePruner:
    """Analysiert und reduziert den Phasenplan auf hörbar notwendige Phasen."""

    def __init__(self) -> None:
        pass

    def prune(
        self,
        phases: list[str],
        defect_types: list[str] | None = None,
        material: str = "unknown",
        defect_severities: dict[str, float] | None = None,
        audio_duration_s: float = 0.0,
    ) -> PruningResult:
        """Reduziert den Phasenplan auf das Wesentliche.

        Args:
            phases: Vollständiger PID-Phasenplan
            defect_types: Detektierte Defekt-Typen (lowercase)
            material: Material-Typ
            defect_severities: Defekt-Schweregrade (0–1)
            audio_duration_s: Audio-Dauer in Sekunden
        """
        defects_lower = [d.lower() for d in (defect_types or [])]
        sevs = defect_severities or {}
        result = PruningResult()

        # Material-spezifische Skips
        material_skips = set(_MATERIAL_SKIP_PHASES.get(material, []))

        for phase_id in phases:
            # 1. Material-basierter Skip
            if phase_id in material_skips:
                result.skipped_phases.append(phase_id)
                result.reasons[phase_id] = f"Material {material} benötigt diese Phase nicht"
                continue

            # 2. Defekt-Präsenz-Check
            required = _PHASE_DEFECT_REQUIREMENTS.get(phase_id, [])
            if required:
                matching_defects = [d for d in required if any(
                    d in defect for defect in defects_lower
                )]
                if not matching_defects:
                    # Defekt nicht vorhanden → Skip
                    result.skipped_phases.append(phase_id)
                    result.reasons[phase_id] = f"Kein {'/'.join(required)} detektiert"
                    continue

                # 3. Psychoakustische Hörschwelle: sehr schwache Defekte → reduzierte Stärke
                max_sev = max((sevs.get(d, 0.0) for d in matching_defects), default=0.0)
                if max_sev < 0.15:
                    result.reduced_phases[phase_id] = 0.3  # Minimale Stärke
                    result.reasons[phase_id] = f"{'/'.join(matching_defects)} unter Hörschwelle (sev={max_sev:.2f})"

            # 4. Phase behalten
            result.kept_phases.append(phase_id)

        result.reduction_pct = len(result.skipped_phases) / max(len(phases), 1) * 100
        logger.info("§AC Phase Pruning: %d→%d Phasen (%.0f%% reduziert), %d reduziert",
                     len(phases), len(result.kept_phases), result.reduction_pct,
                     len(result.reduced_phases))
        return result
