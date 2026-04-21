"""Global calibration helpers for derived universal meta-parameters (§09.10).

All functions are pure and bounded. They only use existing pipeline inputs
and are safe to call from gates and target estimators.
"""

from __future__ import annotations

import numpy as np


def compute_tcci(transfer_chain: list[str] | None) -> float:
    """Transfer-Chain-Complexity-Index in [0, 1]."""
    chain = [str(m).strip().lower() for m in (transfer_chain or []) if str(m).strip()]
    n = max(1, len(chain))
    lossy = sum(1 for m in chain if m in {"mp3_low", "aac", "streaming"})
    analog = sum(
        1 for m in chain if m in {"wax_cylinder", "shellac", "vinyl", "tape", "cassette", "wire_recording", "reel_tape"}
    )
    score = 0.18 * float(n - 1) + 0.22 * float(lossy) + 0.10 * float(max(0, analog - 1))
    return float(np.clip(score, 0.0, 1.0))


def compute_ibs(restorability: float, defect_severity_mean: float, tcci: float) -> float:
    """Intervention-Budget-Scalar in [0.15, 0.95]."""
    r = 1.0 - float(np.clip(restorability / 100.0, 0.0, 1.0))
    d = float(np.clip(defect_severity_mean, 0.0, 1.0))
    c = float(np.clip(tcci, 0.0, 1.0))
    budget = 0.55 * r + 0.30 * d + 0.15 * c
    return float(np.clip(budget, 0.15, 0.95))


def blend_targets_with_confidence(
    canonical: dict[str, float],
    song_targets: dict[str, float],
    medium_conf: float,
    era_conf: float,
    genre_conf: float,
) -> dict[str, float]:
    """Blend per-song targets with canonical floors based on confidence."""
    conf = float(np.clip(0.45 * medium_conf + 0.30 * era_conf + 0.25 * genre_conf, 0.0, 1.0))
    blended: dict[str, float] = {}
    for goal, floor in canonical.items():
        t = float(song_targets.get(goal, floor))
        blended[goal] = float((1.0 - conf) * float(floor) + conf * t)
    return blended


def compute_cpb(material_ceiling: float, current_value: float, mode: str) -> float:
    """Ceiling-Proximity-Budget in [0, material_ceiling]."""
    mc = max(0.0, float(material_ceiling))
    cv = max(0.0, float(current_value))
    margin = max(0.0, mc - cv)
    safety = 0.70 if str(mode).strip().lower() == "restoration" else 0.50
    return float(np.clip(safety * margin, 0.0, mc))


def compute_retry_temperature(restorability: float, tcci: float, artifact_freedom_score: float) -> float:
    """Retry aggressiveness temperature in [0, 1]."""
    hard_song = 1.0 - float(np.clip(restorability / 100.0, 0.0, 1.0))
    chain = float(np.clip(tcci, 0.0, 1.0))
    artifact_risk = 1.0 - float(np.clip(artifact_freedom_score, 0.0, 1.0))
    t = 0.50 * hard_song + 0.30 * chain + 0.20 * artifact_risk
    return float(np.clip(t, 0.0, 1.0))


def compute_export_reliability(
    hpi: float,
    artifact_freedom: float,
    passed_goals: int,
    total_goals: int,
    reference_confidence: float,
) -> float:
    """Export reliability score in [0, 1]."""
    total = int(total_goals)
    ratio = 0.0 if total <= 0 else float(np.clip(float(passed_goals) / float(total), 0.0, 1.0))
    score = (
        0.35 * float(np.clip(hpi, 0.0, 1.0))
        + 0.30 * float(np.clip(artifact_freedom, 0.0, 1.0))
        + 0.20 * ratio
        + 0.15 * float(np.clip(reference_confidence, 0.0, 1.0))
    )
    return float(np.clip(score, 0.0, 1.0))


def compute_goal_coverage_index(musical_goals_passed: dict[str, bool] | None) -> float:
    """Priority-weighted musical-goal coverage in [0, 1]."""
    passed = dict(musical_goals_passed or {})
    if not passed:
        return 0.0

    weights = {
        # P1
        "natuerlichkeit": 1.4,
        "authentizitaet": 1.4,
        # P2
        "tonal_center": 1.2,
        "tonalcenter": 1.2,
        "timbre_authentizitaet": 1.2,
        "artikulation": 1.2,
        # P3
        "emotionalitaet": 1.0,
        "mikrodynamik": 1.0,
        "micro_dynamics": 1.0,
        "groove": 1.0,
        # P4
        "transparenz": 0.8,
        "waerme": 0.8,
        "basskraft": 0.8,
        "bass_kraft": 0.8,
        "separation_fidelity": 0.8,
        # P5
        "brillanz": 0.6,
        "raumtiefe": 0.6,
        "spatial_depth": 0.6,
    }

    score = 0.0
    total = 0.0
    for g, ok in passed.items():
        k = str(g).strip().lower()
        w = float(weights.get(k, 1.0))
        total += w
        if bool(ok):
            score += w

    if total <= 0.0:
        return 0.0
    return float(np.clip(score / total, 0.0, 1.0))


