# Aurik 10 — Weltklasse-Audio-Restaurierung

**Ziel:** Intelligente Musikwiederherstellung mit psychoakustischer Präzision, deterministischer Reproduzierbarkeit und vollständiger Ausrichtung auf den natürlichen Wohlklang für das menschliche Ohr.

## 🚀 v10 Invarianten

- **Bridge-Bypass-Verbot**: Kein Frontend-Code importiert `backend/core/` direkt. Nur über `backend/api/bridge.py`.
- **Soft-Knee-Gate**: `apply_musical_gain_envelope()` arbeitet mit Sigmoid-Soft-Knee (6dB), 200ms Hanning-Crossfade. KEIN Hard-Clamp.
- **PIM-first**: Vor jedem Phasen-Loop wird die PIM-Intensitäts-Map berechnet und in `restoration_context` gespeichert.
- **RLP-last**: Nach jedem Phasen-Loop wird der RLP ausgeführt. Korrekturen werden nur bei objektiver Verbesserung übernommen.
- **ML-Fallback-Logging**: JEDER ML→DSP-Fallback MUSS mit `logger.warning()` protokolliert werden. Silent-Failures sind VERBOTEN.
- **Artistic Intent vor Defect-Scan**: `get_artistic_intent()` wird VOR dem Defect-Scan aufgerufen.
- **Glue Stage immer**: Die Glue-Stage läuft in ALLEN Modi als vorletzte Phase.
- **62 DefectTypes**: Keine willkürlichen neuen DefectTypes ohne Phase-Mapping und Material-Sensitivity.

### v9.20.3 Präzisions-Invarianten

- **Centralized Decision Intelligence (§2.16)**: Alle Stärke-Entscheidungen fließen zentral im Denker.
- **Section-Strength-Envelope (§2.17)**: Kontinuierliche 48kHz-Hüllkurve, Cosine-Crossfade 200ms.
- **Physical-over-Statistical (§6.8)**: Physikalische Evidenz schlägt statistische Priors.
- **Fragile-Material-Guard (§2.15)**: bw_loss ≥ 0.90 ∧ SNR < 16dB → global_scalar ≤ 0.70.
- **Bandwidth-Loss-Guard (§2.12)**: global_scalar −25% proportional zu bw_loss.
- **Uncertainty-from-Disagreement (§2.13)**: Detektor-Divergenz → global_scalar ×0.90.
- **Bayesian-Physical-Fusion (§6.8)**: Bayesian unknown > 0.9 → Physical als Primary.
- **Quality-Gate→Action (§2.14)**: PQS-MOS < 2.5 → Rollback-Signal.
- **Onset-Preservation-Guard (§2.14)**: ≥90% Onsets → Score-Override.
- **Chain-Aware Defect Differentiation (§6.7)**: Chirurgische Schwellwerte pro Tonträger.
- **Multi-Generation Era Ceiling (§2.13)**: Analog-Träger-Produktionszeiträume.
- **Vocal Analysis Shared Memory (§2.9)**: VFA → restoration_context.
- **Phonem-Adaptive De-Essing (§2.9)**: Dynamische Band-Mittenfrequenz.
- **Spectral Dynamic EQ (§2.10)**: Pro-FFT-Bin Soft-Knee, Soothe2-Niveau.
- **Librosa pYIN Gender (§2.11)**: Voicing-Confidence + Contralto-Erkennung.

### v10 Roadmap (spezifiziert, nicht implementiert)

| § | Konzept | Beschreibung |
|---|---|---|
| §3.0 | **Cross-Phase Naturalness Consensus** | Phasen im gleichen Frequenzbereich stimmen sich ab. Naturalness-Guard prüft kumulative Wirkung |
| §3.1 | **SectionStrengthEnvelope aktiv** | Phase 19, 38, 18 lesen die bereits injizierte Envelope |
| §3.2 | **Artist/Track-Fingerprint** | BatchSessionLearner persistiert Stimm-Modell + Track-Modell für Transfer |
| §3.3 | **Blind Reference-Free Quality** | MERT-Embedding-basierte absolute Qualitätsschätzung ohne Vergleich zum degradierten Original |
| §3.4 | **Dynamic Phase Ordering (DAG)** | Volles DAG-basiertes Phase-Reordering, materialabhängig |
| §3.5 | **Real-time Preview** | 10s in ~30s vorab restaurieren zur Validierung |
| §3.6 | **Human-Panel MUSHRA** | Ridge-Regression auf echten Hörtest-Daten → kalibrierter MUSHRA-Proxy |

