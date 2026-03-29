"""
PerPhaseMusicalGoalsGate (PMGG) — Aurik 9.0 §2.29
===================================================

Prüft Musical Goals nach JEDER Phase via 5-s-Stichprobe.
Verhindert kumulative Degradation über 56 Phasen.

PROBLEM:
--------
Jede Phase kann Musical Goals minimal verslechtern (z.B. Δ-0.01).
Über 20+ aktive Phasen kumuliert das zu -0.20 → ein Ziel fällt unter
den Pflicht-Schwellwert. Der End-Check kann das nicht mehr korrigieren.

ALGORITHMUS:
-----------
Pro Phase (wrap_phase()):
    1. 5-s-Stichprobe aus Mitte des Audios
    2. Phase ausführen: audio_after = phase(audio_before)
    3. Schnell-Check (14 Ziele, ≤ 200 ms, DSP-only):
       Brillanz, Wärme, Groove, TonalCenter, Natürlichkeit (MFCC-Proxy),
       Timbre-Authentizität, Bass-Kraft, Authentizität, Emotionalität,
       Transparenz, Spatial Depth, Mikro-Dynamik, Separation-Treue, Artikulation
    4. Δ = score_after − score_before für jedes Ziel
       Falls Δ < −REGRESSION_THRESHOLD (adaptiv je nach Restorability):
         Retry-1: Phase mit strength × 0.65
         Retry-2: Phase mit strength × 0.50  (v9.15-B3: sanfterer Gradient)
         Retry-3: Phase mit strength × 0.35
         Retry-4: Phase mit strength × 0.20
         Retry-5 (Last-Resort): Phase mit strength × 0.10
         Falls immer noch: Best-Effort — Versuch mit geringster Regression wird
         angewendet. KEIN Rollback/Skip erlaubt (§2.29 v9.10.64).

WICHTIG (§2.29 v9.10.64):
-----------
PMGG darf Phasen NIEMALS überspringen (kein Rollback auf Original-Audio).
CausalDefectReasoner hat die Phase als notwendig bestimmt — sie MUSS angewendet
werden, ggf. mit reduzierter Stärke (best-effort).

KONSTANTEN:
-----------
REGRESSION_THRESHOLD = 0.025  (adaptiv: 0.012 / 0.040 / 0.060 je Restorability)
SAMPLE_DURATION_S    = 5.0
MAX_RETRIES          = 5  (v9.15-B3: 5 Retries mit sanftem Stärkegradienten)

OVERHEAD: max. 56 × 200 ms = 11.2 s pro Verarbeitungsdurchlauf (alle 14 Ziele DSP-only)
DEAKTIVIERUNG: --no-phase-gate (Debugging/Benchmarking)

WICHTIG: MERT wird im Schnell-Check NICHT verwendet (zu langsam: 800 ms)
Vollständige 14-Ziele-Prüfung bleibt am Pipeline-Ende (MusicalGoalsChecker)

Autor: Aurik 9.0 Development Team / v9.15
"""

from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

_PRECISE_METRICS_LOCK = threading.Lock()
_PRECISE_METRICS: dict[str, Any] | None = None
_PRECISE_OVERRIDE_WARN_MS: float = 200.0


# ---------------------------------------------------------------------------
# Konstanten (§2.29) — restorability-adaptive Schwellwerte
# ---------------------------------------------------------------------------
# Feste Einzel-Schwelle (Legacy-Fallback, nicht mehr primär verwendet)
REGRESSION_THRESHOLD: float = 0.025

# Restorability-adaptive Schwellwerte (§2.29 Spec)
# v9.10.76: 0.012 → 0.030 (DSP-Proxy-Messrauschen 0.01–0.05).
# v9.10.77: 0.030 → 0.020 — §9.7.5 Reference-Aware Preservation Corrections
# eliminieren den größten Teil des Messrauschens; engere Schwellwerte fangen
# nun echte Regressionen zuverlässiger ab ohne False-Positives.
REGRESSION_THRESHOLD_GOOD: float = 0.020  # restorability ≥ 70
REGRESSION_THRESHOLD_FAIR: float = 0.035  # restorability 40–69 (entspannter)
REGRESSION_THRESHOLD_POOR: float = 0.055  # restorability < 40 (maximal tolerant)

# ---------------------------------------------------------------------------
# §2.29 v9.10.77: Priority-aware Retry-Budget
# ---------------------------------------------------------------------------
# P1/P2 regressions trigger full retry cascade (4 Retries + Emergency).
# P3 regressions trigger max 2 retries with 1.5× relaxed threshold.
# P4/P5 regressions never trigger retries — only logged.
#
# Begründung (Pareto-Analyse): Hohe P3–P5-Schwellwerte verursachten unnötige
# PMGG-Retries (CPU-Verschwendung) und Cross-Goal-Damage (Natürlichkeit/
# Authentizität-Regression durch Over-Optimization nachrangiger Ziele).
# GoalPriorityProtocol.PRIORITY_MAP ist die Autoritätsquelle.
# ---------------------------------------------------------------------------
_PRIORITY_MAX_RETRIES: dict[int, int] = {
    1: 4,  # P1: Natürlichkeit, Authentizität — volle Retry-Kaskade
    2: 4,  # P2: TonalCenter, Timbre, Artikulation — volle Retry-Kaskade
    3: 2,  # P3: Emotionalität, MicroDynamics, Groove — max 2 Retries
    4: 0,  # P4: Transparenz, Wärme, Bass-Kraft, SepFidelity — kein Retry
    5: 0,  # P5: Brillanz, SpatialDepth — kein Retry
}

# Regression-Toleranz-Multiplikator pro Priorität.
# P3-Ziele haben 1.5× mehr Toleranz als P1/P2, bevor ein Retry ausgelöst wird.
_PRIORITY_THRESHOLD_FACTOR: dict[int, float] = {
    1: 1.0,
    2: 1.0,
    3: 1.5,
    4: 99.0,  # Effektiv kein Retry (Threshold × 99 = immer unter)
    5: 99.0,
}

SAMPLE_DURATION_S: float = 5.0
MAX_RETRIES: int = 5  # v9.15-B3: 5 Retries mit sanftem Stärkegradienten (0.65→0.50→0.35→0.20→0.10)

# ---------------------------------------------------------------------------
# §9.7.3 Phasen-adaptive Sample-Dauer — triviale Phasen brauchen < 5 s
# ---------------------------------------------------------------------------
PHASE_SAMPLE_DURATIONS: dict[str, float] = {
    # Triviale Phasen: Zeiteffekt ist lokal messbar in 1–2 s
    "phase_30": 1.5,  # DC-Offset-Removal
    "phase_05": 1.5,  # Rumble-Filter (< 20 Hz)
    "phase_02": 2.0,  # Hum-Removal (50/60 Hz Kammfilter)
    "phase_15": 1.5,  # Stereo-Balance L/R
    "phase_11": 1.5,  # Limiting (True-Peak)
    "phase_18": 2.0,  # Noise-Gate
    # Standard: SAMPLE_DURATION_S = 5.0 für alle anderen Phasen
}

