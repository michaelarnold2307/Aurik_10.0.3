"""AURIK Unified Defect Detection System v8.2.

Systematische Audio-Defekt-Erkennung mit Severity Scoring und Treatment
Recommendations. Die Legacy-Schicht bleibt als kompatibler Adapter erhalten,
die kanonische Defekt- und Phasenlogik liegt in `backend.core`.

Unterstützte Defekte:
- Clipping (Übersteuerung)
- Clicks & Pops (Vinyl, digitale Fehler)
- Crackle (Vinyl-Rauschen)
- Broadband Noise (Rauschen)
- Hum & Buzz (50/60 Hz, Harmonische)
- Distortion (THD, IMD)
- Spectral Artifacts (Musical Noise, Pre-Echo)
- Low Frequency Rumble
- High Frequency Roll-off
- Stereo Imbalance

Usage:
    from backend.defect_detection import UnifiedDefectDetector

    detector = UnifiedDefectDetector()
    report = detector.analyze(audio, sr)
"""

from backend.defect_detection.base import (
    DefectDetector,
    DefectInstance,
    DefectReport,
    DefectType,
    SeverityLevel,
    TreatmentRecommendation,
)
from backend.defect_detection.registry import DefectDetectorRegistry
from backend.defect_detection.treatment_recommender import TreatmentRecommender
from backend.defect_detection.unified_detector import UnifiedDefectDetector

__version__ = "9.15.0"

__all__ = [
    "DefectDetector",
    "DefectDetectorRegistry",
    "DefectInstance",
    "DefectReport",
    "DefectType",
    "SeverityLevel",
    "TreatmentRecommendation",
    "TreatmentRecommender",
    "UnifiedDefectDetector",
]
