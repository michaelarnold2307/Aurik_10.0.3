"""
debug_run_elke_best.py — Einmalige Debug-Analyse auf realem Audio.

Führt die Restaurierungspipeline mit enable_debug_trace=True auf der
Elke-Best-MP3 aus und gibt einen strukturierten Report auf stdout aus.

Aufruf:
    .venv_aurik/bin/python debug_run_elke_best.py [restoration|studio]
"""

from __future__ import annotations

import json
import logging
import sys
import time
from pathlib import Path

# Repo-Root auf sys.path
_REPO = Path(__file__).resolve().parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import numpy as np

logging.basicConfig(
    level=logging.WARNING,  # Pipeline-Spam unterdrücken; nur unser Report
    format="%(levelname)s: %(message)s",
)
logger = logging.getLogger("debug_run")

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------
_AUDIO_PATH = str(_REPO / "test_audio" / "Elke Best - Du wolltest nur ein Abenteuer, aber ich suchte einen Freund.mp3")
_MODE = sys.argv[1] if len(sys.argv) > 1 else "Restoration"
_TARGET_SR = 48_000

# Kanonische Goal-Reihenfolge (P1→P5)
_GOAL_PRIORITY = [
    ("P1", ["natuerlichkeit", "authentizitaet"]),
    ("P2", ["tonal_center", "timbre_authentizitaet", "artikulation"]),
    ("P3", ["emotionalitaet", "micro_dynamics", "groove"]),
    ("P4", ["transparenz", "waerme", "bass_kraft", "separation_fidelity"]),
    ("P5", ["brillanz", "spatial_depth"]),
]

# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------


def _sec(s: float) -> str:
    m, s = divmod(int(s), 60)
    return f"{m:02d}:{s:02d}"


def _score_bar(v: float, thr: float, width: int = 20) -> str:
    filled = int(round(v * width))
    bar = "█" * filled + "░" * (width - filled)
    ok = "✓" if v >= thr else "✗"
    return f"{ok} [{bar}] {v:.3f} (thr={thr:.3f})"


def _pct(n: int, total: int) -> str:
    return f"{n}/{total} ({100 * n // total if total else 0}%)"


# ---------------------------------------------------------------------------
# Audio laden & resamplen
# ---------------------------------------------------------------------------


def _load(path: str) -> tuple[np.ndarray, int]:
    from backend.api.bridge import get_load_audio_fn

    load_fn = get_load_audio_fn()
    r = load_fn(path, target_sr=None, mono=False, do_carrier_analysis=False)
    if not isinstance(r, dict) or r.get("audio") is None:
        raise RuntimeError(f"Laden fehlgeschlagen: {r}")
    audio = np.asarray(r["audio"], dtype=np.float32)
    if audio.ndim == 1:
        audio = audio[:, np.newaxis]
    elif audio.ndim == 2 and audio.shape[0] < audio.shape[1]:
        audio = audio.T
    return np.clip(np.nan_to_num(audio), -1.0, 1.0), int(r["sr"])


def _resample(audio: np.ndarray, sr: int) -> np.ndarray:
    if sr == _TARGET_SR:
        return audio
    try:
        import soxr

        return np.asarray(soxr.resample(audio, sr, _TARGET_SR, quality="HQ"), dtype=np.float32)
    except Exception:
        import scipy.signal as sig

        return sig.resample_poly(audio, _TARGET_SR, sr, axis=0).astype(np.float32)


# ---------------------------------------------------------------------------
# Report-Ausgabe
# ---------------------------------------------------------------------------


def _print_separator(title: str = "", char: str = "─", width: int = 70) -> None:
    if title:
        pad = (width - len(title) - 2) // 2
        print(f"\n{'─' * pad} {title} {'─' * (width - pad - len(title) - 2)}")
    else:
        print("─" * width)


