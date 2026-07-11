# Aurik Spezifikation — §-Referenz-Index

> **852 eindeutige §-Referenzen** in `backend/core/`, `denker/`, `forensics/` (Schätzwert, Codebasis wächst).
> Dieser Index dokumentiert die häufigsten und architektonisch wichtigsten (derzeit ~105 Einträge).
> Neue §-Referenzen MÜSSEN hier eingetragen werden (Pre-Commit-Check).

## §-Kategorien

| Präfix | Bedeutung |
|---|---|
| `§0` | Fundamentale Invarianten (Primum non nocere, NaN/Inf, LAG) |
| `§1-4` | Architektur (Module, Singletons, Contracts, Threading) |
| `§2` | UV3-Kern (Kalibrierung, Phasen, Goals, DSP) |
| `§4` | Phasen-spezifische Regeln |
| `§6` | Forensik (Medium-Detector, Defekt-Scanner, Era-Klassifikator) |
| `§7-8` | Pipeline-Intelligenz (CausalReasoner, Optimizer) |
| `§9` | Qualitäts-Metriken (Goal-Scoring, PQS, MOS) |
| `§V` | Vintage-Ästhetik-Guards (Soft-Saturation, Wärmeband, etc.) |
| `§SFT/UQ/AC/AF` | Subsysteme (Safety, Uncertainty, Phase-Pruning, Cross-Guard) |

---

## Fundamentale Invarianten (§0)

| §Ref | Bedeutung | Dateien |
|---|---|---|
| `§0` | Primum non nocere — keine Verschlechterung | UV3 |
| `§0a` | NaN/Inf-Schutz auf allen Ein- und Ausgaben | UV3 |
| `§0p` | Vocal-Focus-Analyzer: Singstimme erkennen und schützen | UV3, VFA |
| `§0c` | Short-Clip-Handling (< 10s): reduzierte Analyse | UV3 |
| `§0d` | LAG-Probe: Sample-genaue Latenzmessung | UV3 |
| `§0h` | Stereo-L/R-Konsistenz | UV3 |
| `§0j` | DC-Offset-Erkennung vor DSP | UV3 |
| `§0l` | Phasen-Linearität bewahren | UV3 |
| `§0b` | Mode-Alias-Guard (copilot-instructions) | UV3 |
| `§0f` | Estimator-Error-Fallback (stiller Rückfall) | UV3 |
| `§0k` | HPI-Ceiling-Guard / Maximum-Achievable-Score | UV3, CDAS, APR |
| `§0m` | Confidence-Sources (3 Evidenzquellen für Konfidenz) | MD, UV3 |

## Architektur (§1-4)

| §Ref | Bedeutung | Dateien |
|---|---|---|
| `§2.8` | UV3 REST API Contract | UV3 |
| `§2.29` | PMGG Datenfluss-Invariante (Restorability) | UV3 |
| `§2.31` | MidCalibrate: Progress-basierte Rekalibrierung | UV3 |
| `§3.1` | NaN/Inf-Schutz (normativ) | UV3, Denker |
| `§3.2` | Singleton-Pattern (Thread-Safe, Double-Checked Locking) | Alle Denker |
| `§4.4` | Phase-Executor: OOM-Probe, PLM, Wall-Budget | UV3 |
| `§4.5` | Phase-ID-Validierung | UV3 |
| `§4.11` | Phase-Verbote (kein Denoise auf NR-Output, etc.) | UV3 |
| `§4.11a` | Pre-Echo-Thresholds (menschliche Hörschwelle) | PED |

## UV3-Kern (§2) — Kalibrierung & Phasen

| §Ref | Bedeutung | Dateien |
|---|---|---|
| `§2.44` | Per-Phase-Musical-Goals-Gate (PMGG) | UV3, PMGG |
| `§2.45` | Pegel-Monitoring (Pre/Post-Pegel pro Phase) | UV3 |
| `§2.45a` | Pegel-Drop-Guard (±0.5 dB Toleranz) | UV3 |
| `§2.46` | Tilt-Cap (Spektrale Neigungs-Begrenzung) | UV3 |
| `§2.46a` | Carrier-Chain-Invariante | UV3 |
| `§2.46b` | Source-Fidelity Spectral Tilt | UV3 |
| `§2.46e` | Room-Acoustics-Fingerprint | UV3 |
| `§2.46f` | Blind-Internal-Reference (BIR) | UV3 |
| `§2.47` | Material-Defect-Consistency | UV3 |
| `§2.48` | Cumulative-Interaction-Guard (CIG) | UV3 |
| `§2.49` | Artifact-Freedom (IAD-gate) | UV3 |
| `§2.51` | Phase-Skipping (deterministischer PID-Executor) | UV3 |
| `§2.54` | Effective-Targets (Physical-Ceiling) | UV3 |
| `§2.55` | Excellence-Optimizer (Core-Guard) | UV3 |
| `§2.56` | Song-Goal-Importance (Genre/Era/Material) | UV3, SGI |
| `§2.59` | **Contract-Validierung & Defekt-Namen-Sync (NEU 2026-07-09)** | CV, DM, SP |
| `§2.62` | Feedback-Chain (Post-Phasen-Retries) | UV3 |
| `§2.64` | Goal-Defizit-Feedback-Chain | UV3 |
| `§2.30b` | Macro-Dynamics-Guard (Quiet-Zone, Per-Sample) | UV3, MDEM, AU |
| `§2.31a` | Base-Target-Fine-Tuning (SongSelbstkalibrierung) | UV3, SGC |
| `§2.36a` | PhonemeTimeline (Phonem-spezifische DSP) | PT, LGE, MDEM |
| `§2.51a` | Stereo-No-Surprises-Guard (Hard-Fail/Warning) | UV3, AU |
| `§2.65` | MAS-Convergence (Early-Stop bei Zielerreichung) | UV3, APR |
| `§2.67` | Koalitions-Priorisierung (gekoppelte Phasen) | UV3, DPM, PSO |
| `§2.68` | SSIP (Signal-Flow Integrity Protocol) | SSI, UV3 |

