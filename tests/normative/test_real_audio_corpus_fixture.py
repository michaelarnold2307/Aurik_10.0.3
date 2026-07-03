"""Normative Real-Audio-Korpus-Fixture fuer R5-R12-Folgegates."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from tests.test_uat_acceptance_criteria import (
    _integrated_lufs_or_fallback,
    _noise_floor_dbfs,
    _run_real_audio_restore_with_timeout,
    _safe_corr,
    _to_samples_first,
)


@pytest.mark.normative
@pytest.mark.timeout(20)
def test_real_audio_corpus_fixture_covers_multiple_local_sources(
    real_audio_corpus_cases: list[dict[str, Any]],
) -> None:
    paths = [Path(str(case["path"])) for case in real_audio_corpus_cases]
    categories = {path.parent.name for path in paths}

    assert len(paths) >= 4
    assert {"tape", "vinyl", "digital", "vocals"} & categories

    for case in real_audio_corpus_cases:
        audio = np.asarray(case["audio"], dtype=np.float32)
        sr = int(case["sr"])
        assert sr == 48_000
        assert audio.ndim == 2
        assert audio.shape[1] == 2
        assert audio.shape[0] >= sr * 2
        assert np.isfinite(audio).all()
        assert float(np.max(np.abs(audio))) <= 1.0 + 1e-6


@pytest.mark.normative
@pytest.mark.heavy
@pytest.mark.timeout(600)
def test_real_audio_corpus_restore_no_harm_gate(
    request: pytest.FixtureRequest,
    real_audio_corpus_cases: list[dict[str, Any]],
) -> None:
    if not bool(request.config.getoption("--run-heavy-tests")):
        pytest.skip("Real-Audio-Korpus-Restore-Gate nur mit --run-heavy-tests")

    limit = max(1, int(float(os.environ.get("AURIK_REAL_AUDIO_CORPUS_RESTORE_LIMIT", "2") or 2)))
    max_seconds = max(2.0, float(os.environ.get("AURIK_REAL_AUDIO_CORPUS_RESTORE_SECONDS", "3.0") or 3.0))
    ml_budget_s = float(os.environ.get("AURIK_REAL_AUDIO_CORPUS_ML_RUNTIME_BUDGET_S", "2.0") or 2.0)
    timeout_s = float(os.environ.get("AURIK_REAL_AUDIO_CORPUS_RESTORE_TIMEOUT_S", "300") or 300.0)

    checked: list[str] = []
    for case in real_audio_corpus_cases[:limit]:
        sr = int(case["sr"])
        original = _to_samples_first(np.asarray(case["audio"], dtype=np.float32))
        original = original[: min(original.shape[0], int(sr * max_seconds))]
        restorer_input = original.T if original.ndim == 2 else original

        payload = _run_real_audio_restore_with_timeout(restorer_input, sr, ml_budget_s, timeout_s)
        restored = _to_samples_first(np.asarray(payload["audio"], dtype=np.float32))
        n = min(original.shape[0], restored.shape[0])
        original = original[:n]
        restored = restored[:n]

        assert n >= sr * 2, f"Restore-Ausgabe zu kurz: {case['path']}"
        assert restored.ndim == 2 and restored.shape[1] == 2, f"Stereo-Layout verloren: {case['path']}"
        assert np.isfinite(restored).all(), f"NaN/Inf im Restore: {case['path']}"
        assert float(np.max(np.abs(restored))) <= 1.0 + 1e-6, f"Restore außerhalb [-1,1]: {case['path']}"

        corr_before = _safe_corr(original[:, 0], original[:, 1])
        corr_after = _safe_corr(restored[:, 0], restored[:, 1])
        assert corr_after <= min(0.995, corr_before + 0.12), (
            f"Stereo-Kollaps im Korpusfall: {case['path']} corr {corr_before:.3f}->{corr_after:.3f}"
        )

        floor_before = _noise_floor_dbfs(original)
        floor_after = _noise_floor_dbfs(restored)
        lufs_before = _integrated_lufs_or_fallback(original, sr)
        lufs_after = _integrated_lufs_or_fallback(restored, sr)
        floor_after_cmp = floor_after - abs(lufs_after - lufs_before)
        material_key = str(payload.get("material_type", "unknown") or "unknown").lower()
        allowance_db = {
            "vinyl": 2.5,
            "shellac": 2.5,
            "lacquer_disc": 2.5,
            "acetate": 2.5,
            "reel_tape": 2.0,
            "tape": 2.0,
            "cassette": 2.0,
            "mp3_low": 1.5,
            "mp3_high": 1.0,
            "aac": 1.0,
            "streaming": 1.0,
            "cd_digital": 0.5,
            "dat": 0.5,
        }.get(material_key, 1.5)
        assert floor_after_cmp <= floor_before + allowance_db, (
            f"Rauschboden-Korpusregression: {case['path']} {floor_before:.2f}->{floor_after_cmp:.2f} "
            f"material={material_key} limit=+{allowance_db:.1f}dB"
        )
        checked.append(str(case["path"]))

    assert len(checked) == min(limit, len(real_audio_corpus_cases))
