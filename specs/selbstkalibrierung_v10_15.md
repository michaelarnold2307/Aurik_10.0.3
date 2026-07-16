# §v10.15 Selbstkalibrierungs-Architektur (Self-Calibration Architecture)

## Prinzip

> Aurik verhält sich wie ein echter Toningenieur: Jeder einzelne Eingriff
> wird kalibriert, verifiziert und nur bei nachgewiesener Verbesserung
> übernommen. Kein Parameter ist hartcodiert, wenn er auch aus dem Signal
> ableitbar ist.

## Architektur-Übersicht

```
┌─────────────────────────────────────────────────────────┐
│                    AUDIO-DATENFLUSS                       │
├──────────┬──────────┬────────────────┬──────────────────┤
│ PRE      │ PHASE 01 │  PHASE 02 … 64 │ POST-PROCESSING  │
│ (Import) │  … 64    │  (PMGG-Loop)   │  (PostGate)      │
├──────────┼──────────┼────────────────┼──────────────────┤
│ STCG     │ PMGG     │  PMGG          │  PostGate        │
│ ✓ v10.14 │ ✓        │  ✓             │  ★ v10.15        │
│ Polarity │          │                │                  │
│ ✓ TODO   │          │                │                  │
└──────────┴──────────┴────────────────┴──────────────────┘
```

## Drei Zonen der Selbstkalibrierung

### Zone A: Pre-Pipeline (vor Phase 01)

| Komponente         | Status    | Maßnahme                                  |
|--------------------|-----------|-------------------------------------------|
| STCG (L/R-Delay)   | ✅ v10.14 | Universeller 20ms-Guard                   |
| Polarity Inversion | ★ TODO   | Verify via L/R-Korrelation Δ vor/nach     |

### Zone B: Main Pipeline (Phasen 01–64)

| Komponente         | Status    | Maßnahme                                  |
|--------------------|-----------|-------------------------------------------|
| Alle 64 Phasen     | ✅ PMGG   | 15-Ziele-Schnellcheck + 5 Retry-Stufen    |
| PhaseSkipper       | ✅        | Defekt-basiert                            |
| Preflight-Risk     | ✅        | Risiko-basiert                            |

**PMGG-Regeln (unverändert):**
1. 5 s Stichprobe aus Audio-Mitte VOR der Phase messen (15 Ziele)
2. Phase ausführen
3. Dieselben 15 Ziele NACH der Phase messen
4. Δ < −Schwellwert → Retry mit strength × 0.65, 0.50, 0.35, 0.20, 0.10
5. Nach 5 Retries immer noch Regression → HPE-Check
6. HPE-Delta < −0.02 → Phase verwerfen, Pre-Phase-Audio wiederherstellen

### Zone C: Post-Processing (nach Phase 64)

> ★ NEU in v10.15: Alle Post-Processing-Komponenten werden durch
> `PostProcessingGate` gewrappt — analog zu PMGG, aber mit reduziertem
> Ziel-Set (5 statt 15 Ziele, da es sich um finale Politur handelt).

| Komponente              | Typ          | Kalibrierung                      |
|--------------------------|--------------|-----------------------------------|
| VocalScratchRepair       | Detektion    | PostGate: Brillanz+Natürlichkeit  |
| TapeHeadArtifactRepair   | Detektion    | PostGate: Transparenz+Wärme       |
| AntiMufflingPass         | Spektral     | PostGate: Brillanz+Wärme          |
| SmartTapeRepair          | Detektion    | PostGate: Transparenz             |
| ArtifactEchoRemoval      | Detektion    | PostGate: SpatialDepth            |
| SibilanceMaxRepair       | Detektion    | PostGate: Natürlichkeit            |
| VocalClarityMax          | Enhancement  | PostGate: Artikulation+Brillanz   |
| SpecializedDefectRepair  | Detektion    | PostGate: Transparenz             |
| **HumanizationPass**     | Enhancement  | **Adaptive Stärke** + PostGate    |
| PerceptualExportOptimizer| Enhancement  | PostGate: Gesamtqualität           |
| DirectDefectRepair       | Detektion    | PostGate: Transparenz             |
| HarmonicPreservationGuard| Guard        | PostGate: Wärme+TimbAuth           |
| HarmonicLatticeAnalyzer  | Guard        | PostGate: TonalCenter              |

**PostGate-Regeln (NEU):**
1. 5 s Stichprobe VOR der Komponente messen (5 Ziele, DSP-only, ≤ 80 ms)
2. Komponente ausführen
3. 5 Ziele NACH der Komponente messen
4. Δ < −REGRESSION_THRESHOLD → Komponente überspringen
5. KEINE Retry-Schleife (Post-Processing ist nicht iterativ kalibrierbar)
6. Ausnahme: HumanizationPass hat adaptive Stärke (0.05–0.25)

### Zone D: STCG (quer durch alle Zonen)

| Aufrufer                  | Status    |
|---------------------------|-----------|
| pre_pipeline              | ✅ 20ms   |
| post_pipeline             | ✅ 20ms   |
| phase_12_pre_chunking     | ✅ 20ms   |
| phase_12_wow_flutter_fix  | ✅ 20ms   |
| phase_24                  | ✅ 20ms   |
| phase_31                  | ✅ 20ms   |
| import_pipeline           | ✅ 20ms   |
| stereo_drift_final        | ✅ 20ms   |
| post_export               | ✅ 20ms   |

## HumanizationPass: Adaptive Stärke

**Vorher (v10.14):** `strength=0.15` hartcodiert
**Nachher (v10.15):** `strength = calibrate(audio, sr)` → ∈ [0.05, 0.25]

Kalibrierung:
- Analysiert die spektrale Dichte und den Dynamikumfang
- Bei bereits „lebendigem" Material (hohe Mikrodynamik) → niedrige Stärke
- Bei „sterilem" Material (flache Dynamik) → höhere Stärke
- PostGate verifiziert: Wärme + Natürlichkeit nach Humanization

## Ausnahmen — keine Selbstkalibrierung

Folgende Komponenten haben KEINE Kalibrierung, weil sie:
- binär sind (entweder sie erkennen einen Defekt und reparieren, oder nicht)
- keine tunable Parameter haben
- immer konservativ arbeiten

| Komponente            | Grund für Ausnahme                        |
|-----------------------|-------------------------------------------|
| PhaseOutputGuard      | Safety-only (NaN/Inf/Clip), kein Parameter |
| DC-Offset-Korrektur   | Deterministisch (Hochpass 10 Hz)          |
| Sample-Rate-Konvert.  | Mathematisch exakt, kein Spielraum         |
| Silence-Maske         | Binär (On/Off), keine Kalibrierung nötig   |

## Pre-Commit / Watchdog

Keine Änderungen nötig:
- `_GLOBAL_MAX_MS` ist bereits in `stereo_temporal_coherence_guard.py` definiert
- PostGate wird als neue Klasse in `backend/core/post_processing_gate.py` implementiert
- Keine bestehenden Watchdog-Regeln betroffen

## Implementierungs-Reihenfolge

1. ✅ STCG Universal Guard (v10.14, bereits umgesetzt)
2. ✅ Null-Lag-Integrationstest (tests/normative/test_null_lag_pass_through.py)
3. 🔲 PostProcessingGate — Klasse + verify_quick (5 Ziele)
4. 🔲 HumanizationPass — adaptive Stärke + PostGate-Integration
5. 🔲 Post-Processing-Chain — alle 13 Komponenten durch PostGate wrappen
6. 🔲 Polarity Inversion — verify via Korrelations-Δ
7. 🔲 Tests aktualisieren
