"""
AdaptivePhaseRescheduler — Geschlossener Regelkreis für UV3-Pipeline (§2.78)
=============================================================================

Nach jeder Phase wird geprüft, ob verbleibende Musical-Goal-Lücken
Recovery-Phasen erfordern, die noch nicht im Ausführungsplan stehen.
Solche Phasen werden dynamisch an das Ende von `selected_phases` angehängt
(Python for-Loop besucht neu angehängte Listenelemente — kein Loop-Umbau nötig).

Invarianten:
- §0a: phase_21_exciter / phase_35_multiband_compression / phase_42_vocal_enhancement
        niemals in Restoration injiziert (get_goal_recovery_phases garantiert es;
        Rescheduler prüft zusätzlich als Sicherheitsnetz)
- §2.45 Minimal-Intervention: Injektion nur wenn gap > GAP_THRESHOLD (0.05)
- §2.52 _NEVER_SKIP: Diese Phasen sind immer im Plan — keine Injektion nötig
- §2.65 MAS: Aufrufer prüft _mas_fully_achieved vor reschedule()-Aufruf (non-blocking)
- §0c: Kein song-spezifischer Hardcode; alle Entscheidungen via get_goal_recovery_phases()
- §2.67 Phase-Koalitionen: keine Injektion von Einzel-Phasen aus Koalitionen
- Max-Injektion: MAX_INJECTIONS_PER_SESSION (3) pro Song-Session
- Singleton (thread-safe, double-checked locking)

Author: Aurik Development Team
Version: 1.0.0 (§2.78 Closed-Loop Rescheduler v9.12.9)
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

import numpy as np

from backend.core.calibration_matrix import get_goal_recovery_phases as _get_goal_recovery_phases

logger = logging.getLogger(__name__)

# ── Limits (statische Defaults — adaptiver Wert per Song via Hilfsfunktionen) ─────────────
MAX_INJECTIONS_PER_SESSION: int = 3  # Basis-Limit; adaptiv erhöht bei niedriger Restorability
GAP_THRESHOLD: float = 0.05  # Basis-Schwelle; adaptiv gesenkt bei niedriger Restorability


def _adaptive_gap_threshold(restorability_score: float) -> float:
    """Berechnet einen restorability-adaptiven GAP_THRESHOLD.

    Logik (§2.45 Minimal-Intervention + §0k Maximum-Achievable-Score):
    - Gut restaurierbare Songs (rest ≈ 100): 0.05 — nur klare Lücken auslösen Injektion.
    - Schwer restaurierbare Songs (rest ≈ 0):  0.025 — kleinere Lücken schon ansprechen,
      weil jede Recovery-Chance zählt und falsch-negative teurer sind als falsch-positive.

    Lineare Interpolation zwischen den Polen; Ergebnis auf [0.025, 0.05] geclippt.
    """
    _rest = float(np.clip(restorability_score, 0.0, 100.0))
    return float(np.clip(0.025 + 0.025 * (_rest / 100.0), 0.025, 0.05))


def _adaptive_max_injections(restorability_score: float) -> int:
    """Berechnet das restorability-adaptive Session-Injektionslimit.

    Logik:
    - rest > 50: Limit 3 (Standard — gut restaurierbare Songs brauchen wenig Recovery).
    - rest <= 50: Limit 4 — mehr Recovery-Versuche erlaubt.
    - rest <= 25: Limit 5 — maximale Recovery-Versuche für sehr schwierige Songs.

    §0h/§0c: Kein Hardcode song-spezifisch; nur restorability-basiert.
    """
    _rest = float(np.clip(restorability_score, 0.0, 100.0))
    if _rest <= 25.0:
        return 5
    if _rest <= 50.0:
        return 4
    return 3


# §0a-verbotene Phasen — dürfen in Restoration nie injiziert werden
_RESTORATION_FORBIDDEN: frozenset[str] = frozenset(
    {
        "phase_21_exciter",
        "phase_35_multiband_compression",
        "phase_42_vocal_enhancement",
    }
)

# §2.52 _NEVER_SKIP-Phasen laufen immer — keine Injektion nötig (redundant / harmlos, aber klar)
_NEVER_SKIP: frozenset[str] = frozenset(
    {
        "phase_01_click_removal",
        "phase_09_crackle_removal",
        "phase_12_wow_flutter_fix",
        "phase_14_phase_correction",
        "phase_15_stereo_balance",
        "phase_30_dc_offset_removal",
        "phase_47_truepeak_limiter",
        "phase_65_vocal_naturalness_restoration",
    }
)

# Goals die per VQI-Gate / HPI-Gate eigene Recovery-Pfade haben
# → kein Rescheduler-Override nötig (würde nur duplizieren)
_SELF_MANAGED_GOALS: frozenset[str] = frozenset(
    {
        "vocal_quality",  # VQI-Gate §0p / _recovery_cascade()
        "formant_fidelity",  # Formant-Guard §0p / phase_04-Rollback
    }
)

# Prioritäts-Reihenfolge der Goals (P0 > P1 > P2 > P3 > P4 > P5)
# Der Rescheduler arbeitet Goals von höchster zu niedrigster Prio ab.
_GOAL_PRIORITY: list[str] = [
    # P1
    "natuerlichkeit",
    "authentizitaet",
    # P2
    "tonal_center",
    "timbre_authentizitaet",
    "timbre",
    "artikulation",
    "transient_energie",
    # P3
    "emotionalitaet",
    "micro_dynamics",
    "groove",
    # P4
    "transparenz",
    "waerme",
    "bass_kraft",
    "separation_fidelity",
    # P5
    "brillanz",
    "spatial_depth",
]


@dataclass
class RescheduleResult:
    """Ergebnis eines reschedule()-Aufrufs."""

    new_phases_to_append: list[str] = field(default_factory=list)
    """Phasen-IDs die ans Ende von selected_phases angehängt werden sollen."""

    goal_gaps_found: dict[str, float] = field(default_factory=dict)
    """Goal-Lücken die Injektion ausgelöst haben (für Logging/Telemetry)."""


class AdaptivePhaseRescheduler:
    """Closed-Loop Rescheduler für die UV3-Pipeline.

    Analysiert nach jeder Phase die verbleibenden Goal-Lücken und
    injiziert Recovery-Phasen in selected_phases (Append).

    Singleton-Pattern: nie direkt instanziieren — `get_adaptive_phase_rescheduler()` verwenden.
    """

    def __init__(self) -> None:
        self._op_lock = threading.Lock()
        self._session_injected: set[str] = set()  # Phasen die in dieser Session injiziert wurden

    # ─── Public API ────────────────────────────────────────────────────────────

    def reset_session(self) -> None:
        """Setzt Session-State zurück (aufrufen: je Song-Session, nach _conductor.reset())."""
        with self._op_lock:
            self._session_injected.clear()

    def reschedule(
        self,
        current_goal_scores: dict[str, float],
        song_goal_targets: dict[str, float],
        selected_phases: list[str],
        executed: set[str],
        is_studio_2026: bool = False,
        transfer_chain: list[str] | None = None,
        material_type: str = "unknown",
        restorability_score: float = 70.0,
    ) -> RescheduleResult:
        """Berechnet Phasen-Injektionen basierend auf aktuellen Goal-Lücken.

        Args:
            current_goal_scores: Goal-Proxy-Scores nach letzter Phase (aus _fast_goal_snapshot).
            song_goal_targets: Per-Song Studio-Day-Targets (aus estimate_song_goal_targets).
            selected_phases: Aktuelle (veränderliche) Phase-Liste — wird NICHT verändert hier;
                             Caller fügt `new_phases_to_append` ans Ende.
            executed: Menge bereits ausgeführter Phase-IDs (inkl. skipped).
            is_studio_2026: Modus-Flag (§0a-Guard für Restoration).
            transfer_chain: Transfer-Chain aus _restoration_context (für chain-aware Recovery).
            material_type: Materialklasse für material-sensitive Gap-Bewertung.
            restorability_score: RestorabilityEstimator-Score [0–100] — steuert adaptive
                                 GAP_THRESHOLD und MAX_INJECTIONS (§0k, §2.45).

        Returns:
            RescheduleResult mit new_phases_to_append-Liste (leer bei keinem Bedarf).

        Non-blocking: Exceptions → leeres RescheduleResult (Pipeline läuft weiter).
        """
        try:
            return self._reschedule_internal(
                current_goal_scores=current_goal_scores,
                song_goal_targets=song_goal_targets,
                selected_phases=selected_phases,
                executed=executed,
                is_studio_2026=is_studio_2026,
                transfer_chain=list(transfer_chain or []),
                material_type=str(material_type or "unknown"),
                restorability_score=float(restorability_score),
            )
        except Exception as exc:
            logger.debug("§2.78 AdaptivePhaseRescheduler.reschedule() non-blocking: %s", exc)
            return RescheduleResult()

    # ─── Private Implementierung ────────────────────────────────────────────────

    def _reschedule_internal(
        self,
        current_goal_scores: dict[str, float],
        song_goal_targets: dict[str, float],
        selected_phases: list[str],
        executed: set[str],
        is_studio_2026: bool,
        transfer_chain: list[str],
        material_type: str,
        restorability_score: float = 70.0,
    ) -> RescheduleResult:
        with self._op_lock:
            _injected_this_call: list[str] = []
            _gaps_triggered: dict[str, float] = {}

            # Restorability-adaptive Limits (§0k, §2.45 Minimal-Intervention)
            _max_inj = _adaptive_max_injections(restorability_score)
            _gap_thr = _adaptive_gap_threshold(restorability_score)

            # §0l Material-adaptiver Gap-Threshold: analoge Träger (cassette, tape, vinyl, shellac)
            # haben stärkere physikalische Degradierung → strengere Lückenschwelle (0.90-Faktor),
            # damit Recovery-Phasen früher greifen (V38: material_type-aware Oracle).
            _ANALOG_MATERIALS: frozenset[str] = frozenset(
                {"cassette", "tape", "vinyl", "shellac", "reel_tape", "wire_recording", "wax_cylinder"}
            )
            if str(material_type).lower() in _ANALOG_MATERIALS:
                _gap_thr = float(np.clip(_gap_thr * 0.90, 0.022, _gap_thr))

            # Frühausstieg: Session-Limit bereits erreicht
            if len(self._session_injected) >= _max_inj:
                return RescheduleResult()

            # Aktueller Plan als Set für schnelle Lookups
            _plan_set: set[str] = set(selected_phases)

            # Goal-Lücken berechnen (normiert: gap = target − score)
            _goal_gaps: dict[str, float] = {}
            for goal in _GOAL_PRIORITY:
                if goal in _SELF_MANAGED_GOALS:
                    continue
                _target = float(song_goal_targets.get(goal, 0.0))
                _score = float(current_goal_scores.get(goal, 0.0))
                if _target <= 0.0:
                    continue
                _gap = float(np.clip(_target - _score, 0.0, 1.0))
                if _gap > _gap_thr:
                    _goal_gaps[goal] = _gap

            if not _goal_gaps:
                return RescheduleResult()

            # Recovery-Phasen für Goals mit signifikanten Lücken bestimmen
            _get_recovery = _get_goal_recovery_phases

            # Goals nach absteigendem Gap sortieren (größte Lücke zuerst)
            _sorted_goals = sorted(_goal_gaps.items(), key=lambda it: it[1], reverse=True)

            for _goal_name, _gap_val in _sorted_goals:
                if len(self._session_injected) + len(_injected_this_call) >= _max_inj:
                    break

                _recovery_phases = _get_recovery(
                    goal=_goal_name,
                    is_studio_2026=is_studio_2026,
                    transfer_chain=transfer_chain if transfer_chain else None,
                )
                if not _recovery_phases:
                    continue

                # Nur Primär-Phase (Index 0) injizieren — §2.45 Minimal-Intervention
                _primary_phase = _recovery_phases[0]

                # Guards
                if _primary_phase in executed:
                    continue  # bereits ausgeführt → kein Gewinn durch Wiederholung
                if _primary_phase in _plan_set:
                    continue  # bereits im Plan
                if _primary_phase in self._session_injected:
                    continue  # bereits in dieser Session injiziert
                if _primary_phase in _injected_this_call:
                    continue  # Guard gegen Duplikate innerhalb dieses Aufrufs
                if _primary_phase in _NEVER_SKIP:
                    continue  # _NEVER_SKIP laufen immer — Injektion unnötig
                # §0a-Guard: in Restoration keine verbotenen Phasen
                if not is_studio_2026 and _primary_phase in _RESTORATION_FORBIDDEN:
                    logger.debug(
                        "§2.78 §0a-Guard: %s nicht injiziert (Restoration verboten)",
                        _primary_phase,
                    )
                    continue

                _injected_this_call.append(_primary_phase)
                _gaps_triggered[_goal_name] = round(_gap_val, 4)
                logger.info(
                    "§2.78 Rescheduler: %s für goal=%s (gap=%.3f) vorgemerkt",
                    _primary_phase,
                    _goal_name,
                    _gap_val,
                )

            # Session-State nach erfolgreicher Berechnung aktualisieren
            for _p in _injected_this_call:
                self._session_injected.add(_p)

            return RescheduleResult(
                new_phases_to_append=_injected_this_call,
                goal_gaps_found=_gaps_triggered,
            )


# ── Singleton ──────────────────────────────────────────────────────────────────
_instance: AdaptivePhaseRescheduler | None = None
_lock = threading.Lock()


def get_adaptive_phase_rescheduler() -> AdaptivePhaseRescheduler:
    """Thread-safe Singleton-Factory für AdaptivePhaseRescheduler."""
    global _instance  # pylint: disable=global-statement
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = AdaptivePhaseRescheduler()
    return _instance
