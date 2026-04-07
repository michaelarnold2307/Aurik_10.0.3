---
name: test-writing
description: "Schreibt Tests für Aurik 9 (pytest, Marker, Heavy-Isolation, conftest). Use when: Test, pytest, test_, Marker, conftest, ml, slow, heavy, unit, normative, integration, regression, e2e, fixture, Edge-Case."
argument-hint: "Welcher Test? (z.B. 'Tests für neue Phase schreiben', 'Heavy-Test isolieren')"
---

# Aurik 9 — Tests schreiben

## Test-Verzeichnisstruktur

| Ordner | Inhalt | Marker |
|---|---|---|
| `tests/unit/` | Schnelle Unit-Tests (≤ 30 s Timeout) | — |
| `tests/musical_goals/` | 14-Goal-Schwellwert-Tests | — |
| `tests/integration/` | Modul-Übergreifende Tests | — |
| `tests/normative/` | CI-Gate-Tests (RELEASE_MUST) | — |
| `tests/regression/` | Regressions-Absicherung | — |
| `tests/e2e/` | End-to-End mit echtem Audio | `e2e` |

## Marker-System

| Marker | Bedeutung | Standard-Suite? |
|---|---|---|
| `ml` | ML-Modell wird geladen | NEIN (nur `--run-heavy-tests`) |
| `slow` | Timeout > 30 s | NEIN (nur `--run-heavy-tests`) |
| `e2e` | End-to-End mit I/O | NEIN (explizit) |
| (kein Marker) | Standard Unit-Test | JA |

`conftest.py` markiert automatisch `ml`/`slow` basierend auf Testinhalten.

## Pflicht-Mindestanzahl pro Modul

**≥ 35 Unit-Tests** für jedes neue Kernmodul:
- Shape-Tests (Mono, Stereo, verschiedene Längen)
- NaN/Inf-Guard (Input und Output)
- Bounds-Tests (Clip [-1, 1])
- Edge-Cases (leeres Audio, 1 Sample, sehr langes Audio)
- Mono UND Stereo
- Musical Goals: kein Ziel nach Modul schlechter
- GrooveMetric DTW ≤ 8 ms RMS
- SOFT_SATURATION → nicht als CLIPPING detektiert
- Pass-Through (SNR > 40 dB → PQS-MOS-Verlust ≤ 0.05)
- quality_estimate ≥ 0.55 im E2E

## Test-Pattern (Vorlage)

```python
import numpy as np
import pytest

class TestPhaseXX:
    """Tests for phase_XX_name."""

    @pytest.fixture
    def mono_audio(self):
        return np.random.randn(48000 * 3).astype(np.float32) * 0.5

    @pytest.fixture
    def stereo_audio(self):
        return np.random.randn(2, 48000 * 3).astype(np.float32) * 0.5

    def test_output_shape_mono(self, mono_audio):
        result, meta = execute(mono_audio, 48000)
        assert result.shape == mono_audio.shape

    def test_output_shape_stereo(self, stereo_audio):
        result, meta = execute(stereo_audio, 48000)
        assert result.shape == stereo_audio.shape

    def test_no_nan_inf(self, mono_audio):
        result, _ = execute(mono_audio, 48000)
        assert np.isfinite(result).all()

    def test_clipped_output(self, mono_audio):
        result, _ = execute(mono_audio, 48000)
        assert np.max(np.abs(result)) <= 1.0

    def test_sample_rate_assertion(self, mono_audio):
        with pytest.raises(AssertionError):
            execute(mono_audio, 44100)

    def test_empty_audio(self):
        result, _ = execute(np.array([], dtype=np.float32), 48000)
        assert len(result) == 0

    def test_strength_zero_passthrough(self, mono_audio):
        result, _ = execute(mono_audio, 48000, strength=0.0)
        np.testing.assert_array_almost_equal(result, mono_audio, decimal=5)

    def test_metadata_fields(self, mono_audio):
        _, meta = execute(mono_audio, 48000)
        assert "phase_id" in meta
        assert "applied" in meta
```

## CI-Gate-Tests (RELEASE_MUST)

Diese Tests MÜSSEN grün sein für jeden Release:

| Test-Datei | Prüft |
|---|---|
| `test_no_docker_in_production_paths.py` | Kein Docker/Cloud |
| `test_competitive_ci_gate.py` | OQS vs iZotope RX 11 |
| `test_performance_budget_ci_gate.py` | RT-Limits |
| `test_combined_ml_memory_budget.py` | ML-Budget ≤ 12 GB |
| `test_hybrid_release_mode.py` | Fallback-Kaskaden |
| `test_full_pipeline_determinism.py` | Bitnahe Reproduzierbarkeit |
| `test_competitive_stratified_gate.py` | Material × Defektklasse |
| `test_stability_invariants.py` | 9 Stabilitäts-Punkte |
| `test_lyrics_guided_enhancement_gate.py` | §2.36 aktiv + Modellpfade |
| `test_external_mushra_artifact_contract.py` | Mini-MUSHRA Artefakt |

## Heavy-Test-Isolation

Tests mit ML-Modellen oder langen Laufzeiten:
```python
@pytest.mark.ml
@pytest.mark.slow
def test_sgmse_plus_inference():
    ...
```

Nur ausführbar mit: `pytest --run-heavy-tests`

## Task-Runner

| Task | Beschreibung |
|---|---|
| `pytest: Unit-Tests` | Schnell, tests/unit/ |
| `pytest: Chunk A` | unit + musical_goals |
| `pytest: Chunk B` | integration + normative + regression |
| `pytest: Chunk HEAVY` | ml + slow + e2e (manuell) |
| `pytest: Smoke-Test` | 50 Tests, maxfail=3 |

> Test-Standards: `.github/specs/07_quality_and_tests.md` §5.x
