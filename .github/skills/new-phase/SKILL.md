---
name: new-phase
description: "Implementiert neue Aurik-9-Phasen (01–64) und PMGG-Integration. Use when: phase, PMGG, Exclusions, PhaseResult, wrap_phase, _run_with_retry, strength, Wet/Dry, Phasen-Ausführung, CausalDefectReasoner."
argument-hint: "Welche Phase? (z.B. 'phase_03 Denoise optimieren', 'neue phase_58 erstellen')"
---

# Aurik 9 — Neue Phase implementieren / Phase ändern

## Phasen-Interface (Pflicht für jede Phase)

Jede Phase liegt in `backend/core/phases/phase_XX_<name>.py` und MUSS:
- `def execute(audio, sr, strength=1.0, **kwargs) -> tuple[np.ndarray, dict]` exportieren
- `assert sr == 48000` am Eingang
- `audio = np.clip(audio, -1.0, 1.0)` am Ausgang
- `np.nan_to_num(result)` vor Return
- PhaseResult-dict mit mindestens: `phase_id`, `applied`, `strength`, `metadata`

## PMGG — PerPhaseMusicalGoalsGate (§2.29)

**Kernregel**: Jede Phase wird von PMGG gewrappt. PMGG misst Musical Goals vor/nach und entscheidet:

### §2.29d Differenziertes Regressions-Regime (v9.10.122)

**P1/P2** (Natürlichkeit, Authentizität, TonalCenter, Timbre, Artikulation): **Hart** — keine Phase darf diese verschlechtern. Volle Retry-Kaskade.

**P3–P5** (Emotionalität, MikroDynamik, Groove, Transparenz, Wärme, Bass, SepFidelity, Brillanz, Raumtiefe): **Pipeline-Netto-Budget** — Einzelphasen dürfen P3–P5 vorübergehend verschlechtern, wenn am Ende der Phasenkette alle Goals ≥ Schwellwert. PMGG loggt Zwischenregressionen, blockiert aber nicht.

**Begründung**: Reale Restaurierung erfordert Kompromisse. De-Hiss senkt kurzfristig Wärme, damit spätere Phasen auf sauberem Fundament bessere Wärme erzeugen. Per-Phase-Block auf P3–P5 erzwingt übervorsichtiges Wet/Dry (5 % statt 70 %) → Restlärm → Tiefen-Immersion zerstört.

### §2.45 Minimal-Intervention-Prüfung (v9.10.122)

**Restoration**: Vor Anwendung: `perceptual_delta = MERT_dist(before, after)`. Wenn `perceptual_delta ≤ 0` → Phase wird übersprungen (kein Nutzen). Ziel: so wenige Phasen wie nötig.

**Studio 2026**: Volle Enhancement-Kette aktiv, aber `perceptual_delta > 0` bleibt Pflicht. Auch Stem-Sep, Vocal-AI, Mastering-Phasen müssen messbaren Klanggewinn nachweisen. Kein Skip wegen Input-Ähnlichkeit — Ziel ist Studio-Qualität, nicht Input-Treue. Phasen ohne Klanggewinn → Skip (verhindert Over-Processing).

### Actions
- `"passed"` — keine Regression, Phase angewendet
- `"retry1"` … `"retry5"` — Regression erkannt, reduzierter Strength
- `"best_effort"` / `"best_effort_rN"` — nach 5 Fehlversuchen: geringstes Delta
- **VERBOTEN**: `"rollback"` / Return von unverändertem Original-Audio = Phase-Skip

### Priority-Aware Retries
| Prio | Retries | Regime | Verhalten |
|---|---|---|---|
| P1/P2 | 4 + Emergency | **Hart** (keine Regression) | Volle Kaskade, Catastrophic = `max(0.08, 4.0 × threshold)` |
| P3 | 2 (tier-adaptiv: good→3, poor→1) | **Netto-Budget** (Zwischen-Regression erlaubt) | Loggt Regression, blockiert nicht. MusicalGoalsChecker prüft am Kettenende |
| P4/P5 | 0 | **Netto-Budget** | Nur Logging (`passed_p4p5_tolerated`). Endprüfung am Kettenende |

