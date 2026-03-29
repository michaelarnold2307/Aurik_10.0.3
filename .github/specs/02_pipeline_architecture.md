# Aurik 9 — Spec 02: Pipeline-Architektur

> Kanonischer Pipeline-Ablauf, RestorationResult-Spec, Restaurierungs-Modi,
> StemRemixBalancer, Studio-2026-Verarbeitungskette.

---

## §1.4 Restaurierungs-Modi

| Modus | Ziel | Charakteristik |
| --- | --- | --- |
| **`restoration`** | Originalgetreue Restauration | Erhalt des historischen Klangs, minimaler Eingriff, LUFS-Diff ≤ 1 LU, kein Harmonic-Exciter, GP `mode="restoration"` konservativ |
| **`studio2026`** | Highend-Studio-Klang | Modern, kräftig — PQS MOS ≥ 4.5, Brillanz ≥ 0.90, Bass-Kraft ≥ 0.88, GP `mode="studio2026"` aggressiv |

**Restoration-Modus Pflicht-Invarianten:**

- Chroma-Korrelation Original↔Restauriert ≥ 0.95
- LUFS-Differenz ≤ 1 LU
- Kein hinzugefügtes Harmonic-Exciter-Material

**Studio-2026-Modus Pflicht-Invarianten:**

- PQS MOS ≥ 4.5 (Weltklasse)
- Brillanz-Score ≥ 0.90 (verschärft)
- Bass-Kraft ≥ 0.88 (verschärft)

---

## §1.5 Studio-2026-Verarbeitungskette (kanonische Reihenfolge nach Defektkorrektur)

```text
1.  Stem-Separation (MDX23C lokal, Kim_Vocal_2/Kim_Inst)
2.  Vocals: VocalAIEnhancement (stimmtyp-adaptiv) + ConsonantEnhancement (Frikative adaptiv)
    + Vocal-Intimitäts-Gate (Pre/Post-Check; Rescue bei Delta < -0.04)
3.  Sub-Mix-Instrumente: genre-adaptiv (guitar/brass/piano/drums nach PANNs)
4.  Reference Mastering (optional): OT-Spektral-Matching, Chroma-Korrelation ≥ 0.92
5.  Multiband-Dynamik: phase_35_multiband_compression
6.  Präsenz & Air: phase_38 + phase_39 (> 12 kHz)
7.  Stereo-Imaging: phase_48 + phase_46
8.  EraAuthenticPerceptualCompletion (wenn Quell-BW < 10 kHz)
9.  Re-Stem-Mix: StemRemixBalancer.balance_remix() — KEIN nacktes vocals + instruments
    Invariante: |LUFS(mix) − L_orig| ≤ 0.3 LU guaranteed
10. Lautheit: phase_40 (−14 LUFS EBU R128)
11. True-Peak-Begrenzung: phase_47 (−1.0 dBTP)
12. Musical Goals: alle 14 Ziele prüfen (verschärfte Studio-Schwellen)
13. Vocos-Synthese (konditionell): wenn PQS-MOS < 4.3
    → vocos_mel_spec_24khz.onnx → HiFi-GAN → PGHI-ISTFT
```

### StemRemixBalancer (Pflicht nach getrennter Stem-Verarbeitung)

```python
class StemRemixBalancer:
    """Gain-korrigierter Re-Mix nach getrennter Stem-Verarbeitung.

    Algorithmus:
        1. Vor Separation: L_orig gesamt messen
        2. Vor Separation: vocal_weight via PANNs auf Original (max. 10-s-Excerpt)
           → vocal_weight MUSS vollständig feststehen BEVOR MDX23C startet
        3. Nach Verarbeitung: LUFS pro Stem messen (L_voc', L_inst')
        4. Gain-Korrektur:
           g_voc  = 10 ** ((L_orig_voc  − L_voc')  / 20)
           g_inst = 10 ** ((L_orig_inst − L_inst') / 20)
        5. Re-Mix: mix = g_voc · vocals + g_inst · instruments
        6. Final-Check: |LUFS(mix) − L_orig| ≤ 0.3 LU

    Invarianten:
        - Vocals/Instruments-Verhältnis: ΔdB ≤ ±0.3 dB vs. Original
        - Kein Clipping im Re-Mix (np.clip nach Summation)
        - TonalCenterMetric nach Re-Mix ≥ 98 % des Pre-Remix-Werts
        - Laufzeit: ≤ 0.5 s / Minute Audio
    """
    def balance_remix(self, vocals, instruments, original, sr, vocal_weight=0.5): ...
```

