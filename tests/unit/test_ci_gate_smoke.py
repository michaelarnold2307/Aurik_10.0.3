"""CI-Gate Smoke Test — End-to-End Pipeline (§Schutzschicht-3)."""
import numpy as np


def test_ci_gate_regression_baseline_runs():
    """Regression Gate läuft und produziert Baseline."""
    from benchmarks.regression.regression_gate import generate_baseline
    bl = generate_baseline(0.3)
    for name, r in bl.scenarios.items():
        assert r['pqs'] > 0, f"{name}: PQS <= 0"
    assert len(bl.scenarios) >= 4

def test_ci_gate_mini_pipeline_no_nan():
    """Mini-Pipeline produziert kein NaN."""
    from benchmarks.regression.regression_gate import _make_music, _make_noisy, aurik_pipeline
    music = _make_music(0.3)
    noisy = _make_noisy(music, 15.0)
    result = aurik_pipeline(noisy, 48000, use_real=True, full=False)
    assert np.all(np.isfinite(result))

def test_ci_gate_open_source_benchmark_runs():
    """Competitive Benchmark importiert und läuft."""
    from benchmarks.competitive.open_source_benchmark import run
    results, summary = run(["scipy_wiener"], dur=0.3)
    assert summary['ok'] > 0