### Regression-Threshold (restorability-adaptiv)
- GOOD: 0.020 | FAIR: 0.035 | POOR: 0.055
- Stagnation-Abbruch: `max(0.002, threshold × 0.15)`

### §2.29a Inference-Caching bei ML-Phasen
ML-deterministische Phasen: Erster Aufruf mit `strength=1.0` → Cache `audio_full`. Retries nur Wet/Dry-Blend:
`audio_retry = dry + strength × (audio_full − dry)`

**ML-deterministische Phasen** (gecachte Inferenz):
`phase_03` (OMLSA+ResembleEnhance), `phase_06` (AudioSR), `phase_09` (BANQUET),
`phase_12` (FCPE/CREPE), `phase_18` (Silero VAD), `phase_20` (SGMSE+),
`phase_23` (AudioSR Inpainting), `phase_24` (AudioSR), `phase_29` (DeepFilterNet),
`phase_42` (BSRoFormer), `phase_55` (CQTdiff/FlowMatching), `phase_56` (FCPE+Synthese)

**Strength-abhängige DSP-Phasen** (müssen bei Retry neu ausgeführt werden):
`phase_01`, `phase_02`, `phase_04`, `phase_10`, `phase_14`, `phase_17`, `phase_19`,
`phase_22`, `phase_25`–`phase_28`, `phase_31`–`phase_41`, `phase_43`–`phase_54`

### §2.43 Phase-Preserved Wet/Dry-Blend
STFT-Bereich: `M_blend = (1−α)·M_dry + α·M_wet`, Phase vom Wet-Signal.
Verhindert Phase-Cancellation bei Kopfhörer. Datei: `backend/core/unified_restorer_v3.py`

## PHASE_GOAL_EXCLUSIONS (v9.10.96, kanonisch)

| Phase | Ausgeschlossene Goals | Begründung |
|---|---|---|
| `phase_02` | bass_kraft, authentizitaet, natuerlichkeit, transparenz, groove, timbre_authentizitaet | Kammfilter Hum-Removal |
| `phase_03` | natuerlichkeit, artikulation, authentizitaet, tonal_center, timbre_authentizitaet | CREPE-Load-State + shaped NR |
| `phase_04` | transparenz, brillanz, waerme, authentizitaet, natuerlichkeit, timbre_authentizitaet | EQ |
| `phase_08` | micro_dynamics, artikulation | TDP/HPSS |
| `phase_12` | tonal_center, timbre_authentizitaet | K-S volatile nach Pitch-Korrektur |
| `phase_18` | micro_dynamics, authentizitaet, emotionalitaet, groove | Noise Gate |
| `phase_20` | authentizitaet, natuerlichkeit | SGMSE+ Reverb-Reduction |
| `phase_23` | natuerlichkeit, brillanz, authentizitaet, artikulation, timbre_authentizitaet | AudioSR synthetisiert |
| `phase_24` | natuerlichkeit, brillanz, authentizitaet, artikulation, timbre_authentizitaet | Dropout |
| `phase_29` | artikulation, authentizitaet, natuerlichkeit, tonal_center, timbre_authentizitaet | DeepFilterNet Tape-Hiss |
| `phase_49` | authentizitaet | Dereverb |

**Material-adaptive Relaxation**: `cd_digital`/`dat` → phase_03/phase_29 reduziert auf `{"natuerlichkeit", "artikulation"}`.

### §2.29b Stable-Metric-Invariante
`NatuerlichkeitMetric` **NIEMALS** in `_PRECISE_METRICS` — CREPE-Load-State ändert Gewichte.
Läuft nur im Export-Gate. Neue Metriken: Eigenrauschen ≤ 0.02 auf identischen Paaren nachweisen.

### §9.7.8 Audio-Cap
`_apply_precise_metric_overrides` kappt auf **2.5 s** — verhindert NMF/Onset-Runs auf Langaudio.

