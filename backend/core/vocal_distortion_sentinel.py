"""
§2.59 Vocal Distortion Sentinel — AKTIV (2026-07-09)

Erkennt Gesangsverzerrung und HANDELT:
1. Warnt lautstark (WARNING)
2. Injiziert De-Esser in den Phasenplan
3. Reduziert Harmonic-Restoration-Stärke
4. Meldet an RestorationContext für Downstream-Phasen

Aktiviert bei: HNR-Abfall > 3 dB oder Harmonic-Restoration ohne De-Esser.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class VocalDistortionSentinel:
    def __init__(self, singing_confidence: float = 0.0) -> None:
        self._singing_conf = singing_confidence
        self._hnr_before: float | None = None
        self._hnr_after: float | None = None
        self._harmonic_restoration_applied: bool = False
        self._deesser_applied: bool = False
        self._warnings: list[str] = []
        self._injected_phases: list[str] = []
        self._strength_overrides: dict[str, float] = {}

    def set_baseline_hnr(self, hnr_db: float) -> None:
        self._hnr_before = hnr_db

    def record_phase(self, phase_id: str) -> None:
        if "harmonic_restoration" in phase_id:
            self._harmonic_restoration_applied = True
        if "de_esser" in phase_id or "deesser" in phase_id:
            self._deesser_applied = True

    def check(self, post_hnr_db: float | None = None) -> dict[str, Any]:
        """Check + ACT: Returns dict with actions for UV3."""
        self._warnings = []
        self._injected_phases = []
        self._strength_overrides = {}

        # 1. HNR-Abfall → AKTION: Harmonic Restoration drosseln
        if post_hnr_db is not None and self._hnr_before is not None:
            delta = post_hnr_db - self._hnr_before
            if delta < -3.0:
                self._warnings.append(
                    f"HNR-Abfall {delta:+.1f} dB → Harmonic Restoration wird "
                    f"auf 30% reduziert"
                )
                self._strength_overrides["phase_07_harmonic_restoration"] = 0.30
            elif delta < -1.5:
                self._strength_overrides["phase_07_harmonic_restoration"] = 0.50

        # 2. Harmonic Restoration ohne De-Esser → AKTION: De-Esser injizieren
        if self._harmonic_restoration_applied and not self._deesser_applied:
            if self._singing_conf >= 0.25:
                self._warnings.append(
                    "Harmonic Restoration AKTIV aber KEIN De-Esser → "
                    "phase_19_de_esser + phase_43_ml_deesser werden injiziert"
                )
                self._injected_phases.extend([
                    "phase_19_de_esser",
                    "phase_43_ml_deesser",
                ])
                self._strength_overrides["phase_07_harmonic_restoration"] = 0.40

        # 3. Gesang erkannt → Vocal-Protection aktivieren
        if self._singing_conf >= 0.35 and not self._deesser_applied:
            self._injected_phases.append("phase_19_de_esser")

        for w in self._warnings:
            logger.warning("🎤 VocalSentinel AKTION: %s", w)

        return {
            "warnings": self._warnings,
            "injected_phases": self._injected_phases,
            "strength_overrides": self._strength_overrides,
            "has_actions": bool(self._injected_phases or self._strength_overrides),
        }