def compute_reference_confidence(target_confidence: float, tcci: float, carrier_chain_recovery_ratio: float) -> float:
    """Calibrated reference confidence in [0, 1] from existing reliability signals."""
    tc = float(np.clip(target_confidence, 0.0, 1.0))
    chain_stability = 1.0 - float(np.clip(tcci, 0.0, 1.0))
    # High carrier-recovery-ratio means stronger intentional divergence from degraded input.
    # This lowers confidence in strict input-referenced proxies.
    carrier_stability = 1.0 - float(np.clip(carrier_chain_recovery_ratio / 0.35, 0.0, 1.0))
    conf = 0.65 * tc + 0.20 * chain_stability + 0.15 * carrier_stability
    return float(np.clip(conf, 0.0, 1.0))


def compute_recovery_pressure_index(
    fallback_attempts: int,
    rollback_count: int,
    goal_deficit_ratio: float,
) -> float:
    """Recovery pressure in [0, 1] based on recovery attempts, rollbacks and missing goals."""
    fa = float(np.clip(float(fallback_attempts) / 3.0, 0.0, 1.0))
    rb = float(np.clip(float(rollback_count) / 8.0, 0.0, 1.0))
    gd = float(np.clip(goal_deficit_ratio, 0.0, 1.0))
    rpi = 0.40 * fa + 0.35 * rb + 0.25 * gd
    return float(np.clip(rpi, 0.0, 1.0))


# ---------------------------------------------------------------------------
# §09.1 Kanonische Schwellwerte (Single Source of Truth)
# ---------------------------------------------------------------------------

CANONICAL_THRESHOLDS_RESTORATION: dict[str, float] = {
    "natuerlichkeit": 0.90,
    "authentizitaet": 0.88,
    "tonal_center": 0.95,
    "tonalcenter": 0.95,
    "timbre_authentizitaet": 0.87,
    "artikulation": 0.85,
    "emotionalitaet": 0.82,
    "mikrodynamik": 0.88,
    "micro_dynamics": 0.88,
    "groove": 0.83,
    "transparenz": 0.82,
    "waerme": 0.75,
    "bass_kraft": 0.78,
    "basskraft": 0.78,
    "separation_fidelity": 0.78,
    "brillanz": 0.78,
    "raumtiefe": 0.70,
    "spatial_depth": 0.70,
}

CANONICAL_THRESHOLDS_STUDIO2026: dict[str, float] = {
    "natuerlichkeit": 0.92,
    "authentizitaet": 0.90,
    "tonal_center": 0.96,
    "tonalcenter": 0.96,
    "timbre_authentizitaet": 0.89,
    "artikulation": 0.87,
    "emotionalitaet": 0.84,
    "mikrodynamik": 0.90,
    "micro_dynamics": 0.90,
    "groove": 0.85,
    "transparenz": 0.85,
    "waerme": 0.78,
    "bass_kraft": 0.80,
    "basskraft": 0.80,
    "separation_fidelity": 0.80,
    "brillanz": 0.82,
    "raumtiefe": 0.74,
    "spatial_depth": 0.74,
}

# ---------------------------------------------------------------------------
# §09.2 Per-Song Goal-Targets — Era × Material × Genre Bias-Tabellen
# ---------------------------------------------------------------------------

_ERA_BIAS: dict[str, dict[str, float]] = {
    "1920s": {
        "brillanz": -0.28,
        "transparenz": -0.18,
        "raumtiefe": -0.14,
        "waerme": +0.14,
        "authentizitaet": +0.10,
        "natuerlichkeit": +0.08,
    },
    "1950s": {
        "brillanz": -0.14,
        "transparenz": -0.08,
        "waerme": +0.10,
        "authentizitaet": +0.08,
    },
    "1970s": {
        "brillanz": +0.04,
        "transparenz": +0.04,
        "waerme": +0.02,
    },
    "1990s": {
        "brillanz": +0.10,
        "transparenz": +0.10,
        "artikulation": +0.06,
        "waerme": -0.04,
    },
}

