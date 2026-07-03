"""Tests fuer Policy-Drift-Guard in backend.adaptive_pipeline."""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np

from backend.adaptive_pipeline import _enforce_canonical_policy_route
from backend.core.restoration_policy import blend_denker_policy_goal_weights, synthesize_human_hearing_comfort_profile
from policy.ml_policy_engine import (
    CANONICAL_INSTRUMENTAL_NR_ROUTE,
    CANONICAL_REPAIR_ROUTE,
    CANONICAL_SEPARATION_ROUTE,
    CANONICAL_VOCAL_NR_ROUTE,
)


def test_enforce_denoise_legacy_to_vocal_route() -> None:
    got = _enforce_canonical_policy_route("denoise", "resemble_enhance", {"has_vocals": True})
    assert got == CANONICAL_VOCAL_NR_ROUTE


def test_enforce_denoise_legacy_to_instrumental_route() -> None:
    got = _enforce_canonical_policy_route("denoise", "deepfilternet", {"has_vocals": False})
    assert got == CANONICAL_INSTRUMENTAL_NR_ROUTE


def test_keep_canonical_denoise_route_unchanged() -> None:
    got = _enforce_canonical_policy_route("denoise", CANONICAL_VOCAL_NR_ROUTE, {"has_vocals": True})
    assert got == CANONICAL_VOCAL_NR_ROUTE


def test_enforce_repair_route() -> None:
    got = _enforce_canonical_policy_route("repair", "dccrn", {"has_vocals": False})
    assert got == CANONICAL_REPAIR_ROUTE


def test_enforce_separation_route() -> None:
    got = _enforce_canonical_policy_route("separation", "mdx23c", {"has_vocals": True})
    assert got == CANONICAL_SEPARATION_ROUTE


def test_enforce_enhancement_legacy_to_instrumental_route() -> None:
    got = _enforce_canonical_policy_route("enhancement", "gacela", {"has_vocals": False})
    assert got == CANONICAL_INSTRUMENTAL_NR_ROUTE


def test_denker_policy_blend_enriches_central_goal_weights() -> None:
    base = {"natuerlichkeit": 1.0, "micro_dynamics": 1.0, "brillanz": 1.0}
    denker_policy = {
        "strategy": {
            "listening_experience_targets": {
                "natuerlichkeit": 1.25,
                "micro_dynamics": 1.20,
            }
        },
        "phase_interaction": {"goal_risk_map": {"brillanz": 0.5}},
    }

    got = blend_denker_policy_goal_weights(base, denker_policy)

    assert got["natuerlichkeit"] > base["natuerlichkeit"]
    assert got["micro_dynamics"] > base["micro_dynamics"]
    assert got["brillanz"] > base["brillanz"]
    assert all(0.65 <= value <= 1.65 for value in got.values())


def test_human_hearing_comfort_profile_is_synthesized_from_denker_policy() -> None:
    denker_policy = {
        "strategy": {
            "intervention_budget": 0.35,
            "human_hearing_risk_map": {
                "listening_fatigue": 0.8,
                "microdynamics_loss": 0.7,
                "overprocessing": 0.6,
            },
        },
        "signal_signature": {
            "crest_db": 22.0,
            "hf_ratio": 0.012,
            "transient_ratio": 0.018,
            "micro_dynamic_db": 5.0,
        },
        "reconstruction_risk_profile": {"hallucination": 0.5},
    }

    profile = synthesize_human_hearing_comfort_profile(denker_policy, mode="restoration")

    assert 2.2 <= profile["peak_overshoot_cap_db"] <= 3.0
    assert 0.45 <= profile["hf_loss_tolerance_db"] <= 1.05
    assert 0.35 <= profile["hf_lift_cap_db"] <= 1.35
    assert 0.20 <= profile["noise_floor_relative_cap_db"] <= 1.20
    assert profile["fatigue_sensitivity"] > 0.4
    assert profile["dullness_risk"] > 0.5
    assert profile["dynamic_smoothing_tolerance"] < 0.25


def test_strategie_denker_exports_human_hearing_comfort_profile() -> None:
    from denker.strategie_denker import StrategieDenker

    audio = (0.2 * np.sin(2.0 * np.pi * 440.0 * np.arange(48_000, dtype=np.float32) / 48_000)).astype(np.float32)
    plan = StrategieDenker().plan(
        audio,
        48_000,
        mode="restoration",
        defect_severity=0.25,
        signal_signature={
            "crest_db": 18.0,
            "hf_ratio": 0.02,
            "transient_ratio": 0.01,
            "micro_dynamic_db": 7.0,
        },
    )

    serialized = plan.as_dict()

    assert "human_hearing_comfort_profile" in serialized
    assert serialized["human_hearing_comfort_profile"]["peak_overshoot_cap_db"] <= 3.0
    assert serialized["human_hearing_comfort_profile"]["hf_lift_cap_db"] > 0.0
    assert serialized["human_hearing_comfort_profile"]["noise_floor_relative_cap_db"] <= 1.20


def test_phases_do_not_read_song_goal_weights_directly() -> None:
    """Phasen muessen Zielgewichte ueber restoration_policy_profile/Helper beziehen."""
    phases_dir = Path(__file__).resolve().parents[2] / "backend" / "core" / "phases"
    offenders: list[str] = []

    for path in sorted(phases_dir.glob("phase_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            direct_get = (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "song_goal_weights"
            )
            direct_subscript = (
                isinstance(node, ast.Subscript)
                and isinstance(node.slice, ast.Constant)
                and node.slice.value == "song_goal_weights"
            )
            if direct_get or direct_subscript:
                offenders.append(path.name)

    assert offenders == []
