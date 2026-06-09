"""Normative Contracts fuer Worldclass-KPI-Dashboard und Release-Gate.

Ziel:
- Sicherstellen, dass die KPI-Ziele versioniert sind.
- Sicherstellen, dass Dashboard + Release-Gate die 5 Kernmetriken erzwingen.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_THRESHOLDS = Path("config/worldclass_kpi_thresholds.json")
_DASHBOARD_SCRIPT = Path("scripts/worldclass_kpi_dashboard.py")
_RELEASE_GATE_SCRIPT = Path("scripts/worldclass_release_gate.py")
_AUTOPILOT_PIPELINE_SCRIPT = Path("scripts/worldclass_autopilot_pipeline.py")

_REQUIRED_TARGET_KEYS = {
    "artifact_freedom_pass_rate_min",
    "vqi_margin_pass_rate_min",
    "wcs_pass_rate_min",
    "defect_detection_pass_rate_min",
    "defect_confidence_pass_rate_min",
    "defect_confidence_coverage_rate_min",
    "defect_confidence_value_min",
    "era_confidence_pass_rate_min",
    "genre_confidence_pass_rate_min",
    "material_confidence_pass_rate_min",
    "pipeline_confidence_pass_rate_min",
    "uncertainty_coverage_rate_min",
    "era_confidence_value_min",
    "genre_confidence_value_min",
    "material_confidence_value_min",
    "pipeline_confidence_value_min",
    "defect_inaudible_or_max_reduction_pass_rate_min",
    "false_reject_rate_max",
    "runtime_p95_seconds_max",
}


@pytest.mark.normative
@pytest.mark.timeout(20)
def test_worldclass_threshold_config_exists_and_has_required_targets() -> None:
    assert _THRESHOLDS.exists(), "config/worldclass_kpi_thresholds.json fehlt."
    data = json.loads(_THRESHOLDS.read_text(encoding="utf-8"))
    assert isinstance(data, dict), "KPI-Threshold-Config muss ein JSON-Objekt sein."
    targets = data.get("targets")
    assert isinstance(targets, dict), "KPI-Threshold-Config braucht ein targets-Objekt."

    missing = sorted(k for k in _REQUIRED_TARGET_KEYS if k not in targets)
    assert not missing, f"Fehlende KPI-Target-Keys: {missing}"


@pytest.mark.normative
@pytest.mark.timeout(20)
def test_dashboard_script_collects_all_required_kpis() -> None:
    assert _DASHBOARD_SCRIPT.exists(), "scripts/worldclass_kpi_dashboard.py fehlt."
    text = _DASHBOARD_SCRIPT.read_text(encoding="utf-8")

    for key in [
        "artifact_freedom_pass_rate",
        "vqi_margin_pass_rate",
        "wcs_pass_rate",
        "defect_detection_pass_rate",
        "defect_confidence_pass_rate",
        "defect_confidence_coverage_rate",
        "era_confidence_pass_rate",
        "genre_confidence_pass_rate",
        "material_confidence_pass_rate",
        "pipeline_confidence_pass_rate",
        "uncertainty_coverage_rate",
        "defect_inaudible_or_max_reduction_pass_rate",
        "false_reject_rate",
        "runtime_p95_seconds",
    ]:
        assert key in text, f"Dashboard-Skript muss KPI '{key}' verarbeiten."


@pytest.mark.normative
@pytest.mark.timeout(20)
def test_release_gate_script_enforces_all_required_kpis() -> None:
    assert _RELEASE_GATE_SCRIPT.exists(), "scripts/worldclass_release_gate.py fehlt."
    text = _RELEASE_GATE_SCRIPT.read_text(encoding="utf-8")

    # Min-Gates
    assert "artifact_freedom_pass_rate" in text
    assert "vqi_margin_pass_rate" in text
    assert "wcs_pass_rate" in text
    assert "defect_detection_pass_rate" in text
    assert "defect_confidence_pass_rate" in text
    assert "defect_confidence_coverage_rate" in text
    assert "era_confidence_pass_rate" in text
    assert "genre_confidence_pass_rate" in text
    assert "material_confidence_pass_rate" in text
    assert "pipeline_confidence_pass_rate" in text
    assert "uncertainty_coverage_rate" in text
    assert "defect_inaudible_or_max_reduction_pass_rate" in text

    # Max-Gates
    assert "false_reject_rate" in text
    assert "runtime_p95_seconds" in text

    # Harte Fail-Semantik
    assert "WORLDCLASS RELEASE GATE: FAIL" in text
    assert "SystemExit(2)" in text


@pytest.mark.normative
@pytest.mark.timeout(20)
def test_autopilot_pipeline_script_wires_required_worldclass_steps() -> None:
    assert _AUTOPILOT_PIPELINE_SCRIPT.exists(), "scripts/worldclass_autopilot_pipeline.py fehlt."
    text = _AUTOPILOT_PIPELINE_SCRIPT.read_text(encoding="utf-8")

    for required in [
        "run_class_c_revalidation_plan.py",
        "run_wp1_material_vqi_revalidation.py",
        "summarize_class_c_revalidation_results.py",
        "worldclass_kpi_dashboard.py",
        "worldclass_release_gate.py",
    ]:
        assert required in text, f"Autopilot-Pipeline muss Schritt '{required}' aufrufen."