**Pflicht**: Kein nacktes `vocals + instruments` in `UnifiedRestorerV3`.
**Pflicht-Test**: `tests/unit/test_stem_remix_balancer.py` (≥ 20 Tests).

---

## §2.2 Pipeline-Ablauf (kanonisch, Code-genau)

### §2.2.1 Parallelisierungs-Invariante

- TIER 0 und TIER 1: IMMER sequenziell
- TIER 2–4: dürfen parallelisieren; Merge via `np.mean` NUR wenn gleiche Frequenzzone
- TIER 6: IMMER sequenziell (EQ → Polish → LUFS → TruePeak → Format)

```text
Audio-Eingang (mono/stereo, beliebige SR)
    ↓
[DCOffsetPreRemoval]  ← PFLICHT-VORSTUFE vor jeder FFT-Analyse (kein phase_30!)
    │ scipy.signal.lfilter([1, -1], [1, -0.9999]) — Hochpass-IIR 5 Hz
    │ Invariante: np.abs(np.mean(audio)) < 1e-6 nach Entfernung
    │ Begründung: DC-Offset verfälscht STFT Bin 0+1 und damit alle
    │   Spektralanalysen (OMLSA-Profil, DefectScanner, HarmonicPreservationGuard).
    │   phase_30 bleibt für Post-Kettenausgleich erhalten, ist aber KEIN Ersatz.
    ↓
[TransientDecoupledProcessing]  ← ZWEITER Schritt (nach DC-Entfernung)
    │ separate(audio, sr) → (audio_percussive, audio_harmonic)
    │ audio_percussive → NUR phase_01 + phase_27 (kein NR, kein EQ!)
    │ audio_harmonic → volle Pipeline
    ↓
[RestorabilityEstimator]  (< 5 s, optional)
    ↓
[EraClassifier]  → EraResult (decade, material_prior, confidence)
    ↓
[GermanSchlagerClassifier]  → SchlagerClassificationResult
    │ → aktiviert SCHLAGER_RESTORATION_PROFILE bei is_schlager=True
    ↓
[MediumClassifier]  → ClassificationResult (MaterialType, confidence)

  ⚡ PARALLEL (ThreadPoolExecutor max_workers=3):
    EraClassifier + GermanSchlagerClassifier + MediumClassifier gleichzeitig
    (ONNX gibt GIL frei → echte Parallelität)

    ↓
[MusikalischerGlobalplanDienst]  ← Stufe 4 (Cross-Phase-Reasoning)
    │ erstelle_globalplan(audio, sr, use_ml_classifiers=False)  [DSP-only]
    │ 13 Ära-Profile × 7 Genre-Modifikatoren → 17 Per-Phase-Adjustments
    │ Enrichment nach Stufe 8 mit era_decade (→ RestorationConfig.global_plan)
    ↓
[DefectScanner]  → DefectAnalysisResult (32 DefectTypes)
    ↓
[CausalDefectReasoner]  → RestorationPlan (34 Kausal-Ursachen)
    ↓
[UncertaintyQuantifier]  → confidence → GP-Bounds adj.
    ↓
[GPParameterOptimizer]  → propose_pareto() → ParameterProposal (Pareto-Front)
    ↓
[HarmonicPreservationGuard]  ← NACH TDP, VOR phase_03/phase_29
    │ extract_harmonic_mask(audio_harmonic, sr) → protected_bins[t,f]
    │ G_floor = 0.85 an Harmonik-Bins, 0.10 sonst
    ↓
[UnifiedRestorerV3._select_phases()]
    ↓
[PerceptualEmbedder]  → AudioEmbedding (256-dim L2, Pre-Fingerprint)
    ↓
[Phasen-Ausführung]  ← jede Phase gewrapped durch PerPhaseMusicalGoalsGate
    │ 5-s-Sample → measure_quick(6 Ziele) → Rollback bei Δ > REGRESSION_THRESHOLD
    │ MAX_RETRIES = 5; STRENGTHS = [0.65, 0.50, 0.35, 0.20, 0.10]
    ↓
[EraAuthenticPerceptualCompletion]  (wenn Quell-BW < 10 kHz)
    ↓
[IntroducedArtifactDetector]  → ML_HALLUCINATION / NMF_RESIDUAL_CLICK / etc.
    ↓
[FeedbackChain.run()]  → iteriert bis PQS-MOS konvergiert || max_iterations
    ↓
[TemporalQualityCoherenceMetric]  (bei Dateien ≥ 25 s)
    ↓
[PerceptualQualityScorer]  → PQSResult (.mos, .nsim, .mcd_db, .spectral_coherence)
    ↓
[ExcellenceOptimizer]  → ExcellenceResult (GP-Params)
    ↓
[MusicalGoalsChecker]  → Dict[str, float] (alle 14 Ziele)
    ↓
[EmotionalArcPreservationMetric]  (bei Dateien ≥ 30 s)
    ↓
[MicroDynamicsEnvelopeMorphing]  ← LETZTER Schritt vor Export
    ↓
[GPParameterOptimizer.update()]  ← persistiert Lernerfolg
    ↓
Audio-Ausgang + RestorationResult
```

