"""Shared output guard helpers for high-quality phase acceptance checks."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class OutputGuardDecision:
    """Decision payload used by high-quality output guards."""

    fallback: bool
    reason: str
    rms_delta_db: float
    stereo_side_ratio: float


def rms(audio: np.ndarray) -> float:
    """Return RMS for mono/stereo audio."""
    x = np.nan_to_num(audio.astype(np.float64), nan=0.0, posinf=0.0, neginf=0.0)
    return float(np.sqrt(np.mean(x**2) + 1e-12))


def side_rms(audio: np.ndarray) -> float:
    """Return side-channel RMS for stereo audio."""
    if audio.ndim != 2 or audio.shape[1] != 2:
        return 0.0
    side = 0.5 * (audio[:, 0].astype(np.float64) - audio[:, 1].astype(np.float64))
    return float(np.sqrt(np.mean(side**2) + 1e-12))


def evaluate_output_guard(
    *,
    original: np.ndarray,
    candidate: np.ndarray,
    enabled: bool,
    max_abs_rms_delta_db: float,
    stereo_side_ratio_min: float,
    stereo_side_ratio_max: float,
) -> OutputGuardDecision:
    """Evaluate conservative output guard constraints for phase outputs."""
    rms_delta_db = float(20.0 * np.log10((rms(candidate) + 1e-12) / (rms(original) + 1e-12)))
    side_ratio = 1.0
    is_stereo = original.ndim == 2 and original.shape[1] == 2 and candidate.ndim == 2 and candidate.shape[1] == 2
    if is_stereo:
        side_ratio = float((side_rms(candidate) + 1e-12) / (side_rms(original) + 1e-12))

    if not enabled:
        return OutputGuardDecision(False, "disabled", rms_delta_db, side_ratio)

    if abs(rms_delta_db) > float(max_abs_rms_delta_db):
        return OutputGuardDecision(True, "rms_shift", rms_delta_db, side_ratio)

    if is_stereo and not (float(stereo_side_ratio_min) <= side_ratio <= float(stereo_side_ratio_max)):
        return OutputGuardDecision(True, "stereo_side_ratio", rms_delta_db, side_ratio)

    return OutputGuardDecision(False, "ok", rms_delta_db, side_ratio)
