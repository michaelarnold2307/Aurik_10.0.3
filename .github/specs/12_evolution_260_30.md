# §EVO: Denker → UV3 Evolutionsstufen (§2.60–§3.0)

Stand: 2026-07-08 | Status: ✅ Implementiert

## §2.60 Fahrplan-Brücke — Denker-Kalibrierung fließt in UV3

**Dateien**: `backend/core/fahrplan.py`, `denker/phase_interaction_denker.py`, `backend/core/unified_restorer_v3.py`

- `build_fahrplan()` erstellt strukturierten Ausführungsplan mit per-Segment-Anweisungen
- `PhaseInteractionDenker.plan()` ruft `build_fahrplan()` und speichert Fahrplan in `policy_hints["fahrplan"]`
- UV3 liest Fahrplan via `denker_policy_input → phase_interaction → fahrplan` in `_profiled_phase_call`
- Fahrplan-Kalibrierung überschreibt `kwargs["strength"]` mit per-Phase gemittelter Stärke
- `PERCEPTUAL_BUDGET` und `PHASE_SUBSTITUTIONS` als Modul-Konstanten definiert

## §2.61 SectionGoalAdapter — Echte Musiksektionen

**Dateien**: `backend/core/section_goal_adapter.py`, `denker/aurik_denker.py`

- `get_sections()` — Wrapper um `MusicalStructureAnalyzer.analyze()`
- Gibt `[(start_s, end_s, label), ...]` im Fahrplan-Format zurück
- Label-Normalisierung (pre-chorus→chorus, solo→bridge etc.)
- Merge benachbarter gleicher Labels
- In `AurikDenker` via `_get_musical_sections()` vor `PhaseInteractionDenker.plan()` aufgerufen
- Sektionen fließen als `sections`-Parameter in `build_fahrplan()` → per-Segment-Logik aktiv

## §2.62 Per-Segment-UV3 — Split + Crossfade

**Dateien**: `backend/core/per_segment_executor.py`, `backend/core/unified_restorer_v3.py`

- `get_segment_strengths_from_fahrplan()` — liest per-Segment-Stärken aus Fahrplan
- `run_phase_per_segment()` — splittet Audio, führt Phase pro Segment aus, crossfaded mit 12ms Hann
- In `_profiled_phase_call`: Prüft Fahrplan auf non-uniforme Segmente → segmentierte Ausführung
- `_SegResult` Wrapper für Kompatibilität mit UV3-Nachverarbeitung
- Nur aktiv wenn Fahrplan tatsächlich unterschiedliche Stärken pro Segment hat

## §2.63 Closed-Loop PID — Messen → Nachsteuern

**Dateien**: `backend/core/closed_loop_pid.py`, `backend/core/unified_restorer_v3.py`

- `ClosedLoopPIDController` mit P/I/D-Gains pro Musical Goal
- `before_phase(phase_id, pre_snapshot) → strength_multiplier` — boostet/dämpft vor Phase
- `after_phase(phase_id, post_snapshot)` — aktualisiert PID-State
- Liest `PHASE_EFFECT_CATALOG` für Phase→Goal-Mapping
- Anti-Windup (I-Term capped bei 0.30)
- Integration in UV3: PID-Init nach `_song_goal_targets`, `before_phase` vor `phase.process()`, `after_phase` nach Delta-Berechnung

## §3.0 Source-Aware Restoration — Demucs → Per-Stem-UV3 → Remix

**Dateien**: `backend/core/source_aware_fahrplan.py`, `backend/core/source_aware_restorer.py`, `denker/restaurier_denker.py`, `denker/aurik_denker.py`

### SourceAwareFahrplan
- `STEM_PHASE_CONFIG`: Per-Stem-Whitelist (Vocals=6 Phasen, Drums=5, Bass=6, Other=alle)
- `STEM_REMIX_GAINS`: Stem-Gewichte (Vocals 1.05, Drums 1.02, Bass 1.00, Other 0.98)
- `filter_phases_for_stem()`: Filtert Phasenplan für einen Stem
- `get_stem_config()`: Gibt `StemConfig` mit Phasen-Stärken und Remix-Gain

### SourceAwareRestorer
- `restore_per_source()`: Orchestrator-Funktion
  1. Demucs ONNX Source-Separation (htdemucs_6s, 4 Stems)
  2. Pro Stem: Phasenplan filtern + UV3 ausführen
  3. Remix mit Stem-Gains + Clip auf [-1, 1]
- `_separate_sources()`: ONNX Runtime direkt (umgeht kaputte demucs.pretrained)
- `_get_ort_session()`: GPU→CPU-Fallback, Session-Cache
- Aktivierung: `AURIK_SOURCE_SEPARATION=1` (default: aus)
- Fallback: Bei Fehler automatisch Standard-UV3 auf Vollmix

### Provider-Strategie
1. ROCMExecutionProvider (GPU) — benötigt `hipblas`, `miopen-hip`
2. MIGraphXExecutionProvider (AMD) — benötigt `libmigraphx_c.so.3`
3. CPUExecutionProvider — immer verfügbar (~0.8× realtime)

## Tests

- `tests/unit/test_260_30_evolution.py` — 27 Tests: Fahrplan, SectionGoalAdapter, PerSegmentExecutor, ClosedLoopPID, SourceAwareFahrplan
- `tests/unit/test_300_source_aware.py` — 12 Tests: StemConfig, PNM-Fallback, Remix
- Alle Tests non-blocking, kein GPU/ML-Bedarf

## Datenfluss (komplett)

```
Audio → MusicalStructureAnalyzer → SectionGoalAdapter.get_sections()
      → [(0,10,"intro"), (10,30,"verse"), (30,45,"chorus")]
      → PhaseInteractionDenker.plan(sections=...) → build_fahrplan()
      → PhasePlan.policy_hints["fahrplan"] → AurikDenker → denker_policy_input
      → RestaurierDenker.restauriere()
           ├─ [Standard] UV3.restore(audio, **kwargs)
           │    ├─ _profiled_phase_call:
           │    │   ├─ Fahrplan-Kalibrierung: strength = fahrplan.calibration[phase_id]
           │    │   ├─ PID.before_phase(): strength ×= pid_mult
           │    │   ├─ Per-Segment: run_phase_per_segment() wenn non-uniform
           │    │   └─ Delta → PID.after_phase()
           │    └─ → restauriertes Audio
           └─ [AURIK_SOURCE_SEPARATION=1] restore_per_source()
                ├─ Demucs ONNX → 4 Stems
                ├─ Pro Stem: Phasenplan filtern → UV3.restore()
                └─ Remix → restauriertes Audio
```
