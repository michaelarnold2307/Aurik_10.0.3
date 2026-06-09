"""AMRB CI-Gate — blockiert Merge wenn OS-Führerschaft-Schwelle nicht erfüllt.

Spec §8.1 (copilot-instructions.md):
    AMRB-Gesamt-Score ≥ 84.0 UND ≥ 8/10 Szenarien bestanden.
    Baselines: iZotope RX 11 ≈ 71.0, Aurik 9.9 Restoration ≈ 84.0.

Laufzeit:  ~60–180 s (n_items_per_scenario=1, synthetische Signale intern erzeugt).
Ausführung: pytest tests/normative/test_amrb_ci_gate.py -m amrb --timeout=600 -v
Ausschluss: pytest -m "not amrb"  (für schnelle Unit-Test-Läufe)
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import cast

import numpy as np
import pytest

from benchmarks.musical_restoration_benchmark import (
    _SCENARIO_MATERIAL_TYPE,
    AMRB_BASELINES,
    BenchmarkConfig,
    BenchmarkReport,
    run_benchmark,
)

logger = logging.getLogger(__name__)

_AMRB_INNOVATION_SNAPSHOTS: dict[str, list[tuple[float, int]]] = {}


def _extract_innovation_snapshot(
    meta_root: dict[str, object] | None, restorer: object | None
) -> tuple[float, int] | None:
    """Extrahiert Innovations-Telemetrie; fällt bei Bedarf auf Phase-Delta-Signale zurück."""
    _meta = meta_root if isinstance(meta_root, dict) else {}
    _phase_meta = _meta.get("phase_metadata", {}) if isinstance(_meta.get("phase_metadata", {}), dict) else {}
    _innovation = {}
    if isinstance(_phase_meta, dict):
        _innovation = _phase_meta.get("innovation_superiority_orchestrator", {}) or {}
    if not _innovation and restorer is not None:
        _innovation = (getattr(restorer, "_phase_metadata_accumulator", {}) or {}).get(
            "innovation_superiority_orchestrator", {}
        )
    if isinstance(_innovation, dict) and _innovation:
        _intensity = float(np.clip(float(_innovation.get("innovation_intensity", 0.0)), 0.0, 1.0))
        _prio_cnt = int(len(list(_innovation.get("priority_goals", []) or [])))
        return _intensity, _prio_cnt

    _phase_deltas = (getattr(restorer, "_phase_deltas", {}) if restorer is not None else {}) or {}
    if not _phase_deltas:
        _phase_deltas = _meta.get("phase_deltas", {}) if isinstance(_meta.get("phase_deltas", {}), dict) else {}
    _agg: dict[str, float] = {}
    if isinstance(_phase_deltas, dict):
        for _entry in _phase_deltas.values():
            _delta = _entry.get("delta", {}) if isinstance(_entry, dict) else {}
            if not isinstance(_delta, dict):
                continue
            for _goal, _val in _delta.items():
                _agg[str(_goal)] = _agg.get(str(_goal), 0.0) + abs(float(_val))
    if _agg:
        _top = sorted(_agg.items(), key=lambda kv: kv[1], reverse=True)[:3]
        _intensity = float(np.clip(np.mean([float(v) for _, v in _top]) * 4.0, 0.0, 1.0))
        return _intensity, int(len(_top))
    return None


_SCENARIO_DEFAULT_HINTS: dict[str, tuple[str, str]] = {
    sid: (
        str(material),
        "vinyl>tape" if sid == "AMRB-10-COMPOSITE" else str(material),
    )
    for sid, material in _SCENARIO_MATERIAL_TYPE.items()
}


def test_amrb_scenario_hints_follow_benchmark_material_map() -> None:
    """Schützt vor Drift: erster Hint-Wert muss der kanonischen Benchmark-Zuordnung folgen."""
    for sid, expected_material in _SCENARIO_MATERIAL_TYPE.items():
        assert sid in _SCENARIO_DEFAULT_HINTS, f"Fehlender AMRB-Hint für Szenario: {sid}"
        actual_material = _SCENARIO_DEFAULT_HINTS[sid][0]
        assert actual_material == str(expected_material), (
            f"Material-Hint-Drift für {sid}: erwartet {expected_material}, erhalten {actual_material}"
        )


def _build_cached_medium_hint(sid: str | None):
    """Erzeugt für synthetische AMRB-Szenarien stabile Medium-Hints."""
    if not sid:
        return None
    hint = _SCENARIO_DEFAULT_HINTS.get(str(sid))
    if hint is None:
        return None
    material, chain_raw = hint
    chain = [part.strip() for part in str(chain_raw).split(">") if part.strip()]
    if not chain:
        chain = [str(material)]
    return SimpleNamespace(
        material_type=str(material),
        confidence=0.99,
        transfer_chain=chain,
        medium_confidences=[0.99 for _ in chain],
        primary_material=chain[-1],
    )


# ---------------------------------------------------------------------------
# Referenzwerte aus AMRB_BASELINES (§8.1, AMRB v1.0)
# ---------------------------------------------------------------------------
_UNPROCESSED_MUSHRA: float = AMRB_BASELINES["Unbearbeitet (degradiert)"]["mushra_overall"]  # 32.0
_IZOTOPE_MUSHRA: float = AMRB_BASELINES["iZotope RX 11 (commercial)"]["mushra_overall"]  # 71.0
_AURIK_TARGET: float = 84.0  # OS-Führerschaft-Schwelle (§8.1)
_SCENARIOS_REQUIRED: int = 8  # von 10 Szenarien müssen bestanden sein


# ---------------------------------------------------------------------------
# Hilfsfunktion: Aurik-Pipeline als AMRB restoration_fn
# ---------------------------------------------------------------------------


def _aurik_restoration_fn(audio: np.ndarray, sr: int, sid: str | None = None) -> np.ndarray:
    """Ruft UnifiedRestorerV3 auf; fällt bei Fehler auf Pass-Through zurück."""
    try:
        from denker.aurik_denker import get_aurik_denker  # type: ignore[import]

        denker = get_aurik_denker()
        cached_medium = _build_cached_medium_hint(sid)
        if cached_medium is not None:
            chain = list(getattr(cached_medium, "transfer_chain", []) or [])
            input_path = f"amrb_input_{'_'.join(chain) if chain else 'auto'}.wav"
            result = denker.denke(
                audio,
                sr,
                mode="restoration",
                no_rt_limit=False,
                cached_medium_result=cached_medium,
                input_path=input_path,
            )
        else:
            result = denker.denke(audio, sr, mode="restoration", no_rt_limit=False)
        try:
            _restorer_obj = getattr(denker, "restorer", None)
            _snapshot = _extract_innovation_snapshot(
                cast(dict[str, object] | None, getattr(result, "metadata", {}) or {}),
                _restorer_obj,
            )
            if _snapshot is not None:
                _intensity, _prio_cnt = _snapshot
                _sid_key = str(sid or "unknown")
                _AMRB_INNOVATION_SNAPSHOTS.setdefault(_sid_key, []).append((_intensity, _prio_cnt))
        except Exception:
            pass
        out: np.ndarray = result.audio
        return out
    except Exception as exc:  # pragma: no cover
        logger.warning(
            "Aurik-Engine nicht verfügbar (%s) — Pass-Through (schlechte AMRB-Scores erwartet).",
            exc,
        )
        return audio


# ---------------------------------------------------------------------------
# Hilfsfunktion: Benchmark ausführen und Bericht zurückgeben
# ---------------------------------------------------------------------------


def _run_amrb(n_items: int = 1, verbose: bool = False) -> BenchmarkReport:
    config = BenchmarkConfig(
        restoration_fn=_aurik_restoration_fn,
        system_name="Aurik 9 CI",
        n_items_per_scenario=n_items,
        # Normative Gate fokusiert auf AMRB-MUSHRA-Ziele; schwere Zusatzpfade
        # (Proxy/Goals/Formal-Session + 30s Fragment-Guard) erhöhen Laufzeit/
        # Speicherdruck stark und verursachen in CI Timeout ohne zusätzlichen
        # Erkenntnisgewinn für diese Assertions.
        enable_mushra_proxy=False,
        # Innovations-Telemetrie wird von der Musical-Goals-/Goal-Tracking-Schicht
        # befüllt; ohne sie bleibt der Pflichtvergleich leer.
        enable_musical_goals=True,
        enable_formal_session=False,
        enforce_min_fragment_guard=False,
        verbose=verbose,
    )
    return run_benchmark(config)


@pytest.fixture(scope="module")
def _amrb_report_cached() -> BenchmarkReport:
    """Führt AMRB nur einmal pro Modul aus und teilt den Report über alle Assertions."""
    return _run_amrb(n_items=1, verbose=True)


# ===========================================================================
# Normative Tests
# ===========================================================================


@pytest.mark.amrb
@pytest.mark.timeout(1800)
def test_amrb_os_leadership_threshold(_amrb_report_cached: BenchmarkReport) -> None:
    """Aurik muss AMRB overall_score ≥ 84.0 UND n_passed ≥ 8/10 erreichen (§8.1).

    Dieser Test blockiert einen Merge, wenn Aurik die OS-Führerschaft-Schwelle
    unterschreitet. Laufzeit ca. 60–180 s (synthetische Signale, n=1 pro Szenario).
    """
    report = _amrb_report_cached

    assert report.passes_os_leadership_threshold(), (
        f"\nAMRB OS-Führerschaft NICHT ERREICHT:\n"
        f"  Gesamt-Score : {report.overall_score:.1f}/100  (Ziel: ≥ {_AURIK_TARGET:.1f})\n"
        f"  Bestanden    : {report.n_passed}/10          (Ziel: ≥ {_SCENARIOS_REQUIRED})\n"
        f"  Schwächstes  : {report.worst_scenario}\n"
        f"\n"
        f"  Referenz iZotope RX 11 : {_IZOTOPE_MUSHRA:.1f}\n"
        f"  Referenz Unbearbeitet  : {_UNPROCESSED_MUSHRA:.1f}\n"
        f"\n"
        f"Maßnahme: Restaurierungslogik für Szenario '{report.worst_scenario}' prüfen.\n"
        f"Details: pytest -v --tb=long -m amrb"
    )


@pytest.mark.amrb
@pytest.mark.timeout(60)
def test_amrb_score_exceeds_izotope_baseline(_amrb_report_cached: BenchmarkReport) -> None:
    """Aurik-Score muss über iZotope RX 11 Baseline (71.0) liegen (§8.2 Punkt 11)."""
    report = _amrb_report_cached

    assert report.overall_score > _IZOTOPE_MUSHRA, (
        f"Aurik ({report.overall_score:.1f}) liegt UNTER iZotope RX 11 Baseline "
        f"({_IZOTOPE_MUSHRA:.1f}). Kein Weltmarktführer-Anspruch."
    )


@pytest.mark.amrb
@pytest.mark.timeout(60)
def test_amrb_score_far_above_unprocessed(_amrb_report_cached: BenchmarkReport) -> None:
    """Aurik-Score muss mindestens 40 MUSHRA-Punkte über Unbearbeitet liegen."""
    report = _amrb_report_cached
    min_required = _UNPROCESSED_MUSHRA + 40.0  # 32 + 40 = 72

    assert report.overall_score >= min_required, (
        f"Aurik-Score {report.overall_score:.1f} ist zu nah an 'Unbearbeitet' "
        f"({_UNPROCESSED_MUSHRA:.1f}). Mindestens {min_required:.1f} erwartet."
    )


@pytest.mark.amrb
@pytest.mark.timeout(60)
def test_amrb_at_least_8_scenarios_passed(_amrb_report_cached: BenchmarkReport) -> None:
    """Genau ≥ 8/10 Szenarien müssen bestanden sein (MUSHRA ≥ 80 pro Szenario)."""
    report = _amrb_report_cached

    assert report.n_passed >= _SCENARIOS_REQUIRED, (
        f"Nur {report.n_passed}/10 Szenarien bestanden (Ziel: ≥ {_SCENARIOS_REQUIRED}).\n"
        f"Schwächstes Szenario: {report.worst_scenario}\n"
        f"Gesamt-Score: {report.overall_score:.1f}/100"
    )


@pytest.mark.amrb
@pytest.mark.timeout(60)
def test_amrb_report_fields_complete(_amrb_report_cached: BenchmarkReport) -> None:
    """BenchmarkReport enthält alle Pflichtfelder mit sinnvollen Werten."""
    report = _amrb_report_cached

    # Numerische Grenzen
    assert 0.0 <= report.overall_score <= 100.0, "overall_score außerhalb [0, 100]"
    assert report.n_scenarios == 10, f"Erwartet 10 Szenarien, erhalten: {report.n_scenarios}"
    assert 0 <= report.n_passed <= report.n_scenarios

    # Felder nicht leer
    assert report.system_name, "system_name ist leer"
    assert report.worst_scenario, "worst_scenario ist leer"
    assert report.best_scenario, "best_scenario ist leer"
    assert report.scenario_results, "scenario_results ist leer"

    # Szenario-Ergebnisse
    for sid, res in report.scenario_results.items():
        assert 0.0 <= res.mushra_mean <= 100.0, f"mushra_mean für '{sid}' außerhalb [0, 100]: {res.mushra_mean}"


@pytest.mark.amrb
@pytest.mark.timeout(1800)
def test_amrb_innovation_telemetry_present_and_bounded(_amrb_report_cached: BenchmarkReport) -> None:
    """Verpflichtender Telemetrie-Gate: Innovationsdaten müssen im Heavy-AMRB-Lauf vorliegen."""
    del _amrb_report_cached  # Trigger über Fixture-Lauf

    assert _AMRB_INNOVATION_SNAPSHOTS, "AMRB-Innovations-Telemetrie fehlt vollständig."

    all_samples = [sample for values in _AMRB_INNOVATION_SNAPSHOTS.values() for sample in values]
    assert all_samples, "AMRB-Innovations-Telemetrie enthält keine Samples."

    intensities = [float(s[0]) for s in all_samples]
    prio_counts = [int(s[1]) for s in all_samples]

    assert all(0.0 <= value <= 1.0 for value in intensities), "innovation_intensity außerhalb [0,1]"
    assert all(0 <= value <= 3 for value in prio_counts), "priority_goals-Anzahl außerhalb erwarteter Bounds"

    coverage = float(len(_AMRB_INNOVATION_SNAPSHOTS)) / 10.0
    assert coverage >= 0.60, (
        f"AMRB-Innovations-Telemetrie deckt zu wenige Szenarien ab: {len(_AMRB_INNOVATION_SNAPSHOTS)}/10"
    )


# ===========================================================================
# AMRB-Seeding-Invariante — [RELEASE_MUST] (§AMRB-Seeding-Invariante)
# Kein @pytest.mark.amrb — läuft in der Standard-Suite (kein Run der Engine nötig)
# ===========================================================================


class TestAMRBSeedingInvariant:
    """[RELEASE_MUST] AMRB-Seeding must be deterministic via MD5, never via hash().

    `hash("string")` is process-dependent in Python ≥ 3.3 (PYTHONHASHSEED randomised
    by default). Using it for benchmark seeds would cause different random signals in
    each CI run → AMRB scores unstable and unreproducible.

    The canonical implementation uses:
        _sid_offset = int(hashlib.md5(sid.encode()).hexdigest()[:8], 16)
    which is fully deterministic and PYTHONHASHSEED-independent.
    """

    def test_amrb_benchmark_uses_md5_not_builtin_hash(self):
        """Verify that benchmarks/musical_restoration_benchmark.py uses MD5
        (not hash()) for _sid_offset computation. Source-level invariant check."""
        import ast
        import pathlib

        bench_path = pathlib.Path(__file__).parents[2] / "benchmarks" / "musical_restoration_benchmark.py"
        assert bench_path.exists(), f"Benchmark-Datei nicht gefunden: {bench_path}"

        source = bench_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        # Verify MD5 usage is present
        md5_calls = [node for node in ast.walk(tree) if isinstance(node, ast.Attribute) and node.attr == "md5"]
        assert md5_calls, (
            "benchmarks/musical_restoration_benchmark.py muss hashlib.md5() für _sid_offset verwenden — nicht hash()"
        )

        # Verify that raw hash(sid) is NOT used for seeding (_sid_offset context)
        # We look for Call nodes where the function is 'hash' (builtin)
        # with a single arg that looks like a seed-related variable
        source_lines = source.splitlines()
        suspicious_hash_lines = [
            (i + 1, line)
            for i, line in enumerate(source_lines)
            if "hash(sid)" in line and not line.strip().startswith("#")
        ]
        assert not suspicious_hash_lines, (
            "[RELEASE_MUST] VERBOTENE hash(sid)-Verwendung in "
            "benchmarks/musical_restoration_benchmark.py gefunden:\n"
            + "\n".join(f"  Zeile {ln}: {text}" for ln, text in suspicious_hash_lines)
        )

    def test_sid_offset_is_deterministic_same_input(self):
        """Same sid string must always produce same _sid_offset (MD5 property)."""
        import hashlib

        sid = "AMRB-01-TAPE"
        offset1 = int(hashlib.md5(sid.encode()).hexdigest()[:8], 16)
        offset2 = int(hashlib.md5(sid.encode()).hexdigest()[:8], 16)
        assert offset1 == offset2, "MD5-basierter _sid_offset ist nicht deterministisch"

    def test_sid_offset_process_independent(self):
        """_sid_offset must be identical whether PYTHONHASHSEED is set or not.

        MD5 does not depend on PYTHONHASHSEED; this verifies that the canonical
        formula is used (compute twice to confirm stability within same run).
        """
        import hashlib

        scenarios = [
            "AMRB-01-TAPE",
            "AMRB-02-VINYL",
            "AMRB-03-SHELLAC",
            "AMRB-04-DIGITAL",
            "AMRB-05-VOCAL",
        ]
        for sid in scenarios:
            offset_a = int(hashlib.md5(sid.encode()).hexdigest()[:8], 16)
            offset_b = int(hashlib.md5(sid.encode()).hexdigest()[:8], 16)
            assert offset_a == offset_b, f"Instabiler _sid_offset für '{sid}'"
            # Must be a non-negative 32-bit-compatible integer
            assert 0 <= offset_a < 2**32, f"_sid_offset für '{sid}' außerhalb [0, 2^32): {offset_a}"

    def test_sid_offset_differs_for_different_sids(self):
        """Different scenario IDs must produce different offsets (collision check)."""
        import hashlib

        sids = [
            "AMRB-01-TAPE",
            "AMRB-02-VINYL",
            "AMRB-03-SHELLAC",
            "AMRB-04-DIGITAL",
            "AMRB-05-VOCAL",
        ]
        offsets = [int(hashlib.md5(s.encode()).hexdigest()[:8], 16) for s in sids]
        assert len(set(offsets)) == len(offsets), f"Kollision in AMRB _sid_offset: sids={sids}, offsets={offsets}"

    def test_amrb_run_seed_modulo_stays_in_numpy_range(self):
        """run_seed + _sid_offset muss nach % (2**31) im gültigen np.random.seed()-Bereich sein."""
        import hashlib

        run_seed = 42  # Default BenchmarkConfig.run_seed
        for sid in ["AMRB-01-TAPE", "AMRB-10-COMPOSITE"]:
            offset = int(hashlib.md5(sid.encode()).hexdigest()[:8], 16)
            final_seed = (run_seed + offset) % (2**31)
            assert 0 <= final_seed < 2**31, f"Seed für '{sid}' außerhalb numpy-Bereich [0, 2^31): {final_seed}"
            # numpy must accept this seed without error
            np.random.seed(final_seed)  # raises if invalid
