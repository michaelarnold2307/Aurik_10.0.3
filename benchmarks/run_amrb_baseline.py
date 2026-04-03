"""AMRB Baseline Runner — Aurik 9.10.x

Führt den Musical Restoration Benchmark mit der echten AurikDenker-Pipeline
durch und speichert den JSON-Bericht unter benchmarks/amrb_baseline_<mode>.json.

Verwendung::

    .venv_aurik/bin/python benchmarks/run_amrb_baseline.py
    .venv_aurik/bin/python benchmarks/run_amrb_baseline.py --mode studio
    .venv_aurik/bin/python benchmarks/run_amrb_baseline.py --n-items 3 --scenarios tape vinyl dropout
    .venv_aurik/bin/python benchmarks/run_amrb_baseline.py --dry-run

Optionen:
    --mode          restoration | studio  (default: restoration)
    --n-items       Stimuli pro Szenario  (default: 5)
    --duration      Länge je Stimulus in Sekunden (default: 8.0)
    --scenarios     Teilmenge: tape vinyl shellac digital codec vocal reverb hum dropout composite
    --report-path   Expliziter Ausgabepfad für JSON-Bericht
    --dry-run       Nur DSP-Pass-Through — kein ML, schnell
    --verbose       Ausführliches Logging
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("amrb_runner")

# ---------------------------------------------------------------------------
# Scenario name → AMRB key mapping
# ---------------------------------------------------------------------------
_SCENARIO_KEYS = {
    "tape": "AMRB-01-TAPE",
    "vinyl": "AMRB-02-VINYL",
    "shellac": "AMRB-03-SHELLAC",
    "digital": "AMRB-04-DIGITAL",
    "codec": "AMRB-05-CODEC",
    "vocal": "AMRB-06-VOCAL",
    "reverb": "AMRB-07-REVERB",
    "hum": "AMRB-08-HUM",
    "dropout": "AMRB-09-DROPOUT",
    "composite": "AMRB-10-COMPOSITE",
}


def _build_restoration_fn(mode: str, dry_run: bool):
    """Return the (audio, sr) → restored_audio callable for the benchmark.

    dry_run: returns input unchanged (sanity check, fast).
    """
    if dry_run:
        logger.info("DRY-RUN: restoration_fn is pass-through (no ML).")
        return lambda audio, sr: audio.copy()

    # Lazy-import so benchmark CLI works even without full backend warm-up
    try:
        from denker.aurik_denker import get_aurik_denker
    except Exception as exc:
        logger.error("AurikDenker import failed: %s", exc)
        raise

    denker = get_aurik_denker()
    logger.info("AurikDenker loaded, mode=%s", mode)

    def restoration_fn(audio: np.ndarray, sr: int) -> np.ndarray:
        try:
            result = denker.denke(audio, sr, mode=mode, no_rt_limit=True)
            return result.audio
        except Exception as exc:
            logger.warning("restoration_fn error: %s — returning input unchanged", exc)
            return audio.copy()

    return restoration_fn


def _run(args: argparse.Namespace) -> int:
    # Import here so errors are caught after arg parsing
    try:
        import sys as _sys

        _sys.path.insert(0, str(Path(__file__).parent.parent))
        from benchmarks.musical_restoration_benchmark import BenchmarkConfig, run_benchmark
    except Exception as exc:
        logger.error("AMRB import failed: %s", exc)
        return 1

    # Resolve scenario filter
    scenario_filter: list[str] | None = None
    if args.scenarios:
        scenario_filter = []
        for s in args.scenarios:
            key = _SCENARIO_KEYS.get(s.lower())
            if key is None:
                logger.error("Unknown scenario '%s'. Valid: %s", s, list(_SCENARIO_KEYS))
                return 1
            scenario_filter.append(key)

    # Default report path
    if args.report_path:
        report_path = Path(args.report_path)
    else:
        ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
        report_path = Path("benchmarks") / f"amrb_baseline_{args.mode}_{ts}.json"

    restoration_fn = _build_restoration_fn(args.mode, dry_run=args.dry_run)

    config = BenchmarkConfig(
        restoration_fn=restoration_fn,
        sample_rate=48_000,
        n_items_per_scenario=args.n_items,
        duration_s=args.duration,
        scenarios=scenario_filter,
        report_path=report_path,
        system_name=f"Aurik 9.10.x ({args.mode})",
        verbose=args.verbose,
    )

    logger.info(
        "Starting AMRB: mode=%s, n_items=%d, duration=%.1fs, scenarios=%s",
        args.mode,
        args.n_items,
        args.duration,
        scenario_filter or "all",
    )
    t0 = time.monotonic()
    report = run_benchmark(config)
    elapsed = time.monotonic() - t0

    # Print summary
    print("\n" + "=" * 60)
    print(f"  AMRB Baseline — {config.system_name}")
    print("=" * 60)
    print(f"  Overall Score : {report.overall_score:.1f} / 100  (target ≥ 80)")
    print(f"  Scenarios     : {len(report.scenario_results)}")
    print(f"  Runtime       : {elapsed:.0f} s")
    print(f"  Report saved  : {report_path}")
    print()

    passed = 0
    for name, res in report.scenario_results.items():
        score = res.mushra_mean
        ok = "✅" if score >= 80 else "❌"
        print(f"  {ok}  {name:<30} OQS={score:.1f}")
        if score >= 80:
            passed += 1

    print()
    print(f"  Gate: {passed}/{len(report.scenario_results)} scenarios ≥ 80")
    if report.overall_score >= 80:
        print("  ✅ RELEASE_MUST gate PASSED")
    else:
        print("  ❌ RELEASE_MUST gate FAILED")
    print("=" * 60)

    # Also append a compact summary to a persistent baseline log
    log_path = Path("benchmarks") / "amrb_baseline_log.jsonl"
    entry = {
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "mode": args.mode,
        "system_name": config.system_name,
        "overall_score": report.overall_score,
        "scenarios_passed": passed,
        "scenarios_total": len(report.scenario_results),
        "n_items": args.n_items,
        "elapsed_s": round(elapsed, 1),
        "report_path": str(report_path),
    }
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    logger.info("Baseline entry appended to %s", log_path)

    return 0 if report.overall_score >= 80 else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="AMRB Baseline Runner — misst OQS der aktuellen Aurik-Pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--mode",
        choices=["restoration", "studio"],
        default="restoration",
        help="Restaurierungsmodus (default: restoration)",
    )
    parser.add_argument(
        "--n-items",
        type=int,
        default=5,
        metavar="N",
        help="Stimuli pro Szenario (default: 5)",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=8.0,
        metavar="S",
        help="Stimulus-Länge in Sekunden (default: 8.0)",
    )
    parser.add_argument(
        "--scenarios",
        nargs="+",
        metavar="NAME",
        help="Teilmenge der Szenarien, z.B. --scenarios tape dropout",
    )
    parser.add_argument(
        "--report-path",
        metavar="PATH",
        help="Expliziter JSON-Ausgabepfad",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Pass-Through ohne ML — Sanity-Check",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Ausführliches Logging",
    )
    args = parser.parse_args()
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    sys.exit(_run(args))


if __name__ == "__main__":
    main()
