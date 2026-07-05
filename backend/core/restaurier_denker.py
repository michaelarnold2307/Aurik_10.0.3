"""
RestaurierDenker — Zentrale Entscheidungs-Intelligenz §v10.6

Der Denker ist der Schiedsrichter zwischen Guard und Phase.
Er trifft DIE EINE Entscheidung nach jeder Phase — nicht fünf
unabhängige Module mit potenziell widerspruechlichen Urteilen.

ARCHITEKTUR:
  ┌─────────────────────────────────────────────────────┐
  │                 RESTAURIER-DENKER                    │
  │                                                     │
  │  Input: PhaseResult + PMGG-Scores + Pipeline-Context │
  │                                                     │
  │  ┌──────────────┐  ┌──────────────┐  ┌───────────┐  │
  │  │ MediaDefect  │  │ Provenance   │  │ Guard     │  │
  │  │ Verifier     │  │ Tracker      │  │ Auditor   │  │
  │  │ (v10.3)      │  │ (v10.4)      │  │ (v10.5)   │  │
  │  └──────┬───────┘  └──────┬───────┘  └─────┬─────┘  │
  │         │                 │                 │        │
  │         └─────────┬───────┴─────────┬───────┘        │
  │                   │                 │                │
  │              ┌────▼─────────────────▼────┐           │
  │              │   DENKER.DECIDE()         │           │
  │              │   - Regression check      │           │
  │              │   - Proxy alternative     │           │
  │              │   - Undo detection        │           │
  │              │   - Paralysis audit       │           │
  │              │   - Mode-aware threshold  │           │
  │              │   - Retry strategy        │           │
  │              └────────────┬──────────────┘           │
  │                           │                          │
  │              Decision: CONTINUE | RETRY | SKIP |     │
  │                         OVERRIDE_GUARD | ROLLBACK    │
  └─────────────────────────────────────────────────────┘

ENTSCHEIDUNGS-HIERARCHIE:
  1. Content Integrity (catastrophic loss → ROLLBACK)
  2. Undo Detection (Provenance: Phase N zerstört Phase M's Arbeit → RETRY)
  3. Paralysis Check (Guard-Auditor: false positive → OVERRIDE_GUARD)
  4. Proxy Alternative (MediaDefectVerifier: PMGG-Fehler korrigieren)
  5. Mode-Adaptive Steering (Restoration konservativ, Studio aggressiv)
  6. Standard Regression (PMGG threshold check)

Author: Aurik v10.6 Development
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────
# Decision Types
# ─────────────────────────────────────────────────────────────────

class DecisionVerdict(str, Enum):
    """Endgültiges Urteil des Denkers über eine Phase."""

    CONTINUE = "continue"               # Phase-Ergebnis akzeptieren, weitermachen
    RETRY_LIGHTER = "retry_lighter"     # Gleiche Phase, reduzierte Intensität
    RETRY_DIFFERENT = "retry_different" # Anderen Ansatz/Plugin versuchen
    OVERRIDE_GUARD = "override_guard"   # Guard ist false-positive → volle Strength
    SKIP = "skip"                       # Phase überspringen (würde nur schaden)
    ROLLBACK = "rollback"               # Zurück zum besten bekannten Zustand
    STOP_GRACEFUL = "stop_graceful"     # Keine Verbesserung mehr möglich


class RetryStrategy(str, Enum):
    """Wie soll retried werden?"""

    REDUCE_INTENSITY = "reduce_intensity"     # Strength × 0.65, 0.40, 0.25...
    SWITCH_PLUGIN = "switch_plugin"            # Anderes Plugin/Algorithmus
    BYPASS_GUARD = "bypass_guard"              # Guard deaktivieren, volle Strength
    ADAPTIVE = "adaptive"                      # Denker wählt basierend auf Kontext


@dataclass
class DenkerContext:
    """Vollständiger Kontext für eine Denker-Entscheidung."""

    phase_id: str
    mode: str = "restoration"                    # "restoration" | "studio_2026"
    restorability: float = 70.0                  # 0-100
    initial_strength: float = 1.0
    current_strength: float = 1.0
    retry_count: int = 0
    total_phases_run: int = 0
    best_effort_count: int = 0

    # Scores
    scores_before: dict[str, float] = field(default_factory=dict)
    scores_after: dict[str, float] = field(default_factory=dict)
    effective_goals: list[str] = field(default_factory=list)
    regression: float = 0.0
    regression_goal: str = ""

    # Audio (für Deep-Checks)
    audio_before: np.ndarray | None = None
    audio_after: np.ndarray | None = None
    sr: int = 48000


@dataclass
class Decision:
    """DIE EINE Entscheidung des Denkers. Keine weiteren Module nötig."""

    verdict: DecisionVerdict
    reason: str = ""
    recommended_strength: float = 1.0
    retry_strategy: RetryStrategy = RetryStrategy.REDUCE_INTENSITY
    override_goals: list[str] = field(default_factory=list)  # Goals deren Guard disabled wird

    # Diagnostik
    proxy_alternative_used: bool = False
    undo_detected: bool = False
    paralysis_detected: bool = False
    false_positive_corrected: bool = False
    mode_adjusted: bool = False

    # Metadaten
    details: dict[str, Any] = field(default_factory=dict)


class RestaurierDenker:
    """§v10.6 Zentrale Entscheidungs-Intelligenz.

    Singleton. Eine Instanz pro Pipeline-Durchlauf.
    Ersetzt die verteilten Entscheidungen von PMGG, MediaDefectVerifier,
    ProvenanceTracker, GuardAuditor und steer_pipeline durch EINE
    koordinierte Entscheidung.

    Usage:
        denker = get_restaurier_denker()
        denker.start_session(mode="restoration", restorability=70)

        for phase in phases:
            result = run_phase(phase)
            scores = measure_goals(result)
            decision = denker.decide(phase_id, scores_before, scores_after, ...)
            if decision.verdict == DecisionVerdict.CONTINUE:
                break  # Phase erfolgreich
            elif decision.verdict == DecisionVerdict.RETRY_LIGHTER:
                strength *= 0.65  # und erneut
            # ...
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._mode: str = "restoration"
        self._restorability: float = 70.0
        self._session_active: bool = False
        self._phase_count: int = 0
        self._best_effort_count: int = 0
        self._decision_history: list[Decision] = []

    # ── Session ──

    def start_session(
        self,
        mode: str = "restoration",
        restorability: float = 70.0,
        sr: int = 48000,
    ) -> None:
        """Initialisiert eine neue Denker-Session."""
        with self._lock:
            self._mode = mode
            self._restorability = restorability
            self._session_active = True
            self._phase_count = 0
            self._best_effort_count = 0
            self._decision_history.clear()

    def end_session(self) -> dict[str, Any]:
        """Beendet die Session und gibt eine Zusammenfassung."""
        with self._lock:
            self._session_active = False
            decisions = [d.verdict.value for d in self._decision_history]
            return {
                "total_phases": self._phase_count,
                "mode": self._mode,
                "restorability": self._restorability,
                "best_effort_count": self._best_effort_count,
                "decision_summary": {
                    "continue": decisions.count("continue"),
                    "retry_lighter": decisions.count("retry_lighter"),
                    "retry_different": decisions.count("retry_different"),
                    "override_guard": decisions.count("override_guard"),
                    "skip": decisions.count("skip"),
                    "rollback": decisions.count("rollback"),
                    "stop_graceful": decisions.count("stop_graceful"),
                },
            }

    # ── Decide ──

    def decide(self, ctx: DenkerContext) -> Decision:
        """§v10.6 DIE EINE zentrale Entscheidung.

        Wird nach JEDER Phase aufgerufen. Ersetzt alle verteilten Checks.

        Entscheidungs-Hierarchie:
          1. Content Integrity (catastrophic → ROLLBACK)
          2. Undo Detection (Provenance)
          3. Paralysis Check (Guard-Auditor)
          4. Proxy Alternative (MediaDefectVerifier)
          5. Mode-Adaptive Steering
          6. Standard Regression

        Args:
            ctx: Vollständiger DenkerContext

        Returns:
            Decision mit Verdict, Reason, empfohlener Strength, Strategie
        """
        with self._lock:
            self._phase_count += 1

            # ── Ebene 0: Mode-adjustierte Schwellwerte ──
            is_studio = "studio" in self._mode.lower() or "2026" in self._mode.lower()
            thresholds = self._get_mode_thresholds(is_studio)

            # ── Ebene 1: Content Integrity (katastrophaler Verlust) ──
            ci_decision = self._check_content_integrity(ctx)
            if ci_decision:
                self._record(ci_decision)
                return ci_decision

            # ── Ebene 2: Undo Detection (Provenance Tracker) ──
            undo_decision = self._check_undo_provenance(ctx)
            if undo_decision:
                self._record(undo_decision)
                return undo_decision

            # ── Ebene 3: Paralysis Check (Guard-Auditor) ──
            paralysis_decision = self._check_paralysis(ctx)
            if paralysis_decision:
                self._record(paralysis_decision)
                return paralysis_decision

            # ── Ebene 4: Proxy-Alternative (MediaDefectVerifier) ──
            proxy_regression = ctx.regression
            if ctx.regression > thresholds["proxy_check_min"]:
                alt_reg = self._get_alternative_regression(ctx)
                if alt_reg is not None and alt_reg < ctx.regression * 0.5:
                    proxy_regression = alt_reg
                    decision = self._decide_on_regression(
                        proxy_regression, ctx, thresholds, is_studio
                    )
                    decision.false_positive_corrected = True
                    decision.proxy_alternative_used = True
                    decision.details["original_regression"] = ctx.regression
                    decision.details["alternative_regression"] = alt_reg
                    self._record(decision)
                    return decision

            # ── Ebene 5: Mode-Adaptive Steering ──
            decision = self._decide_on_regression(
                proxy_regression, ctx, thresholds, is_studio
            )
            decision.mode_adjusted = True
            decision.details["regression"] = proxy_regression
            decision.details["threshold_used"] = (
                thresholds["retry_light"] if is_studio else thresholds["retry_light"]
            )

            # ── Ebene 6: Standard Regression (PMGG) ──
            self._record(decision)
            return decision

    # ── Decision Helpers ──

    def _get_mode_thresholds(self, is_studio: bool) -> dict[str, float]:
        """Mode-adjustierte Schwellwerte."""
        if is_studio:
            return {
                "retry_light": 0.060,       # HPE-Drop für RETRY_LIGHTER
                "retry_heavy": 0.100,       # HPE-Drop für SKIP/ROLLBACK
                "continue_up": 0.025,       # HPE-Verbesserung für CONTINUE
                "proxy_check_min": 0.015,   # Regression ab wann Proxy-Check
                "max_drops": 3,             # Max erlaubte Drops vor ROLLBACK
                "paralysis_strength": 0.30, # Strength unterhalb = Paralysis
            }
        return {
            "retry_light": 0.020,
            "retry_heavy": 0.040,
            "continue_up": 0.010,
            "proxy_check_min": 0.010,
            "max_drops": 2,
            "paralysis_strength": 0.20,
        }

    def _check_content_integrity(self, ctx: DenkerContext) -> Decision | None:
        """Prüft auf katastrophalen Content-Verlust."""
        # RMS-Drop > 12 dB = katastrophal
        if ctx.audio_before is not None and ctx.audio_after is not None:
            rms_before = float(np.sqrt(np.mean(ctx.audio_before.ravel() ** 2)) + 1e-10)
            rms_after = float(np.sqrt(np.mean(ctx.audio_after.ravel() ** 2)) + 1e-10)
            rms_drop_db = 20 * np.log10(rms_before / rms_after if rms_after > 1e-10 else 1.0)
            if rms_drop_db > 12:
                return Decision(
                    verdict=DecisionVerdict.ROLLBACK,
                    reason=f"Katastrophaler Content-Verlust: RMS-Drop={rms_drop_db:.1f} dB",
                    recommended_strength=0.0,
                )
        return None

    def _check_undo_provenance(self, ctx: DenkerContext) -> Decision | None:
        """Prüft Provenance-Tracker auf Undo-Ereignisse."""
        try:
            from backend.core.pipeline_provenance_tracker import get_provenance_tracker

            pt = get_provenance_tracker()
            # Der Tracker wurde bereits vom PMGG gefüttert — nur abfragen
            conflicts = pt.get_conflict_phases()
            if conflicts:
                # Prüfe ob aktuelle Phase ein Undo verursacht hat
                for conf in conflicts[:3]:
                    if conf.get("undoing_phase") == ctx.phase_id.split("_")[0]:
                        return Decision(
                            verdict=DecisionVerdict.RETRY_LIGHTER,
                            reason=f"Undo erkannt: {ctx.phase_id} hat "
                                   f"{conf['original_contributor']}'s Arbeit an "
                                   f"{conf.get('goal', '?')} rückgängig gemacht",
                            recommended_strength=ctx.current_strength * 0.5,
                            undo_detected=True,
                            details={"conflict": conf},
                        )
        except Exception:
            pass
        return None

    def _check_paralysis(self, ctx: DenkerContext) -> Decision | None:
        """Prüft Guard-Auditor auf Paralysis-Ereignisse."""
        if ctx.current_strength < 0.25 and ctx.retry_count >= 3:
            # Mögliche Paralysis — prüfe ob false positive
            try:
                from backend.core.cassette_defect_verifier import (
                    compute_phase_proxy_for_pmgg as _cv_proxy,
                )

                if ctx.audio_before is not None and ctx.audio_after is not None:
                    alt_scores = _cv_proxy(
                        ctx.phase_id, ctx.audio_before, ctx.audio_after, ctx.sr
                    )
                    alt_regression = 0.0
                    for g in ctx.effective_goals:
                        b = ctx.scores_before.get(g, 0.5)
                        a = alt_scores.get(g, ctx.scores_after.get(g, 0.5))
                        if a < b:
                            alt_regression = max(alt_regression, b - a)

                    if alt_regression < ctx.regression * 0.5:
                        # False positive bestätigt → Guard override!
                        self._best_effort_count += 1
                        return Decision(
                            verdict=DecisionVerdict.OVERRIDE_GUARD,
                            reason=f"Guard-Paralysis bei {ctx.current_strength:.0%}: "
                                   f"PMGG Δ={ctx.regression:.3f} → Alternativ Δ={alt_regression:.3f} "
                                   f"(false positive). Re-run mit voller Strength.",
                            recommended_strength=1.0,
                            retry_strategy=RetryStrategy.BYPASS_GUARD,
                            paralysis_detected=True,
                            override_goals=list(ctx.effective_goals),
                            details={
                                "paralyzed_strength": ctx.current_strength,
                                "original_regression": ctx.regression,
                                "alternative_regression": alt_regression,
                            },
                        )
            except Exception:
                pass
        return None

    def _get_alternative_regression(self, ctx: DenkerContext) -> float | None:
        """Berechnet alternative Regression via MediaDefectVerifier."""
        try:
            from backend.core.cassette_defect_verifier import (
                compute_phase_proxy_for_pmgg as _cv_proxy,
            )

            if ctx.audio_before is not None and ctx.audio_after is not None:
                alt_scores = _cv_proxy(
                    ctx.phase_id, ctx.audio_before, ctx.audio_after, ctx.sr
                )
                alt_reg = 0.0
                for g in ctx.effective_goals:
                    if g in alt_scores:
                        b = ctx.scores_before.get(g, 0.5)
                        a = alt_scores[g]
                        if a < b:
                            alt_reg = max(alt_reg, b - a)
                return alt_reg if alt_reg > 0 else None
        except Exception:
            pass
        return None

    def _decide_on_regression(
        self,
        regression: float,
        ctx: DenkerContext,
        thresholds: dict[str, float],
        is_studio: bool,
    ) -> Decision:
        """Trifft Entscheidung basierend auf Regression + Mode + Retry-Count."""

        # Verbesserung → CONTINUE
        if regression < thresholds["retry_light"]:
            return Decision(
                verdict=DecisionVerdict.CONTINUE,
                reason=f"Regression {regression:.4f} < {thresholds['retry_light']} — "
                       f"Phase erfolgreich ({'Studio' if is_studio else 'Restoration'})",
                recommended_strength=ctx.current_strength,
            )

        # Leichter Drop → RETRY_LIGHTER (Restoration) oder RETRY_DIFFERENT (Studio)
        if regression < thresholds["retry_heavy"]:
            if is_studio and ctx.retry_count >= 2:
                return Decision(
                    verdict=DecisionVerdict.RETRY_DIFFERENT,
                    reason=f"Leichter Drop (Δ={regression:.3f}) nach {ctx.retry_count} Retries "
                           f"→ alternativen Ansatz versuchen (Studio 2026)",
                    recommended_strength=1.0,
                    retry_strategy=RetryStrategy.SWITCH_PLUGIN,
                )
            new_strength = ctx.current_strength * (0.65 if ctx.retry_count == 0 else 0.40)
            return Decision(
                verdict=DecisionVerdict.RETRY_LIGHTER,
                reason=f"Leichter Drop (Δ={regression:.3f}) → reduzierte Intensität "
                       f"({new_strength:.0%})",
                recommended_strength=new_strength,
                retry_strategy=RetryStrategy.REDUCE_INTENSITY,
            )

        # Starker Drop → SKIP oder ROLLBACK
        if ctx.retry_count >= thresholds["max_drops"]:
            return Decision(
                verdict=DecisionVerdict.ROLLBACK,
                reason=f"Starker Drop (Δ={regression:.3f}) nach "
                       f"{ctx.retry_count} Retries → ROLLBACK",
                recommended_strength=0.0,
            )
        return Decision(
            verdict=DecisionVerdict.SKIP,
            reason=f"Starker Drop (Δ={regression:.3f}) → Phase {ctx.phase_id} überspringen",
            recommended_strength=0.0,
        )

    # ── Helpers ──

    def _record(self, decision: Decision) -> None:
        """Zeichnet eine Entscheidung in der History auf."""
        self._decision_history.append(decision)
        if len(self._decision_history) > 200:
            self._decision_history = self._decision_history[-100:]

    def get_history(self) -> list[dict[str, Any]]:
        """Gibt Entscheidungs-History als dicts zurück."""
        with self._lock:
            return [
                {
                    "phase": self._phase_count - len(self._decision_history) + i + 1,
                    "verdict": d.verdict.value,
                    "reason": d.reason,
                    "strength": d.recommended_strength,
                    "undo": d.undo_detected,
                    "paralysis": d.paralysis_detected,
                    "proxy": d.proxy_alternative_used,
                }
                for i, d in enumerate(self._decision_history[-20:])
            ]

    def reset(self) -> None:
        """Reset für neuen Durchlauf."""
        with self._lock:
            self._session_active = False
            self._phase_count = 0
            self._best_effort_count = 0
            self._decision_history.clear()


# ── Singleton ──────────────────────────────────────────────────
_instance: RestaurierDenker | None = None
_lock = threading.Lock()


def get_restaurier_denker() -> RestaurierDenker:
    """Thread-safe Singleton accessor."""
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = RestaurierDenker()
    return _instance


def reset_restaurier_denker() -> None:
    """Reset für Tests."""
    global _instance
    with _lock:
        if _instance is not None:
            _instance.reset()
        _instance = None
