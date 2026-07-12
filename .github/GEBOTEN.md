# Aurik 10 — Vollständige GEBOTEN-Tabelle (PFLICHT-Regeln)

> **Normatives Gegenstück zu VERBOTEN.md**: Was MUSS vorhanden sein, nicht was verboten ist.

## Teil A — Code-Struktur (G01-G10)

| ID | Kategorie | PFLICHT | Erkennung |
|----|----------|---------|-----------|
| G01 | Logging | Jede .py-Datei MUSS `logger = logging.getLogger(__name__)` definieren | `logger = logging.getLogger` |
| G02 | NaN-Schutz | Jede Phase MUSS `np.nan_to_num()` auf Ausgabe-Audio anwenden | `nan_to_num` oder `isfinite` |
| G03 | Typisierung | Jede öffentliche Funktion MUSS Type-Hints haben | `def func(arg: Type) -> Type:` |
| G04 | Docstring | Jede öffentliche Funktion MUSS einen Docstring haben | `"""..."""` nach `def` |
| G05 | Dataclass | API-Rückgabewerte MÜSSEN `@dataclass` sein | `@dataclass` |
| G06 | Singleton | Singletons MÜSSEN `threading.Lock()` verwenden | `threading.Lock()` |
| G07 | ML-Fallback | Jedes ML-Plugin MUSS einen DSP-Fallback haben | DSP-Funktion nach ML-Try |
| G08 | GPU | GPU-Zugriff MUSS über `get_torch_device()` erfolgen | `get_torch_device` |
| G09 | Import | Audio-Import MUSS über `load_audio_file()` erfolgen | `load_audio_file` |
| G10 | Test | Jede Spec-§-Referenz MUSS einen Test haben | Testdatei mit §-Referenz |

## Teil B — Audio-Qualität (G11-G20)

| ID | Kategorie | PFLICHT | Erkennung |
|----|----------|---------|-----------|
| G11 | Loudness | Ausgabe MUSS LUFS-normalisiert sein (ITU-R BS.1770) | `loudness` oder `LUFS` |
| G12 | Zero-Phase | Filter auf Signal-Addition MÜSSEN `sosfiltfilt` verwenden | `sosfiltfilt` |
| G13 | Artifact | Ausgabe MUSS `artifact_freedom >= 0.95` erreichen | `artifact_freedom` |
| G14 | Vocal | Bei `panns_singing >= 0.25` MUSS VQI geprüft werden | `vqi` oder `vocal_quality` |
| G15 | DC-Offset | reel_tape MUSS `filtfilt([1,-1],[1,-0.9995])` verwenden | `filtfilt.*-0.9995` |
| G16 | Gate | Gate MUSS `reference_for_gate` verwenden | `reference_for_gate` |
| G17 | Peak | Peak-Guard MUSS `np.percentile(99.9)` verwenden | `percentile.*99.9` |
| G18 | Envelope | Gain MUSS `_musical_gain_envelope()` verwenden | `_musical_gain_envelope` |
| G19 | Material | Jedes `dict[MaterialType, ...]` MUSS ALLE Materialien enthalten | vollständiges Material-Dict |
| G20 | NR-Check | Nach NR MUSS `compute_nmr_score()` aufgerufen werden | `compute_nmr_score` |

## Teil C — Pipeline (G21-G30)

| ID | Kategorie | PFLICHT | Erkennung |
|----|----------|---------|-----------|
| G21 | Glue | Glue-Stage MUSS in ALLEN Modi laufen | Glue-Stage-Call |
| G22 | PIM | PIM-Intensitäts-Map MUSS vor Phasen-Loop berechnet werden | `pim` oder `perceptual_intensity` |
| G23 | RLP | RLP MUSS nach jedem Phasen-Loop ausgeführt werden | `rlp` oder `reflective_listening` |
| G24 | Export | Export MUSS `artifact_freedom >= 0.95` prüfen | Export-Gate |
| G25 | Warmup | ROCm-GPU MUSS beim Start gewarmupt werden | `warmup` oder `_ROCM_WARMUP` |
| G26 | Recovery | Nach GPU-Fehler MUSS CPU-Fallback erfolgen | GPU-Fehler→CPU |
| G27 | Budget | 8×RT-Budget MUSS eingehalten werden | `_3X_RT_LIMIT` |
| G28 | Checkpoint | Crash-Recovery MUSS Checkpoints speichern | `save_checkpoint` |
| G29 | Memory | ML-Memory-Budget MUSS vor Allocation geprüft werden | `ml_memory_budget` |
| G30 | Cross-Phase | Cross-Phase-Guards MÜSSEN nach jeder Phase prüfen | `CumulativeInteractionGuard` |

## Teil D — Tests & CI (G31-G40)

| ID | Kategorie | PFLICHT | Erkennung |
|----|----------|---------|-----------|
| G31 | Unit-Test | Jede Phase MUSS einen Unit-Test haben | `test_phase_*.py` |
| G32 | CI-Gate | CI MUSS `artifact_freedom`-Regression prüfen | CI-Config |
| G33 | Coverage | Test-Coverage MUSS ≥ 80% sein | `--cov` |
| G34 | Linter | Pre-Commit MUSS `ruff` + `mypy` ausführen | `.pre-commit-config.yaml` |
| G35 | Benchmark | Release MUSS AMRB-Benchmark bestehen | AMRB-Skript |
| G36 | Version | Änderungen MÜSSEN in CHANGELOG.md dokumentiert sein | CHANGELOG |
| G37 | Lock | Jeder `threading.Lock()` MUSS `with`-Statement verwenden | `with.*lock` |
| G38 | Path | Pfade MÜSSEN `pathlib.Path` verwenden | `Path(` |
| G39 | Encoding | Dateien MÜSSEN UTF-8 sein | `encoding="utf-8"` |
| G40 | License | Jede neue Datei MUSS den Aurik-Lizenzheader haben | Lizenzheader |