---

## Kanonische RestorationResult-Definition

```python
@dataclass
class RestorationResult:
    # ── Pflichtfelder ────────────────────────────────────────
    audio:                np.ndarray
    config:               "RestorationConfig"
    material_type:        "MaterialType"
    defect_scores:        dict["DefectType", float]
    phases_executed:      list[str]
    phases_skipped:       list[str]
    total_time_seconds:   float
    rt_factor:            float
    quality_estimate:     float   # = 0.40·(1−defect_severity) + 0.60·(pqs_mos−1)/4
    warnings:             list[str]
    metadata:             dict[str, Any]
    # ── Optionale Felder ─────────────────────────────────────
    pqs_result:           Optional[Any] = None    # .mos, .nsim, .mcd_db, .spectral_coherence
    musical_goals:        Optional[dict[str, float]] = None   # 14 Ziele → Score
    excellence:           Optional[Any] = None
    temporal_coherence:   Optional[Any] = None    # MOS-Spanne ≤ 0.30
    emotional_arc:        Optional[Any] = None    # Arousal/Valence Pearson
    restorability:        Optional[Any] = None    # 0–100
    confidence:           float = 1.0
    genealogy:            Optional[Any] = None
    harmonic_fingerprint: Optional[Any] = None    # 256-dim L2 Post-Fingerprint
    phase_gate_log:       Optional[list[str]] = None
    adaptive_thresholds:  dict[str, float] = field(default_factory=dict)
    physical_ceiling:     dict[str, float] = field(default_factory=dict)
    goal_applicability:   dict[str, bool] = field(default_factory=dict)
    goal_priority_log:    list[str] = field(default_factory=list)
    preview_mos:          Optional[float] = None
    era_decade:           Optional[int] = None
    # ── §2.38 KMV-Felder ─────────────────────────────────────
    deferred_phases:      list[str] = field(default_factory=list)   # Phasen die Stufe 2 benötigen
    refinement_complete:  bool = False                               # True nach ML-Veredelung
    stufe2_quality_estimate: Optional[float] = None                  # quality nach vollständigem ML-Pass
```

### §2.38a ML-Guard-Fallback-Metadaten (PFLICHT)

Wenn eine heavy ML-Stufe wegen RAM-Headroom-Guard nicht gestartet wird, MUESSEN strukturierte Metadaten geschrieben werden.