## Forensik (§6)

| §Ref | Bedeutung | Dateien |
|---|---|---|
| `§6.2a` | Carrier-Chain-Invariante (Tape-Stufe in mp3-Chain) | UV3 |
| `§6.2c` | Dolby-NR-Erkennung | MD |
| `§6.3` | DefectScanner: 62 DefectTypes | DS |
| `§6.7` | Medium-Detector: Bayesian-Fusion (v9.10.97) | MD |
| `§6.7b` | File-Extension-Prior (Digital vs Analog) | MD |
| `§6.8` | Era-Precursor (reel_tape-Injektion) | UV3 |
| `§6.1` | Material-Key-Normalisierung (kanonisches Mapping) | MD, TD |
| `§6.1b` | Letzter-Analog-Träger-Primärprinzip | MD |
| `§6.7.1` | Pflicht-Spektralfingerabdruck (5 Basis-Features) | MD |
| `§6.7.2` | Ketten-Erkennung (Transfer-Chain) | MD |
| `§6.7.3` | Erweiterte Features (Rotation, Infrasonic, Codec) | MD |
| `§6.7e` | Multi-Kandidaten-Gate | MD |
| `§6.7f` | Vorläufer-Analog-Gate (Precursor-Stufen) | MD |
| `§6.9a` | Normative Literatur-Referenz (wissenschaftlich) | MD |

## Qualitäts-Metriken (§9)

| §Ref | Bedeutung | Dateien |
|---|---|---|
| `§9.5` | Quality-Tracking (Vorher/Nachher-Baseline) | UV3 |
| `§09.2` | Song-Goal-Targets (Era/Material/Studio-Mode) | UV3 |
| `§9.12.7` | Vintage-Material-Floor (Brillanz-Ceiling nach Träger) | UV3, PCE, EAPC, SGT |
| `§9.12.8` | Material-adaptive Metriken (Wärme, Brillanz, TQC) | UV3, CM, MRB, TQC |

## Pipeline-Intelligenz (§7-8)

| §Ref | Bedeutung | Dateien |
|---|---|---|
| `§7.6` | Chunk-Size (Defekt-adaptive Verarbeitung) | SD, AD, ACP, UV3 |
| `§7.6a` | Chunk-Boundary-Transient-Guard | ACP |
| `§8.2` | Emotional-Arc-Preservation (Tonart, LUFS, Chroma) | UV3, EXP, BSB |
| `§8.3` | Gänsehaut-Formel (Goosebumps-Quality-Check) | GQC, EAP, MDEM, LGE |

## Vintage-Ästhetik (§V)

| §Ref | Bedeutung | Dateien |
|---|---|---|
| `§V19` | Noise-Texture-Detector (erhält Rausch-Charakter) | UV3 |
| `§V24` | Tilt-Cap: Spektrale Balance bewahren | UV3 |
| `§V38` | Soft-Saturation-Guard (Röhren/Tape-Charakter) | UV3 |
| `§V40` | Wärmeband-Guard (200-800 Hz) | UV3 |
| `§V41` | Referenz-Konsistenz (kein Oversmoothing) | UV3 |

## Subsysteme