# §9.7.4 Phase-specific goal exclusions.
# Goals whose DSP proxy is structurally unreliable for a given processing type.
# These goals are NOT checked for regression when the phase matches.
#
# v9.10.77: Exclusions significantly reduced thanks to §9.7.5 reference-aware
# preservation corrections.  Goals with spectral/temporal correlation support
# are now checked even for phases that previously triggered false positives.
# Only goals where processing FUNDAMENTALLY changes the measured quantity
# (and correlation cannot distinguish intentional change from degradation)
# remain excluded.
#
# Rationale for remaining exclusions:
#
# phase_02 (hum removal): 50/100/.../400 Hz comb-filter creates spectral
#   notches directly in the bass band → bass_kraft LF correlation still sees
#   notches as degradation because they ARE spectral removal (intentional).
#   authentizitaet excluded: comb-filter notches create spectral roughness
#   that is the intended action, not degradation.
#
# phase_04 (EQ correction): Spectral redistribution IS the core function.
#   transparenz (rolloff + balance) changes deliberately.
#
# phase_06 (frequency restoration): SBR intentionally adds HF content that
#   the reference doesn't have → correlation is LOW by design.
#   brillanz excluded because the increase IS the goal.
#
# phase_18 / phase_26 / phase_36: Dynamics-modifying phases intentionally
#   change the temporal envelope → micro_dynamics measures the intended change.
PHASE_GOAL_EXCLUSIONS: dict[str, set[str]] = {
    # Hum removal: comb-filter notches in bass band + spectral roughness.
    # natuerlichkeit excluded: CREPE voicing analysis in NatuerlichkeitMetric
    # flags 50/100 Hz notch-induced spectral-flatness changes as P1 regression.
    "phase_02": {"bass_kraft", "authentizitaet", "natuerlichkeit"},
    # Reconstruction phases: spectral correlation handles reconstruction well;
    # only keep exclusions where AI-generated content has low correlation by design
    # natuerlichkeit excluded: gap-fill synthesis produces content absent from
    # reference; CREPE voicing score on synthesised audio is unreliable.
    "phase_24": {"natuerlichkeit"},  # Dropout repair
    "phase_28": set(),  # Noise reduction variant: handled by correlation
    # Diffusion inpainting: synthesised content has no transient reference →
    # ArticulationMetric correlation vs pre-inpainting fragment is meaningless.
    # micro_dynamics excluded: inpainting inserts new content with its own
    # envelope that intentionally differs from the surrounding material.
    "phase_55": {"artikulation", "micro_dynamics"},  # Diffusion inpainting
    # Sub-sonic removal: reference LF correlation handles bass preservation check
    "phase_05": set(),  # Rumble filter
    "phase_30": set(),  # DC-offset removal
    # Broadband denoise: reference HF/LF correlation distinguishes noise from music
    # natuerlichkeit excluded: broadband denoising shifts spectral flatness and
    # ZCR, causing the CREPE-based NatuerlichkeitMetric to report false P1
    # regressions (~0.28) even at near-dry wet-mix.  DSP proxy with §9.7.5
    # reference-aware preservation correctly evaluates naturalness for denoise.
    # artikulation excluded: ArticulationMetric(reference=noisy_tape) measures
    # transient-shape correlation between the denoised output and the noisy input.
    # Denoising IS supposed to reshape transients (ResembleEnhance, OMLSA spectral
    # weighting) — scores_before(reference-free)≈0.67 vs scores_after(ref-based)≈0.13
    # produces a false P2 regression of ~0.54 that drives PMGG into best_effort at
    # strength=0.06 (virtually no denoising applied).  Root cause confirmed in debug
    # logs (2026-03-28): worst_goal=artikulation, before=0.665, after=0.126.
    "phase_03": {"natuerlichkeit", "artikulation"},  # OMLSA/ResembleEnhance
    # DeepFilterNet HF-removal intentionally reduces HF energy → brillanz drops.
    # artikulation excluded for same reason as phase_03: reference=hissy_tape vs
    # denoised output gives misleadingly low transient-correlation score.
    "phase_29": {"brillanz", "artikulation"},  # DeepFilterNet / tape hiss
    # Phases with RADICAL spectral changes where even correlation can't help:
    "phase_04": {"transparenz"},  # EQ deliberately redistributes spectrum
    "phase_06": {"brillanz"},  # SBR adds content not in reference → low correlation
    "phase_07": {"brillanz"},  # Harmonic synthesis adds new HF content
    "phase_08": set(),  # Transient preservation: handled by envelope correlation
    # Dynamics-modifying phases: intentional temporal envelope changes
    "phase_18": {"micro_dynamics"},  # Noise gate: deliberate silence insertion
    "phase_26": {"micro_dynamics", "artikulation"},  # Dynamic expansion
    "phase_36": {"micro_dynamics", "artikulation"},  # Transient shaper
    # Mastering: intentional dynamics compression + spectral shaping
    "phase_17": {"micro_dynamics", "natuerlichkeit"},
    # Vocal enhancement: Stages 2-6 intentionally alter spectral shape and dynamics;
    # natuerlichkeit/timbre proxies are unreliable for deliberate vocal-presence boosts.
    "phase_19": {"natuerlichkeit", "timbre_authentizitaet", "micro_dynamics"},
}


def _get_sample_duration(phase_id: str) -> float:
    """Gibt phasen-adaptive Stichprobenlänge zurück (§9.7.3).

    Minimale Sample-Dauer: 1.0 s (kein Unterschreiten).
    Maximale Sample-Dauer: SAMPLE_DURATION_S (5.0 s).
    Phase-ID-Matching via startswith — robust gegen Suffix-Varianten.
    """
    for prefix, dur in PHASE_SAMPLE_DURATIONS.items():
        if phase_id.startswith(prefix):
            return max(1.0, min(dur, SAMPLE_DURATION_S))
    return SAMPLE_DURATION_S


# Strength-Faktoren für Retry-Durchgänge
# v9.10.79: 5 Stufen für 5 vollständige Retries (0–4). Floor = 0.15 für Last-Resort.
# Psychoakustik: strength ≥ 0.15 still perceivable (−18 dB Wet bleiben unter Maskierungsschwelle).
# Nach 5 fehlgeschlagenen Retries: best-effort Anwendung (Spec §2.29 v9.10.64).
_RETRY_STRENGTHS: list[float] = [
    0.65,
    0.50,
    0.35,
    0.25,
    0.15,
]  # v9.10.79: 5 Stufen (Retry-Index 0–4), Floor 0.15 last-resort

# §2.29a ML-deterministische Phasen: Inference-Output ist bei gleichem Input
# identisch, unabhängig vom strength-Parameter.  Bei PMGG-Retries wird nur
# Wet/Dry-Reblending variiert — keine Re-Inferenz.
# Phase-ID-Prefixes (startswith-Match) für robustes Matching.
_ML_DETERMINISTIC_PHASES: frozenset[str] = frozenset(
    {
        "phase_03",  # OMLSA + ResembleEnhance (ML-Hybrid Denoising)
        "phase_06",  # AudioSR (neurale Bandwidth-Extension)
        "phase_09",  # BANQUET ONNX (Blind-Denoising)
        "phase_12",  # FCPE/CREPE/pYIN (f₀-Schätzung) — Timing-Phase, kein Wet/Dry
        "phase_18",  # Silero VAD (Binary-Mask)
        "phase_19",  # De-Esser+VocalStack: process() ignoriert strength → Wet/Dry reicht
        "phase_20",  # SGMSE+ (Reverb-Separation) — nur ML-deterministisch wenn SGMSE+ geladen
        # WPE-Fallback ist strength-abhängiger DSP → _phase20_is_ml_active() prüft zur Laufzeit
        "phase_23",  # AudioSR Inpainting (Spektral-Lückenfüllung)
        "phase_24",  # AudioSR (Dropout-Repair)
        "phase_29",  # DeepFilterNet v3 II (HF-Denoising)
        "phase_42",  # BSRoFormer (Stem-Separation)
        "phase_55",  # CQTdiff/FlowMatching (Diffusions-Inpainting)
        "phase_56",  # FCPE/CREPE + Synthese (Spectral Band Gap Repair)
    }
)


def _phase20_is_ml_active() -> bool:
    """Return True when SGMSE+ is currently loaded in the ML budget (§2.29a).

    phase_20 is ML-deterministic only when the SGMSE+ model is actually resident
    in memory.  When SGMSE+ was blocked by ml_memory_budget (OOM pressure) and
    the WPE-DSP fallback is active instead, wet/dry blending cannot represent the
    full range of WPE's strength-dependent predictor-order parameter.  In that
    case phase_20 must be treated as a strength-dependent DSP phase — re-run on
    every PMGG retry.
    """
    try:
        from backend.core.ml_memory_budget import get_status

        return "SGMSE+" in get_status().get("models", {})
    except Exception:
        return False  # Safe default: DSP path — must re-run


def _get_adaptive_threshold(restorability_score: float) -> float:
    """Restorability-adaptiver REGRESSION_THRESHOLD (§2.29).

    Args:
        restorability_score: RestorabilityEstimator-Score ∈ [0, 100]

    Returns:
        Adaptiver Schwellwert: 0.025 / 0.040 / 0.060.
    """
    if restorability_score >= 70.0:
        return REGRESSION_THRESHOLD_GOOD
    if restorability_score >= 40.0:
        return REGRESSION_THRESHOLD_FAIR
    return REGRESSION_THRESHOLD_POOR


# All 14 Musical Goals are checked per-phase — DSP-only proxies, no ML (≤ 200 ms total §2.29).
# "natuerlichkeit" uses an MFCC-smoothness DSP proxy internally but is exposed under its
# canonical key so GoalApplicabilityFilter intersection (§2.32) works correctly.
FAST_GOALS_SUBSET: list[str] = [
    "brillanz",
    "waerme",
    "groove",
    "tonal_center",
    "natuerlichkeit",  # canonical key — MFCC-smoothness DSP proxy, matches GoalApplicabilityFilter
    "timbre_authentizitaet",
    # 8 neu (DSP-Proxies, v9.10.57):
    "bass_kraft",
    "authentizitaet",
    "emotionalitaet",
    "transparenz",
    "spatial_depth",
    "micro_dynamics",
    "separation_fidelity",
    "artikulation",
]


# ---------------------------------------------------------------------------
# Datenklassen
# ---------------------------------------------------------------------------


@dataclass
class PhaseGateLogEntry:
    """Eintrag im phase_gate_log für eine Phase."""

    phase_id: str
    action: str  # "passed" | "retry1" | ... | "retry5" | "best_effort" | "best_effort_rN"
    goal_regressions: dict[str, float]  # Ziel → Δ-Score
    strength_used: float
    timestamp: float = field(default_factory=time.time)


@dataclass
class PhaseGateResult:
    """Ergebnis der wrap_phase()-Operation."""

    audio: np.ndarray
    scores_after: dict[str, float]
    log_entry: PhaseGateLogEntry
    rolled_back: bool


# ---------------------------------------------------------------------------
# Singleton (§3.2)
# ---------------------------------------------------------------------------
_instance: PerPhaseMusicalGoalsGate | None = None
_lock = threading.Lock()


def get_phase_gate() -> PerPhaseMusicalGoalsGate:
    """Thread-sicherer Singleton-Accessor (Double-Checked Locking)."""
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = PerPhaseMusicalGoalsGate()
    return _instance


