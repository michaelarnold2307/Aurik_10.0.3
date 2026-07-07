"""
§2.59 Intro Defect Zone Detector (2026-07-09)

Erkennt transient Bandfehler, die NUR am Song-Anfang auftreten
(Leader-Tape, Anlauf-Störungen, Kopf-Kontakt-Probleme).
Markiert diese Zonen für fokussierte, hochpräzise Reparatur.

Prinzip: Nicht das ganze Lied gleich behandeln.
Nur die kranken Stellen operieren. Der Rest bleibt unberührt.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class IntroDefectZone:
    """Eine Zone mit konzentrierten Bandfehlern am Song-Anfang."""

    def __init__(
        self,
        start_s: float,
        end_s: float,
        defect_type: str,
        severity: float,
    ) -> None:
        self.start_s = start_s
        self.end_s = end_s
        self.defect_type = defect_type
        self.severity = severity


class IntroDefectAnalyzer:
    """Analysiert die ersten 30 Sekunden auf konzentrierte Bandfehler."""

    INTRO_DURATION_S: float = 30.0
    MIN_SEVERITY: float = 0.3

    def analyze(
        self,
        defect_scores: dict[str, float],
        transport_bump_count: int = 0,
        audio_duration_s: float = 0.0,
    ) -> list[IntroDefectZone]:
        """Findet Bandfehler-Zonen, die auf den Song-Anfang konzentriert sind.

        Returns:
            Liste von IntroDefectZone, sortiert nach Startzeit.
        """
        zones: list[IntroDefectZone] = []

        # Bandfehler, die typischerweise am Anfang konzentriert sind
        intro_defect_types = {
            "wow": "Geschwindigkeitsschwankung beim Anlauf",
            "flutter": "Flutter beim Bandstart",
            "transport_bump": "Transport-Störung",
            "modulation_noise": "Band-Anlauf-Rauschen",
            "dropouts": "Kopf-Kontakt-Aussetzer",
        }

        for defect_type, description in intro_defect_types.items():
            sev = defect_scores.get(defect_type, 0.0)
            if sev < self.MIN_SEVERITY:
                continue

            # Zone: erste INTRO_DURATION_S Sekunden
            end_s = min(self.INTRO_DURATION_S, audio_duration_s if audio_duration_s > 0 else 30.0)
            zones.append(IntroDefectZone(0.0, end_s, defect_type, sev))

        # Transport-Bump ist besonders stark am Anfang
        if transport_bump_count > 50:
            zones.append(
                IntroDefectZone(0.0, min(15.0, audio_duration_s),
                                "transport_bump", 0.70)
            )

        if zones:
            logger.info(
                "IntroDefectAnalyzer: %d Bandfehler-Zone(n) am Song-Anfang "
                "(0–%.0fs) für fokussierte Reparatur markiert",
                len(zones),
                self.INTRO_DURATION_S,
            )
            for z in zones:
                logger.debug("  Zone: %.1f–%.1fs %s (sev=%.2f)",
                             z.start_s, z.end_s, z.defect_type, z.severity)

        return zones
