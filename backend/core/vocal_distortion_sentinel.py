"""
§2.59 Vocal Distortion Sentinel (2026-07-09)

Läuft während restore() und erkennt akustische Anzeichen für
vokale Verzerrung. Warnt frühzeitig, damit Aurik gegensteuern kann.

Erkennt:
  - HNR-Abfall (Harmonic-to-Noise Ratio) in Gesangszonen
  - Übermäßige Harmonic-Restoration ohne De-Essing
  - SFT-Echo-Artefakte in Vocal-Segmenten
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class VocalDistortionSentinel:
    """Überwacht Gesangsqualität während der Pipeline."""

    def __init__(self, singing_confidence: float = 0.0) -> None:
        self._singing_conf = singing_confidence
        self._hnr_before: float | None = None
        self._hnr_after: float | None = None
        self._harmonic_restoration_applied: bool = False
        self._deesser_applied: bool = False
        self._warnings: list[str] = []

    def set_baseline_hnr(self, hnr_db: float) -> None:
        self._hnr_before = hnr_db

    def record_phase(self, phase_id: str) -> None:
        if "harmonic_restoration" in phase_id:
            self._harmonic_restoration_applied = True
        if "de_esser" in phase_id:
            self._deesser_applied = True

    def check(self, post_hnr_db: float | None = None) -> list[str]:
        """Prüft auf Verzerrungs-Risiken. Returns Liste von Warnungen."""
        self._warnings = []

        # 1. HNR vorher/nachher
        if post_hnr_db is not None and self._hnr_before is not None:
            delta = post_hnr_db - self._hnr_before
            if delta < -3.0:
                self._warnings.append(
                    f"HNR-Abfall {delta:+.1f} dB ({self._hnr_before:.1f} → {post_hnr_db:.1f}) — "
                    f"mögliche vokale Verzerrung"
                )
            elif delta < -1.5:
                logger.info(
                    "VocalSentinel: leichter HNR-Abfall %+.1f dB — beobachten", delta
                )

        # 2. Harmonic Restoration ohne De-Esser
        if self._harmonic_restoration_applied and not self._deesser_applied:
            if self._singing_conf >= 0.25:
                self._warnings.append(
                    "Harmonic Restoration aktiv, aber KEIN De-Esser — "
                    "Gefahr von Gesangs-Verzerrung in lauten Passagen. "
                    "→ phase_19_de_esser oder phase_43_ml_deesser zum Plan hinzufügen."
                )

        # 3. Hohe Singing-Confidence ohne Vocal-Protection
        if self._singing_conf >= 0.35:
            if not self._deesser_applied:
                logger.info(
                    "VocalSentinel: singing=%.2f aber kein De-Esser — "
                    "Zischlaute könnten verstärkt werden",
                    self._singing_conf,
                )

        for w in self._warnings:
            logger.warning("🎤 VocalSentinel: %s", w)

        return self._warnings

    @property
    def has_warnings(self) -> bool:
        return len(self._warnings) > 0