def _report(result: Any, elapsed_s: float) -> None:
    meta = getattr(result, "metadata", {}) or {}
    goals = getattr(result, "musical_goals", {}) or {}
    adaptive = meta.get("adaptive_goal_thresholds") or {}
    pmgg_entries = meta.get("pmgg_log_entries") or []
    goal_recovery = meta.get("goal_recovery") or {}
    fail_reasons = meta.get("fail_reasons") or []
    ml_fallbacks = meta.get("ml_fallbacks_used") or []
    sub_threshold = meta.get("sub_threshold_phases") or []

    print("\n")
    print("═" * 70)
    print("  AURIK DEBUG-ANALYSE — ELKE BEST MP3")
    print(f"  Modus: {_MODE}  |  Laufzeit: {_sec(elapsed_s)}  |  RT-Faktor: {getattr(result, 'rt_factor', 0):.2f}×")
    print("═" * 70)

    # ── MATERIAL + BASISDATEN ────────────────────────────────────────────────
    _print_separator("MATERIAL & KONTEXT")
    mat = getattr(result, "material_type", None)
    mat_str = mat.value if hasattr(mat, "value") else str(mat or "?")
    chain = meta.get("transfer_chain") or getattr(result, "transfer_chain", None) or []
    era = getattr(result, "era_decade", "?")
    rest = getattr(result, "restorability", 0)
    qe = getattr(result, "quality_estimate", 0)
    ccr = meta.get("carrier_chain_recovery_ratio", 0)
    print(f"  Material   : {mat_str}")
    print(f"  Kette      : {' → '.join(chain) if chain else '(unbekannt)'}")
    print(f"  Ära        : {era}")
    print(f"  Restorability: {rest:.1f}/100")
    print(f"  Quality Est. : {qe:.3f}")
    print(f"  CCR-Ratio    : {ccr:.3f}  {'(CCR-Shift aktiv)' if ccr > 0.15 else ''}")

    # ── MUSICAL GOALS ────────────────────────────────────────────────────────
    _print_separator("MUSICAL GOALS (14)")
    goals_passed = 0
    goals_total = 0
    for prio, goal_list in _GOAL_PRIORITY:
        for g in goal_list:
            score = float(goals.get(g) or 0.0)
            thr = float(adaptive.get(g) or 0.0)
            passed = score >= thr and thr > 0.0
            if thr > 0.0:
                goals_total += 1
                if passed:
                    goals_passed += 1
            bar = _score_bar(score, thr) if thr > 0.0 else f"  [{score:.3f}] (kein Threshold)"
            print(f"  {prio} {g:<26} {bar}")

    goals_summary = _pct(goals_passed, goals_total)
    print(f"\n  ▶ Bestanden: {goals_summary}")

    # ── GOAL RECOVERY ────────────────────────────────────────────────────────
    if goal_recovery:
        _print_separator("GOAL RECOVERY (§9.8b)")
        print(f"  P1/P2 violations before: {goal_recovery.get('p1p2_violations_before', 0)}")
        print(f"  P1/P2 resolved         : {goal_recovery.get('p1p2_resolved', 0)}")
        print(f"  Universal violations   : {goal_recovery.get('universal_violations_before', 0)}")
        print(f"  Universal resolved     : {goal_recovery.get('universal_resolved', 0)}")
        print(f"  Final violations       : {goal_recovery.get('final_violations', 0)}")
        ua = goal_recovery.get("universal_alpha_used")
        if ua is not None:
            print(f"  Alpha used             : {ua:.2f}")
        remaining = goal_recovery.get("remaining_violations") or []
        if remaining:
            print(f"  Verbleibende Violations: {', '.join(remaining)}")

    # ── PHASEN-ÜBERSICHT ────────────────────────────────────────────────────
    _print_separator("PHASEN")
    phases_exec = getattr(result, "phases_executed", []) or []
    phases_skip = getattr(result, "phases_skipped", []) or []
    print(f"  Ausgeführt : {len(phases_exec)}  |  Übersprungen: {len(phases_skip)}")

    # PMGG-Aktionen analysieren
    if pmgg_entries:
        action_counts: dict[str, int] = {}
        best_effort_phases: list[str] = []
        rollback_phases: list[str] = []
        for e in pmgg_entries:
            action = getattr(e, "action", "") or str(e.get("action", "") if isinstance(e, dict) else "")
            phase = getattr(e, "phase_id", "") or str(e.get("phase_id", "") if isinstance(e, dict) else "")
            action_counts[action] = action_counts.get(action, 0) + 1
            if "best_effort" in action:
                best_effort_phases.append(phase)
            if "rollback" in action or "rolled" in action:
                rollback_phases.append(phase)

        _print_separator("PMGG AKTIONEN")
        for action, cnt in sorted(action_counts.items(), key=lambda x: -x[1]):
            print(f"  {action:<30} {cnt}×")

        if best_effort_phases:
            print(f"\n  ⚠ best_effort Phasen ({len(best_effort_phases)}):")
            for p in best_effort_phases:
                # Auch Regressionen ausgeben wenn vorhanden
                for e in pmgg_entries:
                    eid = getattr(e, "phase_id", "") or (e.get("phase_id", "") if isinstance(e, dict) else "")
                    eac = getattr(e, "action", "") or (e.get("action", "") if isinstance(e, dict) else "")
                    if eid == p and "best_effort" in eac:
                        reg = getattr(e, "goal_regressions", {}) or (
                            e.get("goal_regressions", {}) if isinstance(e, dict) else {}
                        )
                        reg_str = (
                            ", ".join(f"{k}:{v:+.3f}" for k, v in sorted(reg.items()) if abs(v) > 0.005) if reg else ""
                        )
                        print(f"    - {p:<40} {reg_str}")
                        break

        if rollback_phases:
            print(f"\n  ↩ Rollback-Phasen ({len(rollback_phases)}): {', '.join(rollback_phases[:10])}")

    if sub_threshold:
        print(f"\n  Sub-Threshold-Phasen (JND): {', '.join(str(p) for p in sub_threshold[:10])}")

    # ── ML-FALLBACKS ─────────────────────────────────────────────────────────
    if ml_fallbacks:
        _print_separator("ML FALLBACKS")
        for fb in ml_fallbacks:
            print(f"  • {fb}")

    # ── FAIL-REASONS ────────────────────────────────────────────────────────
    if fail_reasons:
        _print_separator("FAIL REASONS")
        for fr in fail_reasons:
            if isinstance(fr, dict):
                print(f"  [{fr.get('severity', '?')}] {fr.get('component', '?')} — {fr.get('error_code', '?')}")
            else:
                print(f"  {fr}")

    # ── AUTO-IMPROVEMENT ─────────────────────────────────────────────────────
    auto_recs = meta.get("auto_improvement_recommendations") or []
    recos = auto_recs if isinstance(auto_recs, list) else auto_recs.get("recommendations", [])
    if recos:
        _print_separator("AUTO-IMPROVEMENT EMPFEHLUNGEN")
        for r in recos[:5]:
            if isinstance(r, dict):
                print(f"  [{r.get('focus', '?')}] {r.get('action', '?')} — {r.get('reason', '?')[:80]}")

    print("\n" + "═" * 70)
    print(f"  ZUSAMMENFASSUNG: Goals {goals_summary}  |  Modus: {_MODE}  |  RT: {elapsed_s:.0f}s")
    print("═" * 70 + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    if not Path(_AUDIO_PATH).exists():
        print(f"FEHLER: Audiodatei nicht gefunden: {_AUDIO_PATH}", file=sys.stderr)
        sys.exit(1)

    print(f"[1/5] Lade Audio: {Path(_AUDIO_PATH).name}")
    audio_raw, sr_raw = _load(_AUDIO_PATH)
    dur_s = audio_raw.shape[0] / sr_raw
    print(f"      {dur_s:.1f}s  |  {sr_raw} Hz  |  {audio_raw.shape[1]}ch")

    print("[2/5] Resampling auf 48 kHz...")
    audio_48k = _resample(audio_raw, sr_raw)

    print("[3/5] Voranalyse (Medium/Era/Genre/Defects/Restorability)...")
    from backend.api.bridge import run_pre_analysis

    pre = run_pre_analysis(
        audio_native=audio_raw,
        sr_native=sr_raw,
        audio_48k=audio_48k,
        file_path=_AUDIO_PATH,
        store_in_bridge_cache=True,
    )
    print("      Voranalyse abgeschlossen.")

    print(f"[4/5] Starte Restaurierungs-Pipeline (Modus: {_MODE}) — kann dauern...")
    from backend.api.bridge import get_aurik_denker_instance

    denker = get_aurik_denker_instance()

    t0 = time.monotonic()
    result = denker.denke(
        audio_48k,
        sr=_TARGET_SR,
        mode=_MODE,
        no_rt_limit=True,
        input_path=_AUDIO_PATH,
        pre_analysis_result=pre,
        enable_debug_trace=True,
    )
    elapsed = time.monotonic() - t0

    print(f"[5/5] Pipeline abgeschlossen in {elapsed:.1f}s")

    _report(result, elapsed)

    # JSON-Dump der Kern-Metriken für weitere Auswertung
    meta = getattr(result, "metadata", {}) or {}
    goals = getattr(result, "musical_goals", {}) or {}
    dump = {
        "goals": {k: round(float(v or 0), 4) for k, v in goals.items()},
        "adaptive_thresholds": {
            k: round(float(v or 0), 4) for k, v in (meta.get("adaptive_goal_thresholds") or {}).items()
        },
        "goal_recovery": meta.get("goal_recovery") or {},
        "transfer_chain": meta.get("transfer_chain") or [],
        "material": str(getattr(result, "material_type", "") or ""),
        "restorability": float(getattr(result, "restorability", 0) or 0),
        "quality_estimate": float(getattr(result, "quality_estimate", 0) or 0),
        "elapsed_s": round(elapsed, 1),
        "phases_executed_count": len(getattr(result, "phases_executed", []) or []),
        "best_effort_count": sum(
            1 for e in (meta.get("pmgg_log_entries") or []) if "best_effort" in (getattr(e, "action", "") or "")
        ),
    }
    out_path = _REPO / "logs" / "debug_run_elke_best.json"
    out_path.parent.mkdir(exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(dump, f, indent=2, ensure_ascii=False, default=str)
    print(f"JSON-Dump: {out_path}")


# ---------------------------------------------------------------------------
# Type alias only imported at runtime to avoid circular imports
# ---------------------------------------------------------------------------
from typing import Any

if __name__ == "__main__":
    main()
