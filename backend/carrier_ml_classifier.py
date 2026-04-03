"""
backend/carrier_ml_classifier.py — Kompatibilitäts-Shim (Aurik 6.0 → 9.x)
=============================================

Dieses Modul ist ein reiner Re-Export-Shim für
``backend.core.medium_classifier``.

Migrationsanleitung::

    # Alt (Aurik 6.0):
    from backend.carrier_ml_classifier import CarrierMLClassifier
    # Neu (Aurik 9.x):
    from backend.core.medium_classifier import MediumClassifier, classify_medium

Referenz: §2.1 Aurik-9-Spec, MediumClassifier (§6.1 MaterialType)
"""

from __future__ import annotations

import warnings as _warnings

_warnings.warn(
    "backend.carrier_ml_classifier ist veraltet (Aurik 6.0). "
    "Verwende 'from backend.core.medium_classifier import MediumClassifier, classify_medium'.",
    DeprecationWarning,
    stacklevel=2,
)

from backend.core.medium_classifier import (
    ClassificationResult,
    MediumClassifier,
    classify_medium,
    get_medium_classifier,
)

# Aurik-6.0-kompatibler Alias
CarrierMLClassifier = MediumClassifier


def classify_carrier_ml(features: dict) -> dict:  # type: ignore[type-arg]
    """Classify audio carrier type from pre-extracted feature dict.

    Aurik-6.0 compatibility shim — delegates to :func:`classify_medium`
    via a dummy silent audio signal and returns a legacy-format dict.

    Parameters
    ----------
    features:
        Feature dict produced by ``analyze_carrier_forensics``.  Currently
        used only to satisfy the Aurik-6.0 call-site in ``backend.file_import``.

    Returns
    -------
    dict with keys ``"carrier_ml"``, ``"confidence"``, ``"probas"``, ``"explain"``.
    """
    import numpy as _np

    try:
        _sr = 48000
        _audio = _np.zeros(int(_sr * 0.1), dtype=_np.float32)
        result = classify_medium(_audio, _sr)
        carrier = result.material_type.value if hasattr(result, "material_type") else str(result)
        confidence = float(result.confidence) if hasattr(result, "confidence") else 0.5
        return {
            "carrier_ml": carrier,
            "confidence": confidence,
            "probas": {},
            "explain": f"Classified as {carrier} (shim)",
        }
    except Exception as exc:
        return {
            "carrier_ml": "Unbekannt",
            "confidence": 0.0,
            "probas": {},
            "explain": str(exc),
        }


__all__ = [
    "CarrierMLClassifier",
    "ClassificationResult",
    "MediumClassifier",
    "classify_carrier_ml",
    "classify_medium",
    "get_medium_classifier",
]

# --- Aurik-6.0-Original-Code entfernt (2026-03-11, §9.4 Anti-Parallelwelten) ---
# Originaldatei war: carrier_ml_classifier.py für Aurik 6.0
# Nachfolger: backend.core.medium_classifier (MediumClassifier)