## 🎯 Kernwerte

- **Präzision über Geschwindigkeit** — Akustische Wahrheit zuerst
- **Transparenz** — Jede Entscheidung ist nachvollziehbar
- **Konsistenz** — Derselbe Input → derselbe Output (immer)
- **Wissenschaftlichkeit** — SOTA-Modelle, verifiable Metriken
- **Natürlichkeit** — Vollständige Ausrichtung auf den Wohlklang für das menschliche Ohr
- **Chirurgie** — Jeder Defekt wird mit dem exakt richtigen Werkzeug in der exakt richtigen Intensität behandelt

## 📊 Architektur-Ebenen

```
CLI (denker/aurik_cli.py)
  ↓
Bridge API (backend/api/bridge.py) [Mode-Normalisierung]
  ↓
Denker-Schicht (denker/*.py) [ZENTRALE ENTSCHEIDUNGSINTELLIGENZ]
  ├─ AurikDenker         — Orchestrierung, GlobalPlan
  ├─ StrategieDenker     — Budget, Performance
  ├─ DefektDenker        — CausalDefectReasoner
  ├─ PhaseInteractionDenker — Phasen-Ordnung, Konflikte
  ├─ ReparaturDenker     — Pre-UV3 Reparatur
  ├─ RekonstruktionsDenker — Gap-Reparatur
  ├─ RestaurierDenker    — UV3-Instanz, Core-Skalierung
  └─ ExzellenzDenker     — Musical Goals, Goal-Repair
  ↓
UnifiedRestorerV3 (backend/core/unified_restorer_v3.py)
  ├─ SongCalibration     — global_scalar, family_scalars, ALLE Guards
  ├─ SectionStrengthEnvelope — kontinuierliche per-Segment-Hüllkurve
  ├─ Phase-Selektion     — Preservation Mode, Risk-Guard
  └─ _profiled_phase_call — zentrale Envelope-Injektion
  ↓
Kernmodule [Psychoakustik + DSP]
  ├─ Defekt-Scanner (backend/core/defect_scanner.py)
  ├─ Medium-Detector (forensics/medium_detector.py)
  ├─ Era-Classifier (backend/core/era_classifier.py)
  ├─ Phasen-Engine (backend/core/phases/)
  ├─ Musikalische Ziele (backend/core/musical_goals/)
  ├─ Vocal-Analyse (backend/core/vocal_focus_analyzer.py)
  ├─ DSP/Formanten (backend/core/dsp/)
  └─ ML-Bridges (backend/ml/inference_only/)
  ↓
Export (backend/exporter.py)
```

## 🔗 Chain-Architektur (v9.20.3)

Jeder Tonträger in der Kette treibt spezifische Entscheidungen:

```
reel_tape (Era-Precursor) → Bandbreiten-Ziel 18–20kHz, Studio-Dynamik
vinyl    (Physical)       → Primär-Material, RIAA-EQ, Knistern, Rotation
cassette (Physical)       → Transport-Bumps, Wow/Flutter, Bandsättigung
mp3_low  (Physical)       → IQR-Guard, Bandbreiten-Cap, Pre-Echo-Schutz
```

**Chain-Awareness über alle Detektoren hinweg:**
- MediumDetector → physikalische Chain + `physical_analog_sources`
- EraClassifier → `material_prior` als Precursor (nicht als Primary-Override)
- DefectScanner → kettenadaptive Schwellwerte für ALLE 20 Defekttypen
- SourceFidelityReconstructor → Bandbreiten-Ziel vom ältesten Träger
- Phase-Selektion → `reel_tape`-Precursor aktiviert Phase 06 (Frequency Restoration)