# ---------------------------------------------------------------------------
# Schnell-Metriken (ohne MERT, ohne CDPAM, ohne externe ML-Modelle)
# ---------------------------------------------------------------------------


def _safe_pearson(a: np.ndarray, b: np.ndarray) -> float:
    """Pearson-Korrelation mit Längen-Matching und NaN/Inf-Sicherheit.

    Returns 0.0 bei Fehler oder zu wenig Daten.
    """
    n = min(len(a), len(b))
    if n < 4:
        return 0.0
    try:
        r = float(np.corrcoef(a[:n].ravel(), b[:n].ravel())[0, 1])
        return r if math.isfinite(r) else 0.0
    except Exception:
        return 0.0


def _get_precise_metric_instances() -> dict[str, Any]:
    """Lazy-load a small set of production musical-goal metrics for PMGG.

    These are used selectively for the most decision-critical goals where local
    DSP proxies are materially less precise than the canonical metric.
    """
    global _PRECISE_METRICS
    if _PRECISE_METRICS is None:
        with _PRECISE_METRICS_LOCK:
            if _PRECISE_METRICS is None:
                try:
                    from backend.core.musical_goals.musical_goals_metrics import (
                        ArticulationMetric,
                        BrillanzMetric,
                        MicroDynamicsMetric,
                        SeparationFidelityMetric,
                        TonalCenterMetric,
                        TransparenzMetric,
                        WaermeMetric,
                    )

                    _PRECISE_METRICS = {
                        "brillanz": BrillanzMetric(),
                        "waerme": WaermeMetric(),
                        # natuerlichkeit intentionally omitted: NatuerlichkeitMetric uses
                        # CREPE ML inference (1–4 s/call) with dynamic weight switching
                        # based on CREPE load state.  Between scores_before (CREPE not
                        # yet loaded → w_crepe=0.0) and scores_after (CREPE loaded →
                        # w_crepe=0.18) the absolute score shifts non-deterministically,
                        # creating systematic false P1 regressions in phase_03/phase_02.
                        # The DSP proxy in _measure_quick with §9.7.5 reference-aware
                        # preservation correction is more reliable for PMGG delta checks.
                        # The canonical NatuerlichkeitMetric still runs in the final
                        # export quality gate (MusicalGoalsChecker).
                        "tonal_center": TonalCenterMetric(),
                        "micro_dynamics": MicroDynamicsMetric(),
                        "artikulation": ArticulationMetric(),
                        "separation_fidelity": SeparationFidelityMetric(),
                        "transparenz": TransparenzMetric(),
                    }
                except Exception as exc:
                    logger.debug("PMGG precise metrics unavailable: %s", exc)
                    _PRECISE_METRICS = {}
    return _PRECISE_METRICS


def _apply_precise_metric_overrides(
    scores: dict[str, float],
    audio: np.ndarray,
    sr: int,
    reference: np.ndarray | None = None,
) -> dict[str, float]:
    """Refine selected quick scores using canonical metric implementations."""
    t0 = time.perf_counter()
    precise_metrics = _get_precise_metric_instances()
    if not precise_metrics:
        return scores

    # §9.7.7 Audio length cap: 2.5 s is sufficient for all precise metrics and
    # avoids long NMF/onset-detection runs in SeparationFidelityMetric /
    # ArticulationMetric on long audio samples.
    _cap = int(2.5 * sr)
    if audio.ndim == 1 and len(audio) > _cap:
        audio = audio[:_cap]
    elif audio.ndim == 2 and audio.shape[-1] > _cap:
        audio = audio[..., :_cap]
    if reference is not None:
        if reference.ndim == 1 and len(reference) > _cap:
            reference = reference[:_cap]
        elif reference.ndim == 2 and reference.shape[-1] > _cap:
            reference = reference[..., :_cap]

    refined = dict(scores)
    for goal_name, metric in precise_metrics.items():
        try:
            if goal_name == "micro_dynamics":
                # Always reference-free: scores_before is measured without reference,
                # so scores_after must use the same absolute mode for a fair comparison.
                # Reference-based MicroDynamicsMetric gives 0.60+ baseline vs ~0.75×corr
                # for scores_after, creating systematic false regressions in PMGG.
                refined[goal_name] = float(metric.measure(audio, sr))
            elif goal_name in {
                "brillanz",
                "waerme",
                "tonal_center",
                "artikulation",
                "separation_fidelity",
                "transparenz",
            }:
                refined[goal_name] = float(metric.measure(audio, sr, reference=reference))
            else:
                refined[goal_name] = float(metric.measure(audio, sr))
        except Exception as exc:
            logger.debug("PMGG precise metric override failed for %s: %s", goal_name, exc)

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    if elapsed_ms > _PRECISE_OVERRIDE_WARN_MS:
        logger.warning(
            "PMGG precise overrides slow: %.1f ms for %d goals",
            elapsed_ms,
            len(precise_metrics),
        )
    return refined


