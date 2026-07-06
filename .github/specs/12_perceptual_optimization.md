# Spec 12: Perceptual Optimization Patterns (§G–§Z)

> **Status:** Normativ · **Version:** Aurik 9.12.11 · **Scope:** Entscheidungsintelligenz, Klangqualität, Resilienz

## §12.1 Übersicht der Patterns

Aurik implementiert 20 Perceptual-Optimization-Patterns, die in 4 Gruppen organisiert sind.
Jedes Pattern ist vollständig implementiert und durch Unit-Tests abgesichert.

### Gruppe 1: Decision Intelligence (§G–§K)

| Pattern | Name | Datei | Funktion |
|---------|------|-------|----------|
| §G | Council Feedback Loop | `denker/aurik_denker.py` | Nach VERSA-MOS-Gate: max 2 Retries mit reduzierter Stärke |
| §H | Genre Goal Profiles | `backend/core/genre_goal_profile.py` | 15 Musical Goals × 18 Genres mit spezifischen Gewichten |
| §I | Multi-Segment ARE | `backend/core/autonomous_restoration_engine.py` | ARE evaluiert 3 Exzerpte (Anfang/Mitte/Ende) statt 1 |
| §J | Goal Budget | `backend/core/goal_budget.py` | Pre-Allokation pro Goal, Abbuchung nach jeder Phase |
| §K | Simplified Progress | `Aurik910/ui/modern_window.py` | 30 Hz-Timer, eine Formel, kein Monotonie-Guard |

### Gruppe 2: Klangwirksame Guards (§L–§Q)

| Pattern | Name | Datei | Trigger-Phasen |
|---------|------|-------|----------------|
| §L | Bass-Punch Coupling | `backend/core/klang_guards.py` | phase_37, phase_08 |
| §M | Vocal Formant Guard | `backend/core/klang_guards.py` | phase_03, phase_49 |
| §N | Stereo Coherence Guard | `backend/core/klang_guards.py` | phase_13, phase_14, phase_15 |
| §O | Dynamics Arc Guard | `backend/core/klang_guards.py` | phase_54 |
| §P | Defect EQ Profile | `backend/core/klang_guards.py` | Vor phase_16 |
| §Q | Listening Mode | `backend/core/unified_restorer_v3.py` | Pipeline-Start (headphones/nearfield/farfield/car) |

### Gruppe 3: Coordination & Humanity (§R–§T)

| Pattern | Name | Datei | Funktion |
|---------|------|-------|----------|
| §R | Cross-Guard Coordinator | `backend/core/klang_guards.py` | L–O gemeinsam: ≥2 Konflikte → reduzierte Stärke |
| §S | Emotional Arc Preserver | `backend/core/klang_guards.py` | Arousal/Valence-Korrelation über 16 Segmente |
| §T | Humanization Pass | `backend/core/klang_guards.py` | Anti-Fatigue: Mikro-Variation <0.3 dB, <0.5 ms |

### Gruppe 4: Intelligence & Learning (§U–§Z)

| Pattern | Name | Datei | Funktion |
|---------|------|-------|----------|
| §U | Phase Order Intelligence | `backend/core/phase_intelligence.py` | 12 akustische Kopplungsregeln optimieren PID-Plan |
| §V | Reference Track Matching | `backend/core/preference_learner.py` | Referenz-Audio → Zielkurve für Goal-Gewichte |
| §W | Preference Learner | `backend/core/preference_learner.py` | A/B-Präferenzen persistent lernen |
| §X | Stage Preview | `backend/core/production_enhancements.py` | 10s-Previews nach Pipeline-Meilensteinen |
| §Y | Codec-Aware Export | `backend/core/production_enhancements.py` | MP3/AAC/Opus/FLAC spezifische Optimierung |
| §Z | Batch Intelligence | `backend/core/preference_learner.py` | Batch-übergreifendes Lernen (Phase-Stärken, EQ) |

## §12.2 Integrationspunkte

Alle Patterns werden über `unified_restorer_v3.py` integriert:

- **§H, §J, §P, §Q, §V:** Vor `_execute_pipeline()` in `restore()`
- **§L–§O:** Nach jeder erfolgreichen Phase via `_apply_klang_guards()`
- **§R, §S:** Nach allen Phasen via `_finalize_klang_guards()`
- **§T:** Nach `_execute_pipeline()`, vor Export via `_apply_humanization_pass()`
- **§U:** Im `PhaseInteractionDenker.erstelle_phasenplan()` nach PID
- **§G:** Im `AurikDenker._orchestriere()` nach VERSA-MOS-Gate
- **§K:** Im `_tick_heartbeat()` des MainWindow über `_tick_uv3_simple_progress()`

## §12.3 Test-Abdeckung

- 285 Denker-Tests: Pipeline-Logik, Mode-Normalisierung
- 386 Musical-Goals-Tests: PMGG, Goal-Weighting, Regression
- 12 Defect-Detection-Tests: Scanner, Classifier
- 53 Normative Contract-Tests: GUI, Export, Stabilität
- **Gesamt: 1.683+ Tests bestanden**

## §12.4 Performance-Implikationen

| Pattern | Overhead | Begründung |
|---------|----------|------------|
| §H | <1 ms | Dict-Lookup, einmal pro Pipeline |
| §J | <1 ms | Dict-Lookup + Delta-Berechnung pro Phase |
| §L–§O | <50 ms | FFT-basierte Messungen, non-blocking |
| §T | <500 ms | Allpass + Modulation, einmal pro Pipeline |
| §G | Variabel | Max 2 zusätzliche UV3-Durchläufe |