```python
metadata.setdefault("ml_guard_events", []).append(
    {
        "phase_id": "phase_20_reverb_reduction",
        "model": "SGMSE+",
        "reason": "insufficient_physical_ram_headroom",
        "required_gb": 9.0,
        "available_gb": 6.8,
        "channels": 2,
        "duration_s": 245.3,
        "fallback": "wpe_dsp",
    }
)
```

**Invarianten:**

- Kein Rollback auf Original-Audio als Guard-Reaktion.
- Phase bleibt ausgefuehrt (DSP/Fallback-Pfad) und wird in `phases_executed` gefuehrt.
- Betroffene Phase MUSS in `deferred_phases` eingetragen werden (Stufe-2-KMV-Nachzug).
- `metadata["ml_guard_events"]` ist JSON-serialisierbar und NaN/Inf-frei.

**quality_estimate-Formel (normativ):**

```python
quality_estimate = 0.40 * (1 - defect_severity) + 0.60 * (pqs_mos - 1) / 4
# VERBOTEN: * 1.15 Bonus; quality_estimate aus defect_severity allein
# Clip: max(0.0, min(1.0, quality_estimate))
```

**Serialisierungsregeln:**

- `audio`-Feld wird NICHT in JSON serialisiert
- NaN/Inf-Werte → `null` (via `clean_nans()`)
- `genealogy` → separates `<sha256_prefix>_genealogy.json`
- Neue Felder: immer mit Default `null`

---

## §2.29 PerPhaseMusicalGoalsGate — Adaptive Regression-Schwellen

**[RELEASE_MUST] PMGG darf Phasen NIEMALS überspringen (kein Rollback auf Original-Audio).**
CausalDefectReasoner hat die Phase als notwendig bestimmt — sie MUSS angewendet
werden, ggf. mit reduzierter Stärke (best-effort). Nach max. Retries wird der Versuch
mit der geringsten Musical-Goal-Regression angewendet (action=`best_effort`).

VERBOTEN: `return audio, scores_before, "rollback", 0.0` — Rückgabe von
unverändertem Original-Audio gleichbedeutend mit Phasen-Skip.

```python
# Schwellwerte restorability-adaptiv:
REGRESSION_THRESHOLD_GOOD: float = 0.020   # restorability ≥ 70 (v9.10.77: §9.7.5 Reference-Aware)
REGRESSION_THRESHOLD_FAIR: float = 0.035   # restorability 40–69
REGRESSION_THRESHOLD_POOR: float = 0.055   # restorability < 40
SAMPLE_DURATION_S: float = 5.0

# Priority-Aware Retry-Budget (v9.10.79):
_RETRY_STRENGTHS: list[float] = [0.65, 0.50, 0.35, 0.25, 0.15]   # 5 Stufen, Floor 0.15 (Last-Resort)
_PRIORITY_MAX_RETRIES: dict[int, int] = {1: 4, 2: 4, 3: 2, 4: 0, 5: 0}
_PRIORITY_THRESHOLD_FACTOR: dict[int, float] = {1: 1.0, 2: 1.0, 3: 1.5, 4: 99.0, 5: 99.0}
# P1/P2: volle Kaskade (4 Retries + Emergency)
# P3: max 2 Retries, 1.5× Regression-Toleranz
# P4/P5: kein Retry — nur Logging (action="passed_p4p5_tolerated")

# Schnell-Ziele (≤ 200 ms Gesamtcheck):
FAST_GOALS_SUBSET = [
    "natuerlichkeit", "authentizitaet", "tonal_center",
    "timbre_authentizitaet", "artikulation", "emotionalitaet",
    "micro_dynamics", "groove", "transparenz", "waerme",
    "bass_kraft", "separation_fidelity", "brillanz", "spatial_depth",
]
# Phasen-adaptive Sample-Dauer (§9.7.3):
PHASE_SAMPLE_DURATIONS = {
    "phase_30": 1.5,  "phase_05": 1.5,  "phase_02": 2.0,
    "phase_15": 1.5,  "phase_11": 1.5,  "phase_18": 2.0,
}

# Datenfluss-Invariante: restorability_score MUSS aus RestorabilityEstimator stammen:
re_result = RestorabilityEstimator().estimate(audio, sr, defect_analysis)
gate = PerPhaseMusicalGoalsGate()
for phase in selected_phases:
    audio, scores, _ = gate.wrap_phase(
        phase, audio, sr, scores_before,
        restorability_score=re_result.restorability_score,
        applicable_goals=goal_filter.applicable,
    )
# action ∈ {"passed", "retry1"..., "best_effort", "best_effort_rN", "passed_p4p5_tolerated"}
```