def _measure_quick(
    audio: np.ndarray, sr: int, reference: np.ndarray | None = None, *, precise_override: bool = True
) -> dict[str, float]:
    """
    Misst alle 14 Musical Goals auf einer 5-s-Stichprobe in ≤ 200 ms.

    §9.7.5 (v9.10.77): Referenz-aware Preservation-Korrekturen.
    Wenn ``reference`` übergeben wird, erhalten anfällige Goals einen
    Preservation-Bonus basierend auf spektraler Korrelation.  Dies beseitigt
    False-Positive-Regressionen bei Noise-Removal, EQ, Dynamics-Phasen
    und ermöglicht breitere Goal-Prüfung mit weniger Exclusions.

    Prinzip: Wenn die Korrelation zwischen Original und Verarbeitetem hoch ist
    (musikalischer Inhalt erhalten), wird der absolute Score nach oben korrigiert.
    Bei niedriger Korrelation (echte Degradation) bleibt der absolute Score.

    Args:
        audio: Mono oder Stereo, float32, beliebige Länge
        sr: 48000 Hz
        reference: Original-Audio vor Phasen-Verarbeitung (gleiche Länge).
            None = rein absolute Messung (für scores_before).

    Returns:
        Dict mit 14 Scores ∈ [0, 1]
    """
    mono = audio[:, 0] if audio.ndim == 2 else audio
    mono = np.nan_to_num(mono, nan=0.0).astype(np.float32)

    scores: dict[str, float] = {}

    # ── Pre-compute spectrum once — brillanz, waerme, bass_kraft, natuerlichkeit,
    #    authentizitaet, transparenz, separation_fidelity all share these arrays.
    #    If FFT fails every dependent metric gracefully falls back to 0.5 via its
    #    own try/except; the shared variables are always defined.
    try:
        fft_mag: np.ndarray = np.abs(np.fft.rfft(mono))
        freqs: np.ndarray = np.fft.rfftfreq(len(mono), d=1.0 / sr)
        tot_energy: float = float(np.mean(fft_mag**2)) + 1e-12
    except Exception:
        fft_mag = np.zeros(len(mono) // 2 + 1, dtype=np.float32)
        freqs = np.zeros(len(mono) // 2 + 1, dtype=np.float32)
        tot_energy = 1e-12

    # §9.7.5 Pre-compute reference spectrum for preservation corrections.
    # Computed once; used by all reference-aware goal branches below.
    _ref_fft: np.ndarray | None = None
    _ref_mono: np.ndarray | None = None
    if reference is not None:
        try:
            _rm = reference[:, 0] if reference.ndim == 2 else reference
            _rm = np.nan_to_num(_rm, nan=0.0).astype(np.float32)
            _ml = min(len(mono), len(_rm))
            _ref_mono = _rm[:_ml]
            _ref_fft = np.abs(np.fft.rfft(_ref_mono))
        except Exception:
            _ref_fft = None
            _ref_mono = None

    # ── Brillanz (HF-Energie > 8 kHz) ─────────────────────────────────
    try:
        hf_energy = float(np.mean(fft_mag[freqs > 8000] ** 2))
        scores["brillanz"] = float(np.clip(hf_energy / tot_energy / 0.3 + 0.4, 0.0, 1.0))
        # §9.7.5 Preservation: HF spectral correlation (>4 kHz broadband)
        if _ref_fft is not None:
            _hf = freqs[: len(_ref_fft)] > 4000
            if np.sum(_hf) > 10:
                _r = _safe_pearson(_ref_fft[_hf], fft_mag[: len(_ref_fft)][_hf])
                if _r > 0.7:
                    scores["brillanz"] = min(1.0, scores["brillanz"] + (_r - 0.7) * 0.5)
    except Exception:
        scores["brillanz"] = 0.5

    # ── Wärme (Mid-Range-Energie 200–2000 Hz) ──────────────────────────
    try:
        mid_energy = float(np.mean(fft_mag[(freqs >= 200) & (freqs <= 2000)] ** 2))
        scores["waerme"] = float(np.clip(mid_energy / tot_energy / 0.6 + 0.3, 0.0, 1.0))
    except Exception:
        scores["waerme"] = 0.5

    # ── Groove (Onset-Energie-Regularität via Autokorrelation) ─────────
    try:
        env = np.abs(mono)
        # Hüllkurven-Autokorrelation
        hop = sr // 100  # 10 ms
        # Vectorized: non-overlapping frames via reshape (replaces Python list comprehension)
        _nf_g = (len(env) - 1) // hop
        rms_env = (
            np.mean(env[: _nf_g * hop].reshape(_nf_g, hop) ** 2, axis=1) if _nf_g > 0 else np.empty(0, dtype=np.float32)
        )
        if len(rms_env) > 10:
            autocorr = np.correlate(rms_env, rms_env, mode="full")
            autocorr = autocorr[len(rms_env) - 1 :]
            autocorr /= autocorr[0] + 1e-12
            # Regularität: Autokorrelations-Peak bei ~0.5 s (typisch Groove)
            lag_05 = min(50, len(autocorr) - 1)  # 50 × 10 ms = 500 ms
            scores["groove"] = float(np.clip(autocorr[lag_05] * 0.5 + 0.5, 0.0, 1.0))
        else:
            scores["groove"] = 0.5
    except Exception:
        scores["groove"] = 0.5

    # ── Tonales Zentrum (Chroma-Konzentration) ─────────────────────────
    try:
        n_fft_chroma = 4096
        spec_mag = np.abs(np.fft.rfft(mono, n=n_fft_chroma))
        spec_freqs = np.fft.rfftfreq(n_fft_chroma, d=1.0 / sr)
        # Vectorized chroma accumulation (replaces ~355-iteration Python bin loop)
        chroma = np.zeros(12, dtype=np.float32)
        _cbins = np.where((spec_freqs > 27.5) & (spec_freqs < 4186))[0]
        if len(_cbins) > 0:
            _cn = np.round(12.0 * np.log2(spec_freqs[_cbins] / 440.0 + 1e-12)).astype(np.int32) % 12
            np.add.at(chroma, _cn, spec_mag[_cbins])
        else:
            _cn = np.empty(0, dtype=np.int32)
        if chroma.sum() > 1e-8:
            chroma /= chroma.sum()
            # Konzentration = 1 − Entropie/log(12)
            entropy = -float(np.sum(chroma * np.log(chroma + 1e-12)))
            tonal_score = 1.0 - entropy / math.log(12.0)
            scores["tonal_center"] = float(np.clip(tonal_score, 0.0, 1.0))
        else:
            scores["tonal_center"] = 0.5
        # §9.7.5 Preservation: Chroma-Korrelation mit Referenz.
        # Rauschentfernung erhöht Chroma-Entropie (bisher verborgene Bins
        # werden sichtbar), aber die Tonart bleibt erhalten.  Chroma-Pearson
        # ≥ 0.90 = Tonart bewahrt → Preservation-Bonus, damit PMGG keine
        # False-Positive-Regression für tonal_center meldet.
        if _ref_mono is not None:
            try:
                _ref_chroma = np.zeros(12, dtype=np.float32)
                _ref_spec = np.abs(np.fft.rfft(_ref_mono, n=n_fft_chroma))
                # Reuse _cbins/_cn from processed chroma (spec_freqs shared)
                if len(_cbins) > 0:
                    np.add.at(_ref_chroma, _cn, _ref_spec[_cbins])
                _rcs = float(_ref_chroma.sum())
                if _rcs > 1e-8:
                    _ref_chroma /= _rcs
                    _tc_corr = _safe_pearson(_ref_chroma, chroma)
                    if _tc_corr > 0.90:
                        scores["tonal_center"] = min(1.0, scores["tonal_center"] + (_tc_corr - 0.90) * 1.0)
            except Exception:
                pass
    except Exception:
        scores["tonal_center"] = 0.5

    # ── Natürlichkeit (MFCC-Proxy: spektrale Glattheit) ───────────────
    # Canonical key "natuerlichkeit" — aligned with GoalApplicabilityFilter §2.32.
    try:
        n_mfcc = min(20, len(fft_mag) // 2)
        mfcc_approx = np.log(np.convolve(fft_mag[: len(fft_mag) // 2], np.ones(10) / 10, mode="valid") + 1e-12)
        if len(mfcc_approx) > n_mfcc:
            smoothness = 1.0 - float(np.std(np.diff(mfcc_approx[:n_mfcc]))) / (
                float(np.std(mfcc_approx[:n_mfcc])) + 1e-12
            )
            scores["natuerlichkeit"] = float(np.clip(smoothness, 0.0, 1.0))
        else:
            scores["natuerlichkeit"] = 0.5
        # §9.7.5 Preservation: Log-spectral envelope correlation
        if _ref_fft is not None:
            _fl = min(len(fft_mag), len(_ref_fft))
            if _fl > 20:
                _log_proc = np.log(fft_mag[:_fl] + 1e-12)
                _log_ref = np.log(_ref_fft[:_fl] + 1e-12)
                _r = _safe_pearson(_log_ref, _log_proc)
                if _r > 0.7:
                    scores["natuerlichkeit"] = min(1.0, scores["natuerlichkeit"] + (_r - 0.7) * 0.5)
    except Exception:
        scores["natuerlichkeit"] = 0.5

    # ── Timbre-Authentizität (MFCC-basiert: Pearson auf log-Mel) ──────
    try:
        # Proxy: Spectral Centroid-Stabilität über kurze Fenster
        hop_t = sr // 50  # 20 ms
        centroids = []
        for i in range(0, len(mono) - hop_t, hop_t):
            w = mono[i : i + hop_t]
            w_fft = np.abs(np.fft.rfft(w))
            w_freqs = np.fft.rfftfreq(len(w), d=1.0 / sr)
            centroid = float(np.sum(w_freqs * w_fft) / (np.sum(w_fft) + 1e-12))
            centroids.append(centroid)
        if len(centroids) > 2:
            cv = float(np.std(centroids)) / (float(np.mean(centroids)) + 1e-12)
            # Niedrige CV → stabiles Timbre → hoher Score
            scores["timbre_authentizitaet"] = float(np.clip(1.0 - min(cv, 1.0), 0.0, 1.0))
        else:
            scores["timbre_authentizitaet"] = 0.5
        # §9.7.5 Preservation: Centroid trajectory correlation with reference
        if _ref_mono is not None and len(centroids) > 2:
            _rm_ml = min(len(mono), len(_ref_mono))
            _ref_centroids = []
            for i in range(0, _rm_ml - hop_t, hop_t):
                _rw = _ref_mono[i : i + hop_t]
                _rw_fft = np.abs(np.fft.rfft(_rw))
                _rw_freqs = np.fft.rfftfreq(len(_rw), d=1.0 / sr)
                _ref_centroids.append(float(np.sum(_rw_freqs * _rw_fft) / (np.sum(_rw_fft) + 1e-12)))
            if len(_ref_centroids) > 2:
                _r = _safe_pearson(np.array(_ref_centroids), np.array(centroids[: len(_ref_centroids)]))
                if _r > 0.7:
                    scores["timbre_authentizitaet"] = min(1.0, scores["timbre_authentizitaet"] + (_r - 0.7) * 0.5)
    except Exception:
        scores["timbre_authentizitaet"] = 0.5

    # ── Bass-Kraft (Bassenergie 20–250 Hz) ─────────────────────────────
    try:
        bass_energy = float(np.mean(fft_mag[(freqs >= 20) & (freqs <= 250)] ** 2))
        # Normierung: typische Bassenergie ~2% des Spektrums → 0.02 = Score 1.0
        scores["bass_kraft"] = float(np.clip(bass_energy / (tot_energy * 0.02 + 1e-12), 0.0, 1.0))
        # §9.7.5 Preservation: LF spectral correlation (20-500 Hz)
        if _ref_fft is not None:
            _lf = (freqs[: len(_ref_fft)] >= 20) & (freqs[: len(_ref_fft)] <= 500)
            if np.sum(_lf) > 5:
                _r = _safe_pearson(_ref_fft[_lf], fft_mag[: len(_ref_fft)][_lf])
                if _r > 0.7:
                    scores["bass_kraft"] = min(1.0, scores["bass_kraft"] + (_r - 0.7) * 0.5)
    except Exception:
        scores["bass_kraft"] = 0.5

    # ── Authentizität (Spektrale Konsistenz-Proxy, referenzfrei) ───────
    try:
        # Proxy: Gleichmäßigkeit der Spektralhüllkurve (glatte Hülle = authentisches Signal)
        # Stark deformierte Spektren (Codec-Artefakte, Phasenfehler) zeigen hohe Varianz
        log_mag = np.log(fft_mag + 1e-12)
        # Glättung über 50 Bins
        smooth_len = min(50, len(log_mag) // 4)
        if smooth_len > 1:
            smoothed = np.convolve(log_mag, np.ones(smooth_len) / smooth_len, mode="valid")
            roughness = float(np.std(log_mag[smooth_len // 2 : smooth_len // 2 + len(smoothed)] - smoothed))
            # Niedriger Roughness-Wert → glatte Hülle → hohe Authentizität
            scores["authentizitaet"] = float(np.clip(1.0 - roughness / 3.0, 0.0, 1.0))
        else:
            scores["authentizitaet"] = 0.5
        # §9.7.5 Preservation: Spectral envelope correlation (full-band)
        if _ref_fft is not None:
            _fl = min(len(fft_mag), len(_ref_fft))
            if _fl > 20:
                _r = _safe_pearson(
                    np.log(_ref_fft[:_fl] + 1e-12),
                    np.log(fft_mag[:_fl] + 1e-12),
                )
                if _r > 0.7:
                    scores["authentizitaet"] = min(1.0, scores["authentizitaet"] + (_r - 0.7) * 0.5)
    except Exception:
        scores["authentizitaet"] = 0.5

    # ── Emotionalität (Crest-Factor + RMS-Varianz) ─────────────────────
    try:
        rms_val = float(np.sqrt(np.mean(mono**2) + 1e-12))
        peak_val = float(np.max(np.abs(mono)))
        crest_db = 20.0 * math.log10(peak_val / (rms_val + 1e-12) + 1e-12)
        # 2–14 dB Crestfaktor ist gesunder Dynamikbereich
        crest_score = float(np.clip((crest_db - 2.0) / 12.0, 0.0, 1.0))
        # RMS-Varianz über 10ms-Frames (Ausdruck)
        hop_e = max(1, sr // 100)
        rms_frames = np.array(
            [float(np.sqrt(np.mean(mono[i : i + hop_e] ** 2) + 1e-12)) for i in range(0, len(mono) - hop_e, hop_e)]
        )
        variance_score = float(np.clip(np.var(rms_frames) * 1000.0, 0.0, 1.0)) if len(rms_frames) > 2 else 0.5
        scores["emotionalitaet"] = float(np.clip(0.5 * crest_score + 0.5 * variance_score, 0.0, 1.0))
        # §9.7.5 Preservation: RMS-envelope correlation (dynamics preservation)
        if _ref_mono is not None:
            _rm_ml = min(len(mono), len(_ref_mono))
            _ref_rms = np.array(
                [
                    float(np.sqrt(np.mean(_ref_mono[i : i + hop_e] ** 2) + 1e-12))
                    for i in range(0, _rm_ml - hop_e, hop_e)
                ]
            )
            _proc_rms = np.array(
                [float(np.sqrt(np.mean(mono[i : i + hop_e] ** 2) + 1e-12)) for i in range(0, _rm_ml - hop_e, hop_e)]
            )
            _r = _safe_pearson(_ref_rms, _proc_rms)
            if _r > 0.7:
                scores["emotionalitaet"] = min(1.0, scores["emotionalitaet"] + (_r - 0.7) * 0.5)
    except Exception:
        scores["emotionalitaet"] = 0.5

    # ── Transparenz (Spektrale Rolloff + Energie-Balance) ──────────────
    try:
        # 75%-Rolloff: Frequenz unterhalb derer 75% der Energie konzentriert ist
        cumsum = np.cumsum(fft_mag**2)
        total_e = cumsum[-1] + 1e-12
        rolloff_idx = int(np.searchsorted(cumsum, 0.75 * total_e))
        rolloff_hz = float(freqs[min(rolloff_idx, len(freqs) - 1)])
        # 5500 Hz = 1.0 (gut gemastertes Material), 1500 Hz = 0.0
        rolloff_score = float(np.clip((rolloff_hz - 1500.0) / 4000.0, 0.0, 1.0))
        # Energie-Balance low/mid/high: gleichmäßig = transparent
        e_low = float(np.mean(fft_mag[freqs < 500] ** 2) + 1e-12)
        e_mid = float(np.mean(fft_mag[(freqs >= 500) & (freqs < 2000)] ** 2) + 1e-12)
        e_high = float(np.mean(fft_mag[freqs >= 2000] ** 2) + 1e-12)
        e_total = e_low + e_mid + e_high
        balance_std = float(np.std([e_low / e_total, e_mid / e_total, e_high / e_total]))
        balance_score = float(np.clip(1.0 - balance_std * 3.0, 0.0, 1.0))
        scores["transparenz"] = float(np.clip(0.6 * rolloff_score + 0.4 * balance_score, 0.0, 1.0))
    except Exception:
        scores["transparenz"] = 0.5

    # ── Spatial Depth (M/S-Korrelation bei Stereo, 0.5 bei Mono) ──────
    try:
        if audio.ndim == 2 and audio.shape[1] >= 2:
            left = audio[:, 0].astype(np.float32)
            right = audio[:, 1].astype(np.float32)
            mid = (left + right) * 0.5
            side = (left - right) * 0.5
            mid_e = float(np.mean(mid**2) + 1e-12)
            side_e = float(np.mean(side**2) + 1e-12)
            # Hohe Side-Energie = breites Stereo-Bild = hohe Räumlichkeit
            # Normierung: S/M-Ratio ≥ 0.5 = sehr breites Stereo → Score 1.0
            stereo_ratio = side_e / (mid_e + side_e)
            scores["spatial_depth"] = float(np.clip(stereo_ratio * 2.0, 0.0, 1.0))
        else:
            scores["spatial_depth"] = 0.5  # Mono: neutral (GoalApplicabilityFilter entscheidet)
    except Exception:
        scores["spatial_depth"] = 0.5

    # ── Mikro-Dynamik (LUFS-Profil-Korrelation 400ms Proxy) ──────────
    try:
        # Proxy: RMS-Varianz über 400ms-Fenster (äquivalent zu LUFS-Profil-Korrelation)
        win_400ms = max(1, int(sr * 0.4))
        hop_400ms = win_400ms // 4
        rms_400 = np.array(
            [
                float(np.sqrt(np.mean(mono[i : i + win_400ms] ** 2) + 1e-12))
                for i in range(0, len(mono) - win_400ms, hop_400ms)
            ]
        )
        if len(rms_400) > 2:
            # Gleichmäßige Variation über 400ms-Fenster = gute Mikro-Dynamik
            # (weder totales Limiting noch extreme Spitzen)
            db_profile = 20.0 * np.log10(rms_400 + 1e-12)
            db_range = float(np.max(db_profile) - np.min(db_profile))
            # Gesunder Bereich: 3–18 dB Variation
            scores["micro_dynamics"] = float(np.clip((db_range - 1.0) / 17.0, 0.0, 1.0))
        else:
            scores["micro_dynamics"] = 0.5
    except Exception:
        scores["micro_dynamics"] = 0.5

    # ── Separation-Treue (Spektrale Tonalität als NMF-Proxy) ──────────
    try:
        # Proxy: Spektrale Flachheit (niedrig = tonal = gut separierbar)
        # Rauschen hat hohe Flachheit → schwer zu trennen → niedrige Separation-Treue
        # Tonales Signal: Flachheit ~ 0.01–0.05 → Score nahe 1.0
        # Rauschen: Flachheit ~ 0.3–1.0 → Score nahe 0.0
        eps = 1e-12
        # Geometrisches Mittel / arithmetisches Mittel auf Leistungsspektrum
        power = fft_mag**2 + eps
        geom_mean = float(np.exp(np.mean(np.log(power))))
        arith_mean = float(np.mean(power))
        flatness = float(np.clip(geom_mean / (arith_mean + eps), 0.0, 1.0))
        # Niedriger Flatness → hohe Tonalität → gute Separierbarkeit
        scores["separation_fidelity"] = float(np.clip(1.0 - flatness * 2.5, 0.0, 1.0))
        # §9.7.5 Preservation: Full-band spectral magnitude coherence
        if _ref_fft is not None:
            _fl = min(len(fft_mag), len(_ref_fft))
            if _fl > 20:
                _r = _safe_pearson(_ref_fft[:_fl], fft_mag[:_fl])
                if _r > 0.7:
                    scores["separation_fidelity"] = min(1.0, scores["separation_fidelity"] + (_r - 0.7) * 0.5)
    except Exception:
        scores["separation_fidelity"] = 0.5

    # ── Artikulation (Onset-Schärfe: Transient-Proxy) ─────────────────
    try:
        # Proxy: Varianz der Energiehüllkurve-Ableitungen (scharfe Transienten = hohe Varianz)
        hop_a = max(1, sr // 200)  # 5 ms
        # Vectorized: non-overlapping peak envelope via reshape
        _nf_a = (len(mono) - 1) // hop_a
        env_a = (
            np.max(np.abs(mono[: _nf_a * hop_a].reshape(_nf_a, hop_a)), axis=1)
            if _nf_a > 0
            else np.empty(0, dtype=np.float32)
        )
        if len(env_a) > 4:
            # Erste Ableitung der Hüllkurve
            d_env = np.diff(env_a)
            # Starke positive Sprünge = scharfe Anschläge (Artikulation)
            pos_peaks = d_env[d_env > 0]
            if len(pos_peaks) > 0:
                onset_sharpness = float(np.mean(pos_peaks))
                # Normierung: 0.01 = gute Artikulation → Score 1.0
                scores["artikulation"] = float(np.clip(onset_sharpness / 0.01, 0.0, 1.0))
            else:
                scores["artikulation"] = 0.3  # Keine Transienten = schlechte Artikulation
        else:
            scores["artikulation"] = 0.5
    except Exception:
        scores["artikulation"] = 0.5

    # NaN-guard (§3.1) — all 14 canonical keys including "natuerlichkeit"
    for k in FAST_GOALS_SUBSET:
        if k not in scores or not math.isfinite(scores[k]):
            scores[k] = 0.5

    if precise_override:
        scores = _apply_precise_metric_overrides(scores, audio, sr, reference=reference)

    for k in FAST_GOALS_SUBSET:
        if k not in scores or not math.isfinite(scores[k]):
            scores[k] = 0.5

    return scores


def _extract_sample(audio: np.ndarray, sr: int, duration_s: float = SAMPLE_DURATION_S) -> np.ndarray:
    """Extrahiert repräsentative 5-s-Stichprobe aus der Mitte des Audios."""
    n = len(audio) if audio.ndim == 1 else len(audio)
    sample_len = min(int(duration_s * sr), n)
    if n <= sample_len:
        return audio
    start = (n - sample_len) // 2
    return audio[start : start + sample_len] if audio.ndim == 1 else audio[start : start + sample_len]


# ---------------------------------------------------------------------------
# Hauptklasse
# ---------------------------------------------------------------------------


class PerPhaseMusicalGoalsGate:
    """
    Wraps PhaseInterface.process() mit Musical-Goals-Prüfung.

    Alle Methoden sind thread-sicher und NaN/Inf-sicher.
    """

    def __init__(self) -> None:
        self._rollback_count: int = 0  # Pro Restaurierungsaufruf
        self._user_warned: bool = False  # Nutzer-Warnung einmalig

    def reset(self) -> None:
        """Setzt Zähler für neuen Restaurierungsaufruf zurück."""
        self._rollback_count = 0
        self._user_warned = False

    def wrap_phase(
        self,
        phase: Any,  # PhaseInterface-Instanz
        audio: np.ndarray,
        sr: int,
        scores_before: dict[str, float] | None = None,
        phase_kwargs: dict[str, Any] | None = None,
        restorability_score: float = 70.0,
        applicable_goals: set[str] | None = None,
        initial_strength: float = 1.0,
    ) -> tuple[np.ndarray, dict[str, float], PhaseGateLogEntry]:
        """
        Führt eine Phase aus und prüft Musical-Goals-Regression.

        Args:
            phase: PhaseInterface-Instanz mit process(audio) → PhaseResult
            audio: Input-Audio (float32)
            sr: 48000 Hz
            scores_before: Bekannte Scores vor der Phase (werden gemessen
                           wenn nicht übergeben)
            phase_kwargs: Zusätzliche kwargs für den Phase-Aufruf (z.B. sample_rate, material_type)
            restorability_score: RestorabilityEstimator-Score ∈ [0, 100] — bestimmt
                                 adaptiven REGRESSION_THRESHOLD (§2.29).
            applicable_goals: Aus GoalApplicabilityFilter — nur diese Ziele werden
                              geprüft. None = alle FAST_GOALS_SUBSET-Ziele.
            initial_strength: Material-adaptive Initialstärke ∈ (0, 1.0] (§2.29/§2.31).
                              1.0 = volle Stärke (Default). Niedrigere Werte aus
                              _MATERIAL_PHASE_FACTORS schützen Vintage-Charakter
                              (z.B. 0.25 für phase_22_tape_saturation bei shellac).
                              Retry-Stärken skalieren relativ zur Initialstärke.

        Returns:
            (audio_out, scores_after, log_entry)
        """
        if sr != 48000:
            logger.debug(f"PMGG: SR={sr} (nicht 48000) — Goal-Messung läuft trotzdem")

        if phase_kwargs is None:
            phase_kwargs = {}

        phase_id = self._get_phase_id(phase)
        t0 = time.time()

        # Adaptiven Threshold bestimmen (§2.29)
        threshold = _get_adaptive_threshold(restorability_score)

        # §9.7.3 Phasen-adaptive Sample-Dauer — MUSS vor scores_before bestimmt werden,
        # damit before und after dieselbe Sample-Länge nutzen (sonst falsche Regression).
        _sample_dur = _get_sample_duration(phase_id)

        # Vor-Scores messen (wenn nicht übergeben) — gleiche duration wie after-Messung
        sample_before = _extract_sample(audio, sr, duration_s=_sample_dur)
        if scores_before is None:
            scores_before = _measure_quick(sample_before, sr)

        # Effective goal set: Schnitt aus FAST_GOALS_SUBSET + applicable_goals
        if applicable_goals is not None:
            effective_goals = [g for g in FAST_GOALS_SUBSET if g in applicable_goals]
            if not effective_goals:
                effective_goals = FAST_GOALS_SUBSET  # Fallback: alle
        else:
            effective_goals = FAST_GOALS_SUBSET

        # §9.7.4 Phase-specific goal exclusions (comb-filter-sensitive proxies).
        # Remove goals whose DSP proxy is unreliable for this particular phase type.
        _excluded_goals: set[str] = set()
        for _pfx, _excl in PHASE_GOAL_EXCLUSIONS.items():
            if phase_id.startswith(_pfx):
                _excluded_goals |= _excl
        if _excluded_goals:
            effective_goals = [g for g in effective_goals if g not in _excluded_goals]
            if not effective_goals:
                effective_goals = list(FAST_GOALS_SUBSET)  # Safety fallback
            logger.debug(
                "PMGG: %s goal exclusions applied: %s → %d goals checked",
                phase_id,
                sorted(_excluded_goals),
                len(effective_goals),
            )

        # Phase ausführen + Regression prüfen (§2.29: initial_strength statt immer 1.0)
        audio_out, scores_after, action, strength = self._run_with_retry(
            phase,
            audio,
            sr,
            scores_before,
            phase_id,
            phase_kwargs,
            threshold=threshold,
            effective_goals=effective_goals,
            sample_duration_s=_sample_dur,
            initial_strength=max(0.0, min(1.0, initial_strength)),
        )

        # Best-Effort-Zähler (Phase wurde mit reduzierter Stärke angewendet, nicht übersprungen)
        if action.startswith("best_effort"):
            self._rollback_count += 1
            if self._rollback_count > 3 and not self._user_warned:
                self._user_warned = True
                logger.warning(
                    "ℹ️ Einige Verarbeitungsschritte wurden mit reduzierter Stärke angewendet, um den Klang zu schützen."
                )

        goal_regressions = {
            g: scores_after.get(g, 0.5) - scores_before.get(g, 0.5)
            for g in effective_goals
            if scores_after.get(g, 0.5) - scores_before.get(g, 0.5) < -threshold
        }

        log_entry = PhaseGateLogEntry(
            phase_id=phase_id,
            action=action,
            goal_regressions=goal_regressions,
            strength_used=strength,
        )

        elapsed = time.time() - t0
        logger.debug(
            "PMGG: %s → %s (%.0f ms, strength=%.2f)",
            phase_id,
            action,
            elapsed * 1000,
            strength,
        )

        return audio_out, scores_after, log_entry

    # ------------------------------------------------------------------
    # Interne Methoden
    # ------------------------------------------------------------------

    def _run_with_retry(
        self,
        phase: Any,
        audio: np.ndarray,
        sr: int,
        scores_before: dict[str, float],
        phase_id: str,
        phase_kwargs: dict[str, Any] | None = None,
        *,
        threshold: float = REGRESSION_THRESHOLD_GOOD,
        effective_goals: list | None = None,
        sample_duration_s: float = SAMPLE_DURATION_S,  # §9.7.3 phasen-adaptiv
        initial_strength: float = 1.0,
    ) -> tuple[np.ndarray, dict[str, float], str, float]:
        """
        Führt Phase aus, ggf. mit Retry bei Regression.

        Args:
            threshold: Adaptiver REGRESSION_THRESHOLD (§2.29).
            effective_goals: Subset aus FAST_GOALS_SUBSET, das geprüft wird.
            sample_duration_s: Stichprobenlänge (§9.7.3 phasen-adaptiv, 1.0–5.0 s).
            initial_strength: Material-adaptive Initialstärke ∈ (0, 1.0] (§2.31).
                1.0 = Default. Retry-Stärken skalieren relativ dazu wenn < 1.0.

        Returns:
            (audio_out, scores_after, action_label, strength_used)
        """
        if phase_kwargs is None:
            phase_kwargs = {}
        if effective_goals is None:
            effective_goals = FAST_GOALS_SUBSET
        initial_strength = max(0.01, min(1.0, initial_strength))

        # §2.29a ML-Inference-Caching: ML-deterministische Phasen werden nur
        # einmal mit strength=1.0 ausgeführt.  Retries variieren Wet/Dry-Blending.
        # Strength-abhängige DSP-Phasen müssen bei jedem Retry neu ausgeführt
        # werden, da strength dort Algorithmus-Parameter steuert (z.B. Filterfrequenz,
        # Kompressionsratio), nicht nur das Mischverhältnis.
        _is_ml_deterministic = phase_id.startswith(tuple(_ML_DETERMINISTIC_PHASES))
        # §2.29a Sonderfall phase_20: SGMSE+ (ML) ist deterministisch, aber WPE-DSP-Fallback
        # verwendet strength*0.90 als algorithmus-internen Prädiktor-Parameter → must re-run.
        # Zur Laufzeit: nur wenn SGMSE+ im ML-Budget alloziert ist, ML-Pfad verwenden.
        if _is_ml_deterministic and phase_id.startswith("phase_20"):
            _is_ml_deterministic = _phase20_is_ml_active()

        # §9.7.5 Referenz-Stichprobe für preservation-aware Messung.
        # Einmal berechnen, für alle scores_after/scores_retry wiederverwenden.
        _ref_sample = _extract_sample(audio, sr, duration_s=sample_duration_s)

        if _is_ml_deterministic:
            # ML-Pfad: Einmalige Inferenz mit strength=1.0, Wet/Dry für Stärke
            audio_full = self._run_phase(phase, audio, 1.0, phase_kwargs)
            if initial_strength < 1.0:
                audio_out = self._wet_dry_blend(audio, audio_full, initial_strength, phase)
            else:
                audio_out = audio_full
        else:
            # DSP-Pfad: Direkte Ausführung mit material-adaptiver Stärke
            audio_out = self._run_phase(phase, audio, initial_strength, phase_kwargs)
            audio_full = None  # kein Cache benötigt

        scores_after = _measure_quick(
            _extract_sample(audio_out, sr, duration_s=sample_duration_s), sr, reference=_ref_sample
        )

        regression = self._max_regression(scores_before, scores_after, effective_goals)
        if regression <= threshold:
            return audio_out, scores_after, "passed", initial_strength

        # §2.29 v9.10.77: Priority-aware regression check.
        # Determine worst priority among regressed goals to set retry budget.
        _reg_pa, _worst_prio = self._max_regression_priority_aware(
            scores_before, scores_after, effective_goals, threshold
        )

        # Log which goal caused the regression (diagnostics for false-positive detection)
        _worst_goal = max(
            effective_goals,
            key=lambda g: max(0.0, scores_before.get(g, 0.5) - scores_after.get(g, 0.5)),
        )
        logger.debug(
            "PMGG: %s regression=%.4f > threshold=%.3f — worst goal: %s (P%d, before=%.3f after=%.3f)",
            phase_id,
            regression,
            threshold,
            _worst_goal,
            _worst_prio,
            scores_before.get(_worst_goal, 0.5),
            scores_after.get(_worst_goal, 0.5),
        )

        # §2.29 v9.10.77: If ONLY P4/P5 goals regressed (priority-adjusted threshold
        # not exceeded), skip retries entirely — these are best-effort goals.
        if _worst_prio >= 4:
            logger.info(
                "PMGG: %s regression only in P%d goals (%s) — no retry (best-effort priority)",
                phase_id,
                _worst_prio,
                _worst_goal,
            )
            log_action = "passed_p4p5_tolerated"
            return audio_out, scores_after, log_action, initial_strength

        # Priority-based max retries (§2.29 v9.10.77):
        _max_retries_for_prio = _PRIORITY_MAX_RETRIES.get(_worst_prio, 4)

        # Retry-Stärken relativ zur Initialstärke skalieren (§2.29):
        # initial_strength=1.0 → normale Retry-Folge [0.65, 0.50, ...]
        # initial_strength<1.0 → proportional nach unten skaliert
        retry_strengths = [s * initial_strength for s in _RETRY_STRENGTHS[:_max_retries_for_prio]]

        # §2.29 Best-Effort-Tracking: Speichere den Versuch mit geringster Regression.
        # PMGG darf Phasen NICHT überspringen — CausalDefectReasoner hat die Phase
        # als notwendig bestimmt. Stattdessen wird der beste Versuch verwendet.
        best_audio = audio_out
        best_scores = scores_after
        best_regression = regression
        best_strength = initial_strength
        best_action = "best_effort"

        # §2.29a Fix: ML-deterministische Timing-Phasen (phase_12, phase_31)
        # können NICHT per Wet/Dry retried werden, da Timing-Phasen kein Blending
        # erlauben (Phasen-Artefakte bei Crossfade zeitversetzter Signale).
        # Alle Retries würden identisches Audio produzieren → sofort Best-Effort.
        _TIMING_PHASES = frozenset(
            {
                "phase_12_wow_flutter_fix",
                "phase_31_speed_pitch_correction",
            }
        )
        if _is_ml_deterministic and phase_id in _TIMING_PHASES:
            logger.info(
                "PMGG: %s is ML-deterministic timing phase — Wet/Dry retries not applicable, "
                "using best-effort (regression=%.4f > threshold=%.3f)",
                phase_id,
                regression,
                threshold,
            )
            return best_audio, best_scores, "best_effort", initial_strength

        # Retry-Schleife
        # ML-deterministische Phasen: Wet/Dry-Reblend des gecachten audio_full
        #   (spart ~60 s pro Retry bei OMLSA + ResembleEnhance etc.)
        # DSP-Phasen: Erneuter process()-Aufruf mit geändertem strength
        #   (nichtlineare DSP-Operationen: wet/dry ≠ Neuberechnung)
        _prev_regression = regression
        _retry_t0 = time.time()
        _RETRY_BUDGET_S = 300.0  # Max 5 min für alle Retries einer Phase
        for attempt, strength in enumerate(retry_strengths):
            _retry_elapsed = time.time() - _retry_t0
            if _retry_elapsed > _RETRY_BUDGET_S:
                logger.info(
                    "PMGG: %s retry time budget exceeded (%.0fs > %.0fs) — "
                    "using best attempt so far (regression=%.4f, attempt=%d)",
                    phase_id,
                    _retry_elapsed,
                    _RETRY_BUDGET_S,
                    best_regression,
                    attempt,
                )
                break

            import gc

            gc.collect()

            action_label = f"retry{attempt + 1}"

            if _is_ml_deterministic:
                # §2.29a: Wet/Dry-Reblend — keine erneute ML-Inferenz
                logger.debug(
                    "PMGG: %s Retry %d mit strength=%.2f (Wet/Dry-Reblend, keine Re-Inferenz)",
                    phase_id,
                    attempt + 1,
                    strength,
                )
                audio_retry = self._wet_dry_blend(audio, audio_full, strength, phase)
            else:
                # DSP-Phase: Neu ausführen mit reduziertem strength
                logger.debug(
                    "PMGG: %s Retry %d mit strength=%.2f (DSP Re-Run)",
                    phase_id,
                    attempt + 1,
                    strength,
                )
                audio_retry = self._run_phase(phase, audio, strength, phase_kwargs)

            _retry_sample = _extract_sample(audio_retry, sr, duration_s=sample_duration_s)
            scores_retry = _measure_quick(_retry_sample, sr, reference=_ref_sample, precise_override=False)
            regression_retry = self._max_regression(scores_before, scores_retry, effective_goals)
            if regression_retry <= threshold:
                # Apply precise overrides once for accurate score propagation to next phase
                scores_retry = _apply_precise_metric_overrides(scores_retry, _retry_sample, sr, reference=_ref_sample)
                return audio_retry, scores_retry, action_label, strength
            # Track best attempt (lowest regression)
            if regression_retry < best_regression:
                best_audio = audio_retry
                best_scores = scores_retry
                best_regression = regression_retry
                best_strength = strength
                best_action = f"best_effort_r{attempt + 1}"

            # Stagnation guard: if regression barely changes across consecutive
            # retries despite strength variation, further retries are wasted.
            if abs(regression_retry - _prev_regression) < 0.005 and attempt >= 1:
                logger.info(
                    "PMGG: %s stagnation detected at retry %d (Δregression=%.6f) — skipping remaining retries",
                    phase_id,
                    attempt + 1,
                    abs(regression_retry - _prev_regression),
                )
                break
            _prev_regression = regression_retry

        # §2.29 catastrophic-regression safety net (P1/P2 only, v9.10.77):
        # When best_regression > 0.20 after all regular retries, extend with
        # ultra-low strengths.  This is NOT a rollback — processing is still
        # applied, just at near-transparent level.  Spec-compliant.
        # Only for P1/P2 regressions — P3 at this point already used max 2 retries.
        _CATASTROPHIC_THRESHOLD = 0.20
        _EMERGENCY_STRENGTHS = [0.15 * initial_strength, 0.10 * initial_strength]
        if best_regression > _CATASTROPHIC_THRESHOLD and _worst_prio <= 2:
            logger.warning(
                "PMGG: %s catastrophic regression %.4f > %.2f — attempting emergency low-strength retries",
                phase_id,
                best_regression,
                _CATASTROPHIC_THRESHOLD,
            )
            for _em_strength in _EMERGENCY_STRENGTHS:
                _retry_elapsed = time.time() - _retry_t0
                if _retry_elapsed > _RETRY_BUDGET_S:
                    break
                if _is_ml_deterministic:
                    audio_em = self._wet_dry_blend(
                        audio, audio_full if audio_full is not None else best_audio, _em_strength, phase
                    )
                else:
                    audio_em = self._run_phase(phase, audio, _em_strength, phase_kwargs)
                _em_sample = _extract_sample(audio_em, sr, duration_s=sample_duration_s)
                scores_em = _measure_quick(_em_sample, sr, reference=_ref_sample, precise_override=False)
                regression_em = self._max_regression(scores_before, scores_em, effective_goals)
                if regression_em <= threshold:
                    if audio_full is not None:
                        del audio_full
                    scores_em = _apply_precise_metric_overrides(scores_em, _em_sample, sr, reference=_ref_sample)
                    return audio_em, scores_em, f"emergency_s{_em_strength:.2f}", _em_strength
                if regression_em < best_regression:
                    best_audio = audio_em
                    best_scores = scores_em
                    best_regression = regression_em
                    best_strength = _em_strength
                    best_action = "best_effort_emergency"

        # §2.29 KEIN Rollback — Phase wird mit geringster Regression angewendet.
        # VERBOTEN: Phase überspringen (Original-Audio zurückgeben).
        # CausalDefectReasoner hat diese Phase als notwendig bestimmt.
        # Sofortige Freigabe: audio_full (+86 MB bei 225s) nicht bis GC halten.
        if audio_full is not None:
            del audio_full
        # Apply precise overrides once for accurate score propagation to next phase
        _best_sample = _extract_sample(best_audio, sr, duration_s=sample_duration_s)
        best_scores = _apply_precise_metric_overrides(best_scores, _best_sample, sr, reference=_ref_sample)
        logger.warning(
            "⚠️ PMGG: %s best-effort (strength=%.2f, Regression=%.4f > threshold=%.3f) — "
            "Phase wird trotzdem angewendet (kein Rollback/Skip erlaubt)",
            phase_id,
            best_strength,
            best_regression,
            threshold,
        )
        return best_audio, best_scores, best_action, best_strength

    @staticmethod
    def _run_phase(
        phase: Any,
        audio: np.ndarray,
        strength: float,
        phase_kwargs: dict[str, Any] | None = None,
    ) -> np.ndarray:
        """Führt Phase aus mit Wet/Dry-Modulation; gibt bei Fehler das Original zurück.

        CRITICAL FIX (v9.10.64): Ruft phase.process() statt phase() auf.
        PhaseInterface definiert kein __call__; der vorherige Code erzeugte
        TypeError, das still gefangen wurde — ALLE Phasen waren No-Ops.

        Wet/Dry-Modulation (§MusikalischeHarmonisierung):
        strength < 1.0 → audio_out = audio + strength × (processed - audio)
        Psychoakustisch korrekt: Sanftere Verarbeitung bei niedriger Stärke,
        statt binär „alles oder nichts".
        Timing-modifizierende Phasen (wow/flutter, speed) sind von Wet/Dry
        ausgenommen (Phasen-Artefakte bei Crossfade zeitversetzter Signale).
        """
        if phase_kwargs is None:
            phase_kwargs = {}
        # Timing-modifizierende Phasen: kein Wet/Dry (Phasen-Artefakte)
        _TIMING_PHASES = frozenset(
            {
                "phase_12_wow_flutter_fix",
                "phase_31_speed_pitch_correction",
            }
        )
        try:
            # Strength als Kwarg übergeben, damit Phasen ihn OPTIONAL nutzen können
            kw = dict(phase_kwargs)
            kw["strength"] = strength
            # CRITICAL: phase.process() statt phase() — PhaseInterface hat kein __call__
            result = phase.process(audio, **kw)
            if hasattr(result, "audio"):
                out = result.audio
            elif hasattr(result, "processed_audio"):
                out = result.processed_audio
            elif isinstance(result, np.ndarray):
                out = result
            else:
                return audio

            if out is None or not isinstance(out, np.ndarray):
                return audio

            out = np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)
            out = np.clip(out, -1.0, 1.0).astype(np.float32)

            # Länge sicherstellen
            if len(out) != len(audio):
                out = out[: len(audio)] if len(out) > len(audio) else np.pad(out, (0, len(audio) - len(out)))

            # Wet/Dry-Modulation: strength < 1.0 → blende zwischen Original und Verarbeitet
            if 0.0 < strength < 1.0:
                phase_id = ""
                try:
                    meta = phase.get_metadata()
                    phase_id = getattr(meta, "phase_id", "")
                except Exception as _meta_exc:
                    logger.debug("PMGG: Phase-Metadata-Zugriff fehlgeschlagen: %s", _meta_exc)
                if phase_id not in _TIMING_PHASES:
                    out = (audio + strength * (out - audio)).astype(np.float32)
                    out = np.clip(out, -1.0, 1.0)

            return out
        except Exception as exc:
            logger.debug("PMGG: Phase-Ausführung fehlgeschlagen: %s", exc)
            return audio

    @staticmethod
    def _wet_dry_blend(
        dry: np.ndarray,
        wet: np.ndarray,
        strength: float,
        phase: Any = None,
    ) -> np.ndarray:
        """Wet/Dry-Blending zwischen Original (dry) und verarbeitetem Audio (wet).

        Mathematisch: out = dry + strength × (wet − dry)
        Bei strength=1.0 → wet, bei strength=0.0 → dry.

        Timing-modifizierende Phasen (wow/flutter, speed) sind ausgenommen,
        da Crossfade zeitversetzter Signale Phasen-Artefakte erzeugt.
        """
        _TIMING_PHASES = frozenset(
            {
                "phase_12_wow_flutter_fix",
                "phase_31_speed_pitch_correction",
            }
        )
        # Länge sicherstellen
        if len(wet) != len(dry):
            wet = wet[: len(dry)] if len(wet) > len(dry) else np.pad(wet, (0, len(dry) - len(wet)))
        if strength >= 1.0:
            return np.clip(wet, -1.0, 1.0).astype(np.float32)
        if strength <= 0.0:
            return dry.copy()
        # Timing-Phasen: kein Blend
        phase_id = ""
        if phase is not None:
            try:
                meta = phase.get_metadata()
                phase_id = getattr(meta, "phase_id", "")
            except Exception as _meta_exc:
                logger.debug("PMGG: Wet/Dry-Blend Phase-Metadata-Zugriff fehlgeschlagen: %s", _meta_exc)
        if phase_id in _TIMING_PHASES:
            return np.clip(wet, -1.0, 1.0).astype(np.float32)
        out = (dry + strength * (wet - dry)).astype(np.float32)
        return np.clip(out, -1.0, 1.0)

    @staticmethod
    def _max_regression(
        before: dict[str, float],
        after: dict[str, float],
        goals: list | None = None,
    ) -> float:
        """Maximale negative Differenz in Musical Goals (positiv = Regression)."""
        check_goals = goals if goals is not None else FAST_GOALS_SUBSET
        max_reg = 0.0
        for g in check_goals:
            delta = after.get(g, 0.5) - before.get(g, 0.5)
            if delta < 0:
                max_reg = max(max_reg, -delta)
        return max_reg

    @staticmethod
    def _max_regression_priority_aware(
        before: dict[str, float],
        after: dict[str, float],
        goals: list | None = None,
        threshold: float = 0.020,
    ) -> tuple[float, int]:
        """Priority-aware regression: returns (max_regression, worst_priority).

        Only considers goals whose priority-adjusted threshold is exceeded.
        Returns the highest priority level (lowest number) among regressed goals.

        Args:
            before: Scores before phase.
            after: Scores after phase.
            goals: Subset of goals to check.
            threshold: Base regression threshold.

        Returns:
            (max_regression_value, worst_priority) where worst_priority is 1–5
            (1 = most critical). Returns (0.0, 99) if no regression detected.
        """
        from backend.core.goal_priority_protocol import get_goal_priority_protocol

        gpp = get_goal_priority_protocol()
        check_goals = goals if goals is not None else FAST_GOALS_SUBSET
        max_reg = 0.0
        worst_prio = 99
        for g in check_goals:
            delta = after.get(g, 0.5) - before.get(g, 0.5)
            if delta < 0:
                reg = -delta
                prio = gpp.priority_of(g)
                prio_threshold = threshold * _PRIORITY_THRESHOLD_FACTOR.get(prio, 1.0)
                if reg > prio_threshold:
                    if prio < worst_prio:
                        worst_prio = prio
                    max_reg = max(max_reg, reg)
        return max_reg, worst_prio

    @staticmethod
    def _get_phase_id(phase: Any) -> str:
        """Extrahiert Phase-ID aus MetaDaten oder Klassennamen."""
        try:
            meta = phase.get_metadata()
            return getattr(meta, "phase_id", type(phase).__name__)
        except Exception:
            return type(phase).__name__


# ---------------------------------------------------------------------------
# Convenience-Funktion
# ---------------------------------------------------------------------------


def wrap_phase(
    phase: Any,
    audio: np.ndarray,
    sr: int,
    scores_before: dict[str, float] | None = None,
    restorability_score: float = 70.0,
    applicable_goals: set[str] | None = None,
) -> tuple[np.ndarray, dict[str, float], PhaseGateLogEntry]:
    """
    Convenience-Wrapper: Führt eine Phase aus mit Musical-Goals-Schutz.

    Args:
        phase: PhaseInterface-Instanz
        audio: Input-Audio (float32, 48 kHz)
        sr: 48000 Hz
        scores_before: Vorherige Goal-Scores (optional)
        restorability_score: RestorabilityEstimator-Score ∈ [0, 100], bestimmt
                             adaptiven REGRESSION_THRESHOLD (§2.29).
        applicable_goals: Aus GoalApplicabilityFilter — nur diese Ziele geprüft.

    Returns:
        (audio_out, scores_after, log_entry)
    """
    return get_phase_gate().wrap_phase(
        phase,
        audio,
        sr,
        scores_before,
        restorability_score=restorability_score,
        applicable_goals=applicable_goals,
    )
