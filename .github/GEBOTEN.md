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

## Teil E — Wohlklang & Reproduzierbarkeit (G41-G50)

| ID | Kategorie | PFLICHT | Erkennung |
|----|----------|---------|-----------|
| G41 | Pleasantness | HPE-Check MUSS vor/nach JEDER Phase laufen | `compute_pleasantness` |
| G42 | Consistency | Gleicher Input MUSS gleichen Output produzieren | `deterministic\|seed\|reproducible` |
| G43 | CLP | NR-Stärke MUSS CLP-Maske respektieren (2-5kHz) | `clp_max_attenuation\|CLPZone` |
| G44 | Whisper | Leise-Passagen (< -40dBFS) MÜSSEN geschützt werden | `whisper_detail\|whisper_preservation` |
| G45 | Dynamics | Nach Kompressor/Limiter MUSS Dynamik geprüft werden | `dynamics_preserver\|check_phase` |
| G46 | Adaptive | Goal-Schwellen MÜSSEN aus Materialphysik berechnet werden | `compute_adaptive_thresholds` |
| G47 | Version | Versionsnummer MUSS aus `version.py` kommen | `from backend.core.version import` |
| G48 | Error | Jeder `except`-Block MUSS die Exception loggen | `logger.\|exc_info=True` |
| G49 | Dither | 16-bit Export MUSS gedithert werden | `dither\|TPDF\|triangular` |
| G50 | PhaseOrder | Phasen-Reihenfolge MUSS materialabhängig sein | `phase_order.*material\|adaptive.*phase.*order` |

## Teil F — Runtime-Garantien (G51-G55)

| ID | Kategorie | PFLICHT | Erkennung |
|----|----------|---------|-----------|
| G51 | Watchdog | Watchdog MUSS in JEDEM Pipeline-Lauf aktiv sein | `WatchdogMonitor\|get_watchdog` |
| G52 | Timeout | Jede Phase MUSS ein Timeout haben | `timeout\|_MAX_PHASE_SECONDS\|phase_timeout` |
| G53 | Memory | Speicher-Limit MUSS vor ML-Modell-Ladung geprüft werden | `ml_memory_budget\|try_allocate\|memory_limit` |
| G54 | ColdStart | Cold-Start MUSS eigenes Zeitbudget haben | `COLDSTART\|_coldstart\|first_run` |
| G55 | GPUFallback | Nach GPU-Fehler MUSS ONNX auf CPU weitermachen | `CPUExecutionProvider\|cpu.*fallback.*onnx` |

## Teil G — Ketten-Intelligenz (G56-G60)

| ID | Kategorie | PFLICHT | Erkennung |
|----|----------|---------|-----------|
| G56 | Chain | Transfer-Ketten (tape→mp3) MÜSSEN erkannt werden | `transfer_chain\|chain_string\|Tontraegerkette` |
| G57 | Bandwidth | ÄLTESTER Träger bestimmt Bandbreiten-Ziel | `oldest.*carrier\|primary.*bandwidth\|original.*medium` |
| G58 | Codec | Codec-Artefakte (MP3/AAC) MÜSSEN getrennt behandelt werden | `codec.*artifact\|mpeg.*frame\|mp3.*artifact` |
| G59 | Dolby | Dolby-NR-Typ MUSS vor Rauschunterdrückung erkannt werden | `DolbyNR\|dolby_nr\|dolby_type` |
| G60 | RIAA | RIAA-EQ MUSS vor Vinyl-Verarbeitung invers angewendet werden | `RIAA\|riaa_eq\|riaa_curve` |

## Teil H — Vokal-Garantien (G61-G65)

| ID | Kategorie | PFLICHT | Erkennung |
|----|----------|---------|-----------|
| G61 | Primus | Bei panns_singing ≥ 0.25: Stimmqualität VORRANG | `panns_singing.*0\\.25\|primus.*inter.*pares\|vocal.*priority` |
| G62 | Formant | Formant-Integrität MUSS nach Vokal-Phase geprüft werden | `formant.*guard\|formant.*integrity\|vocal_formant` |
| G63 | Sibilance | Sibilanten MÜSSEN nach De-Essing unterscheidbar bleiben | `sibilance.*preserv\|deesser.*intelligibility\|sibilant` |
| G64 | Vibrato | Vibrato MUSS erhalten bleiben | `vibrato.*preserv\|vibrato.*guard\|vibrato_continuity` |
| G65 | Breath | Atemgeräusche MÜSSEN als musikalisch intentional gelten | `breath.*preserv\|breath.*emotion\|breath.*intentional` |

## Teil I — Qualitäts-Garantien (G66-G70)

| ID | Kategorie | PFLICHT | Erkennung |
|----|----------|---------|-----------|
| G66 | Export | Vor Export: artifact_freedom ≥ 0.95 UND pleasantness ≥ 0.35 | `artifact_freedom.*0\\.95.*pleasantness\|export.*guard` |
| G67 | PleasantnessGate | Wenn Pleasantness SCHLECHTER → Original ausgeben | `pleasantness.*worse\|hpe.*rollback\|restored.*worse` |
| G68 | Regression | Jede Spec-Änderung MUSS einen Regression-Test haben | `test.*regression\|regression.*test\|spec.*test` |
| G69 | Agent | KI-Agenten MÜSSEN SpecConstitution nutzen | `get_constitution\|SpecConstitution\|spec_constitution` |
| G70 | VersionCheck | Keine hartcodierten Versionsnummern | `__version__\|AURIK_VERSION\|from.*version import` |