### §9.7.7 [RELEASE_MUST] PMGG Stable-Metric-Invariante (v9.10.79)

Metriken mit ML-zustandsabhängigem Gewicht **DÜRFEN NICHT** in `_PRECISE_METRICS` für PMGG-Delta-Checks stehen.

**Root-Cause `NatuerlichkeitMetric`**: CREPE-Load-State verändert die internen Gewichte zwischen
`scores_before` (CREPE nicht geladen → `w_crepe=0.0`) und `scores_after` (CREPE geladen → `w_crepe=0.18`).
Das erzeugt Pseudo-Regression Δ ≈ 0.15–0.28 auf unverändertem Audio, triggert die vollständige
P1-Retry-Kaskade (4 Retries + 2 Emergency) und erzwingt Phase_03 best-effort bei strength=0.056.

**Auswirkung auf Gänsehaut-Erlebnis**: Phase_03 bei 5.6 % Wet-Mix erreicht Noise Floor −55 dBFS
statt −72 dBFS. Der Air-Layer (8–20 kHz) und der Vokal-Intimität-Layer (4–8 kHz) bleiben unter
dem Rauschteppich verdeckt → kein „Ohr-in-die-Musik-Legen", keine Tiefen-Immersion.

**Invarianten**:

- `NatuerlichkeitMetric` läuft ausschließlich in `MusicalGoalsChecker` (Export-Gate), nie im PMGG-Delta.
- Neue Metriken vor `_PRECISE_METRICS`-Aufnahme: Eigenrauschen ≤ 0.02 auf identischen Audio-Paaren Pflicht.
- `_PRECISE_OVERRIDE_WARN_MS = 200.0` (angehoben von 120.0).

**Aktualisierte `PHASE_GOAL_EXCLUSIONS`** (v9.10.79):

```python
PHASE_GOAL_EXCLUSIONS: dict[str, set[str]] = {
    # Broadband denoise: spectral flatness + ZCR shift triggers CREPE-based
    # NatuerlichkeitMetric false P1 regression ~0.28 even at near-dry wet-mix.
    "phase_03": {"natuerlichkeit"},
    # Hum removal: comb-filter notches alter CREPE pitch confidence alongside bass/auth.
    "phase_02": {"bass_kraft", "authentizitaet", "natuerlichkeit"},
    # Dropout repair: synthesised gap-fill has no CREPE reference relation.
    "phase_24": {"natuerlichkeit"},
    # ... further entries as in backend/core/per_phase_musical_goals_gate.py
}
```

### §9.7.8 [RELEASE_MUST] Precise-Metric Audio-Cap (v9.10.79)

`_apply_precise_metric_overrides` kappt Audio auf **max. 2.5 s** vor dem Metric-Loop.

- Alle 7 verbleibenden präzisen Metriken (Brillanz, Wärme, TonalCenter, MicroDynamics,
  Artikulation, SeparationFidelity, Transparenz) sind spektral-stationär über kurze Fenster.
- Ohne Cap: `ArticulationMetric` (Short-Frame 5 ms Hop) und `SeparationFidelityMetric`
  (NMF) benötigen > 2 s/Call auf 60-s-Material → kumulative PMGG-Latenz 4+ s pro Phase.
- Mit 2.5 s Cap: alle 7 Metriken < 200 ms gesamt.

---

## §2.38 Kontinuierliche ML-Veredelung (KMV) — [RELEASE_MUST]