## ✅ Qualitäts-Gating

### 1. **Tests** (Ziel: 80%+ Abdeckung)

- Unit: schnell, isoliert, ≤1s
- Integration: echte Daten, ≤5s
- E2E: golden samples, ≤30s
- Contract: Bridge↔API Invarianten

### 2. **Typisierung** (mypy strict in Backend)

- Alle Backend-Funktionen: `def func(arg: Type) -> Type:`
- ML-Plugins: `ignore_errors = true` (extern)
- DSP-Core: Type-Hints für öffentliche APIs

### 3. **Linting** (ruff select=[E,W,F,I,N,UP,B,C4,SIM,RUF])

- Automatische Fixes: `ruff check --fix`
- Per-File-Ignores nur für bewusste DSP-Konventionen
- Pre-Commit: ruff, black, isort

### 4. **Konsistenz**

- **Imports:** isort (Black-kompatibel) → `from module import name`
- **Formatierung:** Black 120er Zeilenlänge
- **Namensgebung:** snake_case (PEP8), Math-Variablen (N, X, sr)

## 📝 Dateien-Struktur (v9.20.3)

```
backend/
  ├─ core/
  │  ├─ defect_scanner.py             # Audio-Defekt-Klassifizierung (62 Types)
  │  ├─ unified_restorer_v3.py        # Haupt-Orchestrator + SongCalibration
  │  ├─ singer_voice_model.py         # VFA-Daten-Integration (§2.9)
  │  ├─ vocal_focus_analyzer.py       # Register, Formanten, Vibrato, Style
  │  ├─ room_acoustics_fingerprinter.py
  │  ├─ era_classifier.py             # Multi-Gen-Era-Ceiling (§2.13)
  │  ├─ phases/
  │  │  ├─ phase_19_de_esser.py       # Phonem-adaptiv + Spectral Dynamic EQ
  │  │  ├─ phase_36_transient_shaper.py # Fragile-Skip (§2.15)
  │  │  ├─ phase_39_air_band_enhancement.py # Analog-Skip
  │  │  ├─ phase_40_loudness_normalization.py # Uniform Gain analog+vocal
  │  │  └─ phase_54_transparent_dynamics.py
  │  ├─ musical_goals/
  │  │  └─ musical_goals_metrics.py   # Onset-Preservation-Guard (§2.14)
  │  └─ dsp/
  │     └─ section_strength_envelope.py # Kontinuierliche Hüllkurve (§2.17)
  ├─ api/bridge.py
  └─ exporter.py

forensics/
  └─ medium_detector.py               # Bayesian-Physical-Fusion (§6.8)

denker/
  ├─ aurik_denker.py
  ├─ restaurier_denker.py             # Core-Skalierung (4 Kerne)
  ├─ exzellenz_denker.py
  └─ README.md
```

## 🚫 VERBOTEN

Siehe `.github/VERBOTEN.md` — nicht verhandelbarer Sicherheits- & Qualitäts-Katalog.

**v9.20.3 Ergänzung:** Workarounds sind VERBOTEN. Jede Lösung muss die Ursache beheben, nicht das Symptom umgehen. Phasen-Individuelle Schwellwerte sind VERBOTEN — alle Stärke-Entscheidungen fließen zentral über `global_scalar`.

## 🔗 Externe Ressourcen

- Spezifikationen: `.github/specs/`
  - `01_musical_goals.md` — 15 Musical Goals
  - `02_pipeline_architecture.md` — Pipeline-Ablauf, Modi
  - `11_decision_intelligence.md` — Denker, SongCalibration, SectionEnvelope, Roadmap
  - `13_human_ear_quality.md` — Klangqualität fürs menschliche Ohr, Roadmap
  - `14_completeness_and_perfection.md` — Fehlertoleranz, Deterministik, Export, Batch-Lernen, Roadmap
- Instruktionen: `.github/instructions/`
- Copilot-Verhaltensrichtlinien: `.github/copilot-instructions.md`