_MATERIAL_BIAS: dict[str, dict[str, float]] = {
    # Ultra-analog (Shellac, Wax, Wire)
    "ultra_analog": {
        "brillanz": -0.24,
        "transparenz": -0.12,
        "waerme": +0.10,
        "authentizitaet": +0.10,
    },
    # Normal-analog (Vinyl, Tape, Cassette)
    "analog": {
        "waerme": +0.10,
        "brillanz": -0.06,
        "authentizitaet": +0.08,
    },
    # Digital (CD, DAT, Streaming)
    "digital": {
        "transparenz": +0.08,
        "artikulation": +0.06,
        "brillanz": +0.06,
    },
}

_MATERIAL_CLASS: dict[str, str] = {
    "wax_cylinder": "ultra_analog",
    "shellac": "ultra_analog",
    "wire_recording": "ultra_analog",
    "lacquer_disc": "ultra_analog",
    "vinyl": "analog",
    "lp": "analog",
    "tape": "analog",
    "reel_tape": "analog",
    "cassette": "analog",
    "kassette": "analog",
    "cd_digital": "digital",
    "cd": "digital",
    "dat": "digital",
    "minidisc": "digital",
    "mp3_low": "digital",
    "mp3_high": "digital",
    "aac": "digital",
}

_GENRE_BIAS: dict[str, dict[str, float]] = {
    "klassik": {
        "raumtiefe": +0.18,
        "natuerlichkeit": +0.12,
        "mikrodynamik": +0.10,
        "brillanz": -0.08,
    },
    "jazz": {
        "waerme": +0.12,
        "natuerlichkeit": +0.10,
        "authentizitaet": +0.10,
        "transparenz": -0.04,
    },
    "schlager": {
        # bass_kraft −0.32: Schlager hat physikalisch geringen Bassanteil (heller Vokal-Mix,
        # Vinyl-Schneidebeschränkungen <80 Hz). bass_ratio typisch 0.002–0.005 statt 0.05
        # → Score max. ~0.20 ohne künstliche Bass-Anhebung (§0-Verletzung).
        # Threshold 0.78 → 0.46 ist genre-realistisch und §0-konform.
        "waerme": +0.10,
        "groove": +0.06,
        "authentizitaet": +0.08,
        "bass_kraft": -0.32,
    },
    "pop": {
        # bass_kraft −0.12: Heller Pop-Mix (1970s–1990s) hat weniger Bassanteil als
        # Rock/Electronic. Threshold leicht senken ohne §0-Verletzung.
        "transparenz": +0.08,
        "artikulation": +0.08,
        "brillanz": +0.08,
        "bass_kraft": -0.12,
    },
    "rock": {
        "bass_kraft": +0.08,
        "mikrodynamik": +0.06,
        "groove": +0.08,
    },
    "electronic": {
        "transparenz": +0.10,
        "bass_kraft": +0.10,
        "brillanz": +0.08,
    },
    "folk": {
        "natuerlichkeit": +0.12,
        "authentizitaet": +0.10,
        "waerme": +0.08,
    },
}


def _era_key(decade: int | None) -> str:
    """Map decade to bias bucket."""
    if decade is None:
        return "1970s"
    if decade < 1950:
        return "1920s"
    if decade < 1970:
        return "1950s"
    if decade < 1990:
        return "1970s"
    return "1990s"