> **Kernprinzip**: Der PerformanceGuard verwirft überschrittene Phasen nie endgültig — er _deferriert_ sie.
> RT-Limit-Überschreitung führt zu DSP-Fallback für Sofort-Export **plus** automatischer Hintergrund-Veredelung.

### Zweistufiger Export-Ablauf

```text
Stufe 1 (Sofort-Export, RT-limitiert)
    │  Phasen die RT-Limit überschreiten: DSP-Fallback + in deferred_phases eingetragen
    │  Pipeline finalisiert; Qualitäts-Gate bestanden?
    │   └─ Nein → Stufe 1 abgebrochen (Fail-Reason in metadata)
    │   └─ Ja  → Atomischer Export (immediately listenable)
    │              Wenn len(deferred_phases) > 0:
    ↓
Stufe 2 (Hintergrund-ML-Veredelung, LIMIT_BACKGROUND = ∞)
    │  MLRefinementThread startet automatisch nach Stufe-1-Export
    │  Gecachte Analyse-Ergebnisse aus Stufe 1 (kein Neustart von DefectScanner,
    │    EraClassifier, MediumClassifier, GPParameterOptimizer)
    │  Vollständige UV3-Pipeline ohne RT-Limit (no_rt_limit=True)
    │  QThread.LowPriority + os.nice(10) auf Linux
    │  isInterruptionRequested() zwischen jeder Phase prüfen
    │  Qualitätsinvariante: quality(v2) ≥ quality(v1) → sonst alten Export behalten
    └→ Atomischer Export-Overwrite: result_v2.tmp → os.replace(output_path)
       signal: refinement_complete(output_path, final_RestorationResult)
```

### RAM-Guard (Stufe 2 Startbedingung)

```python
import psutil
avail_gb = psutil.virtual_memory().available / 1024**3
if avail_gb < 4.0:
    logger.warning("KMV Stufe 2 übersprungen: nur %.1f GB RAM verfügbar (< 4 GB)", avail_gb)
    return  # Stufe-1-Export bleibt permanent
```

### DeferredRefinementJob (Pflicht-Dataclass)

```python
@dataclass
class DeferredRefinementJob:
    """Queued job for background ML refinement (§2.38)."""
    output_path:          str                       # Pfad der Stufe-1-Exportdatei
    audio_original:       np.ndarray                # Original-Audio (unkomprimiert, pre-pipeline)
    sr:                   int                       # Sample-Rate (48000)
    mode:                 str                       # "restoration" | "studio_2026"
    deferred_phase_ids:   list[str]                 # Phasen die in Stufe 1 deferriert wurden
    cached_defect_result: Any                       # DefectAnalysisResult aus Stufe 1
    cached_era_result:    Any                       # EraResult aus Stufe 1
    cached_medium_result: Any                       # ClassificationResult aus Stufe 1
    stufe1_quality:       float                     # quality_estimate Stufe 1 (Mindest-Benchmark)
    created_at:           float = field(default_factory=time.time)
```

### MLRefinementThread — Signal-Kontrakt

```python
class MLRefinementThread(QThread):
    refinement_started    = pyqtSignal(str, int)    # output_path, n_deferred_phases
    refinement_phase_done = pyqtSignal(str, float)  # phase_id, quality_improvement_delta
    refinement_progress   = pyqtSignal(int, str)    # pct 0–100, phase_name
    refinement_complete   = pyqtSignal(str, object) # output_path, final_RestorationResult
    refinement_cancelled  = pyqtSignal(str)         # output_path → Stufe-1-Export bleibt
```

### Invarianten

- `LIMIT_BACKGROUND = float("inf")` ist ausschließlich für `MLRefinementThread` — niemals für BatchProcessingThread
- Atomisches Schreiben: `output_path.tmp` → `os.replace(output_path)` nach vollständigem Pass
- Kein Downgrade: `if stufe2_result.quality_estimate < job.stufe1_quality: skip_overwrite()`
- Single active refinement: Pro Prozess höchstens ein aktiver `MLRefinementThread`
- Escape-Abbruch: `requestInterruption()` → Stufe-1-Export bleibt unverändert erhalten
- `DeferredRefinementJob.audio_original` registriert in `ml_memory_budget` (Budget-Guard); freigegeben unmittelbar nach Stufe-2-Export oder Abbruch