## §2.31b Song-Kalibrierungs-Integration (7 PMGG-Schnittstellen)

1. **Threshold**: `global_scalar < 0.85` → ×0.85; `> 1.20` → ×1.15. Begrenzt [0.015, 0.070]
2. **Retry-Leiter**: `initial_strength < 0.90` → Ankerpunkte `[0.80, 0.65, 0.50, 0.35, 0.20]`
3. **Stagnation**: `max(0.002, threshold × 0.15)`
4. **P3-Budget**: tier="good" → 3 Retries; tier="poor" → 1
5. **FeedbackChain target**: Base 0.72/0.78 ±0.035 nach restorability. Begrenzt [0.60, 0.85]
6. **Catastrophic**: `max(0.08, 4.0 × adaptive_threshold)`
7. **Material-adaptive Exclusions**: cd_digital/dat → reduzierter Satz

## Checkliste neue Phase

```
□ backend/core/phases/phase_XX_<name>.py
□ execute(audio, sr, strength=1.0, **kwargs) → (ndarray, dict)
□ assert sr == 48000
□ NaN/Inf-Guard + Clip [-1, 1]
□ PMGG-Exclusions festlegen + begründen
□ ML-deterministisch oder strength-abhängig? → Caching-Strategie
□ DSP-Fallback für optionale ML-Imports
□ ml_memory_budget.try_allocate() VOR Modell-Laden
□ PhaseResult-dict mit phase_id, applied, strength, metadata
□ defect_locations kwargs opt-in nutzen (§9.1)
□ §2.48 Interaktions-Check: Kumulative P1/P2-Drift < −0.05 → Rollback?
□ §2.49 Artefakt-Check: Musical Noise, Pre-Echo, Spectral Holes, Phase-Cancel = 0?
□ ≥ 35 Unit-Tests (Shape, NaN, Bounds, Mono, Stereo)
□ OQS ≥ 80 nachweisbar
□ CHANGELOG.md Eintrag
□ Alle bestehenden Tests grün
```

## PANNs Instrument-Aktivierungsmatrix

| PANNs-Kategorie | Phase | Schwellwert |
|---|---|---|
| Vocals / Singing | phase_19 + phase_42 + phase_43 | ≥ 0.40 / ≥ 0.35 |
| Guitar | phase_44 | ≥ 0.50 |
| Brass / Saxophone | phase_45 | ≥ 0.50 |
| Drum / Percussion | phase_51 | ≥ 0.50 |
| Piano / Keyboard | phase_52 | ≥ 0.50 |

## Vocal-Restaurierungskette (§2.8)

GenderDetector → SGMSE+ → FCPE/CREPE/pYIN → FormantTracker (LPC 30–40) → BreathDetector → De-Esser → VocalAIEnhancement → PSOLA

**API-Falle**: `enhanced, report = self.breath_intelligence.process(audio, sr)` — KEIN `events`-Argument!

**Vocal-Intimitäts-Gate (Phase 42)**: `vocal_intimacy_delta < -0.04` → Safety-Rescue-Blend.

## §2.36 LyricsGuidedEnhancement

Whisper-Tiny ONNX → wav2vec2 Alignment → Phonem-Segmentierung → ContentAwareProcessor.
Produktionsmodul: `backend/core/lyrics_guided_enhancement.py` (NICHT `backend/lyrics_guided/`).

**Phonem-DSP (§2.36a)**:
| Klasse | Algorithmus |
|---|---|
| fricative | Ramp-Gain 4–8 kHz, KEIN Wiener |
| plosive | TransientShapeGuard (onset gain=1.0), Burst ×1.40 |
| vowel_stressed | LPC Burg → F1–F4 Shelving |
| silence | OMLSA G_floor=0.05 |

**Datenschutz**: Lyrics-Text NIEMALS in Logs, Metadata, Checkpoints.

> Vollständige Phasen-Spezifikation: `.github/specs/06_phases_system.md`
> CAUSE_TO_PHASES-Mapping: `.github/specs/06_phases_system.md` §7.2