| §Ref | Bedeutung | Dateien |
|---|---|---|
| `§AC` | Intelligent Phase Pruning | PP |
| `§AF` | Cross-Guard (Denker-Teamwork) | UV3 |
| `§SFT` | Safety-Session-Tracker | UV3 |
| `§UQ` | Uncertainty-Quantification (Pipeline-UQ) | UV3 |
| `§SLR-1` | Lyrics-Guided-Enhancement | UV3 |
| `§CHT-1` | Cumulative-Hallucination-Tracker | UV3 |
| `§PID` | Phase-Interaction-Denker-Plan | UV3, PID |
| `§CSTC` | Cross-Segment-Timbral-Coherence | UV3 |
| `§v10` | Mode-aware Features (Pleasantness-First) | SD, RD, UV3 |
| `§v10.1` | Mode-Aware-Plugin-Routing | QFL, RDA, RD |
| `§v10.5` | PerceptualQualityCouncil & Guard-Auditing | PQC, GEA, PMGG |
| `§HPE` | Human Pleasantness Estimator | HPE |
| `§Gap5` | BlindInternalReference (Studio-Console-Character) | BIR, UV3 |
| `§Gap6` | Perceptual-Reference-Anchor-Matcher | RAM, UV3 |
| `§AJ` | AntiMufflingPass (Dumpfheit-Entfernung) | AMP, UV3 |
| `§C10` | Goal-Feedback (Bayesian EMA Kalibrierung) | SGI, BRD, UV3 |
| `§DSD` | DSD/DSF/SACD-Import-Support | MD |
| `§LSM-1` | Lyrics-Semantics-Model (NLP-Sentiment) | LSA, LGE |
| `§Spektrogramm` | Spektrogramm-Feedback (JSON für GUI) | SPV |
| `§Rolls-Royce` | Hörmüdung/Vision (Phantom-Mode, Comfort) | CG, BP, PM, VQG |
| `§VERBOTEN` | np.corrcoef-Guard (NaN auf konstanten Signalen) | DSP, ML |

---

## Legende der Datei-Abkürzungen

| Kürzel | Datei |
|---|---|
| UV3 | `backend/core/unified_restorer_v3.py` |
| MD | `forensics/medium_detector.py` |
| DS | `backend/core/defect_scanner.py` |
| PMGG | `backend/core/per_phase_musical_goals_gate.py` |
| SGI | `backend/core/song_goal_importance.py` |
| PP | `backend/core/phase_pruner.py` |
| CV | `backend/core/defect_contract_validator.py` |
| DM | `backend/core/defect_manifest.py` |
| SP | `backend/core/safe_dict.py` |
| VFA | `backend/core/vocal_focus_analyzer.py` |
| PID | `denker/phase_interaction_denker.py` |
| PT | `backend/core/phoneme_timeline.py` |
| LGE | `backend/core/lyrics_guided_enhancement.py` |
| MDEM | `backend/core/micro_dynamics_envelope_morphing.py` |
| AU | `backend/core/audio_utils.py` |
| SGC | `backend/core/song_calibration.py` |
| PSO | `backend/core/dsp/phase_strength_oracle.py` |
| DPM | `backend/core/defect_phase_mapper.py` |
| SSI | `backend/core/dsp/structural_silence_isolation.py` |
| APR | `backend/core/adaptive_phase_rescheduler.py` |
| PED | `backend/core/dsp/pre_echo_detector.py` |
| CDAS | `scripts/continuous_deep_analysis.py` |
| TD | `denker/tontraeger_denker.py` |
| PCE | `backend/core/physical_ceiling_estimator.py` |
| EAPC | `backend/core/era_authentic_perceptual_completion.py` |
| SGT | `backend/core/studio_goal_targets.py` |
| CM | `backend/core/calibration_matrix.py` |
| MRB | `benchmarks/musical_restoration_benchmark.py` |
| TQC | `backend/core/temporal_quality_coherence.py` |
| SD | `denker/strategie_denker.py` |
| AD | `denker/aurik_denker.py` |
| ACP | `backend/core/adaptive_chunk_processor.py` |
| EXP | `backend/exporter.py` |
| BSB | `benchmarks/competitive/benchmark_suite.py` |
| GQC | `backend/core/goosebumps_quality_checker.py` |
| EAP | `backend/core/emotional_arc_preservation.py` |
| QFL | `backend/core/quality_feedback_loop.py` |
| RDA | `backend/core/regulator/_dsp_applier.py` |
| RD | `denker/restaurier_denker.py` |
| PQC | `backend/core/perceptual_quality_council.py` |
| GEA | `backend/core/guard_effectiveness_auditor.py` |
| HPE | `backend/core/human_pleasantness_estimator.py` |
| BIR | `backend/core/blind_internal_reference.py` |
| RAM | `backend/core/reference_anchor_matcher.py` |
| AMP | `backend/core/anti_muffling_pass.py` |
| BRD | `backend/api/bridge.py` |
| LSA | `backend/core/lyrics_sentiment_analyzer.py` |
| SPV | `backend/core/spectrogram_provider.py` |
| CG | `backend/core/comfort_guard.py` |
| BP | `backend/core/breath_preserver.py` |
| PM | `backend/core/phantom_mode.py` |
| VQG | `backend/core/vocal_quality_gate.py` |

---

## Wie neue §-Referenzen hinzufügen

1. Im Code: `# §2.XX Beschreibung`
2. In diesem Dokument: Eintrag unter der passenden Kategorie
3. Pre-Commit-Hook prüft: `scripts/compliance/check_spec_refs.py`

**Commit-Regel:** Kein Merge, wenn neue `§`-Referenzen nicht hier dokumentiert sind.