## §2.39 OOM-Recovery-Checkpoint-System — [RELEASE_MUST]

**Kernprinzip**: `systemd-oomd`-Kill oder `MemoryError` führen nie zu Totalverlust. Pipeline-Zwischenstand wird atomar auf Disk persistiert und beim nächsten Start automatisch zur Wiederaufnahme angeboten.

### Checkpoint-Lifecycle

| Schritt | Komponente | Aktion |
| --- | --- | --- |
| 1 | `_execute_pipeline()` MemoryError-Handler | `save_checkpoint()` → `sessions/<stem>_oom_checkpoint.json` + `_oom_audio.wav` |
| 2 | `ModernMainWindow.__init__` (1,5 s QTimer) | `find_pending_checkpoints()` → Dialog "Restaurierung fortsetzen?" |
| 3 | Nutzer bestätigt | `_resume_from_checkpoint()` → Original laden → normale Restaurierung |
| 4 | Erfolgreicher Abschluss | `delete_checkpoint()` → Cleanup |

### Modul: `backend/core/recovery_checkpoint.py`

```python
@dataclass
class RecoveryCheckpoint:
    input_path: str
    output_path: str
    phases_executed: list[str]
    phases_remaining: list[str]
    mode: str                              # "restoration" | "studio_2026"
    material_type: str                     # MaterialType.value
    era_decade: int | None
    defect_scores: dict[str, float]        # {defect_type: severity}
    defect_scores_full: dict[str, dict]    # Full DefectScore with locations
    restorability_score: float | None
    spectral_fingerprint: dict[str, float]
    quality_estimate_at_failure: float
    musical_goals_at_failure: dict[str, float]
    audio_wav_path: str                    # FLOAT WAV (verlustfrei)
    sample_rate: int
    original_input_path: str
    timestamp: float
    aurik_version: str = "9.10.57"
    failure_phase: str = ""
    failure_reason: str = "MemoryError"
```

### Pfad-Durchleitung

```text
BatchProcessingThread
  → denke(input_path=, output_path=)
    → restauriere()
      → _orchestriere()
        → RestaurierDenker.restauriere()
          → UV3 restore(input_path=, output_path=)
            → self._recovery_ctx
              → _execute_pipeline MemoryError-Handler
                → save_checkpoint()
```

## §2.40 Vollpipeline-Determinismus (PFLICHT)

Die komplette UV3-Kette muss fuer identische Eingaben deterministisch reproduzierbar sein.

```python
# Determinismus-Vertrag (normativ)
assert max_abs_err <= 1e-6
assert rms_err <= 1e-7
assert result_a.phases_executed == result_b.phases_executed
```

Pflichtregeln:

- Alle Seeds zentral setzen und im Result-Metadata dokumentieren.
- Keine unseeded Zufallsfunktionen in Produktionspfaden.
- Vergleichslaeufe mit identischen Prozessparametern (Threads, Mode, Config).

## §2.41 Structured Fail-Reason Taxonomie (PFLICHT)

`RestorationResult.metadata["fail_reasons"]` ist eine Liste strukturierter Eintraege.

Pflichtfelder pro Eintrag:

- `phase_id`
- `reason_code` (z. B. `ml_guard_low_ram`, `goal_regression_p1`, `quality_gate_fail`)
- `severity` (`info|warning|error`)
- `action` (`fallback|retry|best_effort|blocked`)
- `details` (JSON-serialisierbar, NaN/Inf-frei)

**Invariante:** Kein freier String-only Fehlerpfad ohne reason_code in Kernmodulen.

## §2.42 [RELEASE_MUST] Pipeline-Stabilitäts-Kontrakt (v9.10.81)

Zusammenfassung aller Stabilitäts-Invarianten. Jede Verletzung einer dieser Regeln ist ein Release-Blocker.