def estimate_song_goal_targets(
    *,
    is_studio_2026: bool = False,
    goal_weights: dict[str, float] | None = None,
    restorability_score: float = 70.0,
    era_decade: int | None = None,
    genre_label: str | None = None,
    material_type: str | None = None,
    transfer_chain: list[str] | None = None,
) -> dict[str, float]:
    """Compute per-song goal targets as studio-day reconstruction targets.

    Returns a dict mapping each goal name to its target value ∈ [0.30, 0.99].
    Targets are blended from canonical floors (§09.1), era-/material-/genre-biases
    (§09.2), goal importance weights (§2.56) and restorability.

    These targets indicate where the pipeline *should stop* — the reconstructed
    studio-day score for this specific song.  They are NOT hard gates; they inform
    PhaseConductor strength recommendations and PMGG over-processing detection.

    Args:
        is_studio_2026: Studio 2026 mode uses higher canonical floors.
        goal_weights:   Per-song goal importance from §2.56 (1.0 = default).
        restorability_score: 0–100 from RestorabilityEstimator.
        era_decade:     Decade (e.g. 1970) from EraClassifier.
        genre_label:    Genre string (e.g. "schlager") from GenreClassifier.
        material_type:  Primary material (e.g. "vinyl") from MediumDetector.
        transfer_chain: Full chain list (e.g. ["vinyl","tape","mp3_low"]).

    Returns:
        dict[str, float]: Per-goal targets, same keys as CANONICAL_THRESHOLDS.
    """
    canonical = CANONICAL_THRESHOLDS_STUDIO2026 if is_studio_2026 else CANONICAL_THRESHOLDS_RESTORATION
    weights = goal_weights or {}
    rest_norm = float(np.clip(restorability_score / 100.0, 0.0, 1.0))

    # Resolve material from chain if not given directly
    primary_mat = (str(material_type or "").strip().lower()) or (
        str((transfer_chain or [""])[0]).strip().lower() if transfer_chain else ""
    )
    mat_class = _MATERIAL_CLASS.get(primary_mat, "analog")
    era_bucket = _era_key(era_decade)
    genre_key = str(genre_label or "").strip().lower()

    # Accumulate biases
    bias: dict[str, float] = {}
    for b_dict in [
        _ERA_BIAS.get(era_bucket, {}),
        _MATERIAL_BIAS.get(mat_class, {}),
        _GENRE_BIAS.get(genre_key, {}),
    ]:
        for goal, delta in b_dict.items():
            bias[goal] = bias.get(goal, 0.0) + float(delta)

    # kappa: how strongly biases are applied (low restorability → more conservative)
    # Restoration: 0.45; Studio 2026: 0.65; modulated by restorability
    kappa_base = 0.65 if is_studio_2026 else 0.45
    kappa = kappa_base * (0.60 + 0.40 * rest_norm)  # range: [0.27, 0.65] Restoration

    targets: dict[str, float] = {}
    for goal, floor in canonical.items():
        b = bias.get(goal, 0.0)
        w = float(weights.get(goal, 1.0))
        # goal weight > 1.0 → song needs this goal → stay closer to or above floor
        # goal weight < 1.0 → goal less important for this song → can tolerate lower target
        weight_shift = (w - 1.0) * 0.06  # ±0.06 max per unit weight deviation
        target = floor + kappa * b + weight_shift
        # Hard bounds: never below 0.30, never above 0.99 (1.0 is unreachable)
        targets[goal] = float(np.clip(target, 0.30, 0.99))

    return targets


# ---------------------------------------------------------------------------
# §09.7 Expected Quality Score (UI Baseline Prediction)
# ---------------------------------------------------------------------------

_MATERIAL_QUALITY_CEILING: dict[str, float] = {
    "wax_cylinder": 0.55,
    "shellac": 0.70,
    "lacquer_disc": 0.68,
    "wire_recording": 0.65,
    "vinyl": 0.88,
    "lp": 0.88,
    "tape": 0.85,
    "reel_tape": 0.86,
    "cassette": 0.80,
    "cd_digital": 0.95,
    "cd": 0.95,
    "dat": 0.92,
    "minidisc": 0.85,
    "mp3_low": 0.78,
    "mp3_high": 0.88,
}


def predict_quality_score(
    material_type: str,
    restorability: float,
    defect_severity_mean: float,
    is_studio_2026: bool = False,
) -> float:
    """Predict expected OQS (Overall Quality Score) after full pipeline.

    Pure function — safe to call from UI/Bridge before processing starts.
    Returns a value ∈ [0.0, 0.99].
    """
    mat = str(material_type or "").strip().lower()
    ceiling = _MATERIAL_QUALITY_CEILING.get(mat, 0.75)
    rest_norm = float(np.clip(restorability / 100.0, 0.0, 1.0))
    defect_penalty = float(np.clip(defect_severity_mean, 0.0, 1.0)) * 0.15
    studio_boost = 0.08 if is_studio_2026 else 0.0
    score = rest_norm * ceiling - defect_penalty + studio_boost
    return float(np.clip(score, 0.0, 0.99))


__all__ = [
    "blend_targets_with_confidence",
    "compute_cpb",
    "compute_export_reliability",
    "compute_goal_coverage_index",
    "compute_ibs",
    "compute_recovery_pressure_index",
    "compute_reference_confidence",
    "compute_retry_temperature",
    "compute_tcci",
    "estimate_song_goal_targets",
    "predict_quality_score",
]