| ID | Mechanismus | Spezifikation | Schutz gegen |
| --- | --- | --- | --- |
| S-01 | Per-Phase-Inference-Timeout | §3.9.1 spec 08 | BLAS-Deadlock, korruptes Modell |
| S-02 | SIGTERM-Handler + Emergency-Checkpoint | §3.9.2 spec 08 | Graceful OS-Shutdown ohne Datenverlust |
| S-03 | Phase-Output-Guard (`@phase_output_guard`) | §3.9.3 spec 08 | NaN/Inf-Propagation aus ML-Ausgaben |
| S-04 | ThreadPoolExecutor-Lifecycle (shutdown) | §3.9.4 spec 08 | Zombie-Threads, Ressourcen-Leaks |
| S-05 | ml_memory_budget Startup-Reconciliation | §3.9.5 spec 08 | Stale-Allokation nach SIGKILL |
| S-06 | Structured Exception Logging | §3.9.6 spec 08 | Stille Fehler, leer `fail_reasons` |
| S-07 | Audio-Buffer-RAM-Guard | §3.9.7 spec 08 | OOM durch sehr große Audio-Dateien |
| S-08 | Lock-Acquisition-Order (ARM→PLM→MLBudget) | §3.9.8 spec 08 | Deadlock zwischen ARM und PLM |
| S-09 | MLRefinementThread Buffer-Release in finally | §3.9.9 spec 08 | RAM-Leak bei KMV-Abbruch |
| S-10 | watchdog + requestInterruption → terminate() | §11.4 spec 08 | Freeze > 90 min (Desktop-Watchdog) |
| S-11 | OOM-Recovery-Checkpoint (MemoryError-Pfad) | §2.39 | Python MemoryError → kein Totalverlust |
| S-12 | §2.38 KMV Stufe 2 mit 4 GB RAM-Guard | §2.38 | OOM bei Hintergrund-ML-Veredelung |
| S-13 | §2.38a ML-Headroom-Guard vor ML-Load | §2.38a | OOM während Modell-Laden |
| S-14 | Hybrid-Release-Mode (primary/fallback/blocked) | §13 spec 08 | Crash durch quarantänisierte Modelle |
| S-15 | Atomic File Writes (.tmp → os.replace) | §3.1 spec 08 | Korrupte Ausgabedatei bei Abbruch |

### Stabilitäts-Priorisierung

- **S-01 bis S-09**: Neue Invarianten aus Tiefenanalyse v9.10.81 — RELEASE_MUST.
- **S-10 bis S-15**: Bestehende Invarianten — bereits implementiert, hier zur Referenz.

### Für jedes neue Kernmodul / jede neue Phase gilt zusätzlich (§9.1 Checkliste):

- `try`/`except` mit §2.41-konformem `fail_reasons`-Eintrag (S-06).
- `@phase_output_guard` oder äquivalente manuelle Absicherung (S-03).
- `ml_memory_budget.try_allocate()` vor ML-Load mit `release()` in Fehler-Pfad (S-13).
- Kein `ThreadPoolExecutor` ohne Shutdown in Cleanup (S-04).
- `_check_audio_buffer_size()` bei direktem `soundfile.read()` (S-07).

### Invarianten

- Checkpoint-Audio als `FLOAT` WAV — verlustfrei, kein Encoding-Verlust
- Ablauf: 7 Tage (`_MAX_CHECKPOINT_AGE_S`) — danach automatische Bereinigung
- Thread-safe: Alle Writes über `.tmp` + `os.replace` (POSIX-atomar)
- Datenschutz: Lyrics-Text NICHT im Checkpoint (§2.36 Pflicht)
- Wiederaufnahme nutzt das **Original-Audio** (nicht das Checkpoint-Audio) für volle Qualität
- Checkpoint-Audio dient als Fallback wenn Original fehlt
- **VERBOTEN**: Checkpoint-Audio als Primärquelle für Re-Restaurierung (Doppelverarbeitung degradiert Qualität)
