---
name: quality-benchmark
description: "Misst Qualität und führt Benchmarks für Aurik 9 durch (OQS, AMRB, PQS, MUSHRA). Use when: OQS, AMRB, PQS, MOS, MUSHRA, Benchmark, Szenario, iZotope, Competitive, quality_estimate, PEAQ, mushra_evaluator."
argument-hint: "Was messen? (z.B. 'OQS-Score interpretieren', 'AMRB-Szenario hinzufügen')"
---

# Aurik 9 — Qualität & Benchmark messen

## OQS — Overall Quality Score

Modul: `core/mushra_evaluator.py` (algorithmische PEAQ-Approximation — **kein** ITU-R-MUSHRA)
In externen Berichten: „OQS (algorithmisch)".

| Stufe | Score | Pflicht |
|---|---|---|
| Good (B) | ≥ 80 | **[RELEASE_MUST]** — Pflicht für jede neue Phase/Plugin |
| Excellent (A) | ≥ 91 | Exzellenz-Label — kein harter Gate-Wert |

**[TARGET_2026]** Studio-2026-Ziel: OQS ≥ **88**. Kein Release-Blocker, Roadmap-Ziel.

## AMRB — Aurik Musical Restoration Benchmark

10 Szenarien: AMRB-01-TAPE … AMRB-10-COMPOSITE

**[RELEASE_MUST]**: Alle 10 Szenarien OQS ≥ 80.
**[TARGET_2026]**: Gesamt ≥ 84.0, ≥ 8/10 Szenarien. Aurik ≥ iZotope RX 11 in ≥ 7/10.

### Seeding-Invariante
`_sid_offset(sid)` via **MD5** — KEIN `hash(sid)` (Python-zufällig zwischen Runs).
Nightly: `n_items ≥ 5`.

### Baseline
`iZotope RX 11 (commercial)` mit OQS 71.0. RX 10-Key als Legacy-Alias.

## §2.40 Stratifiziertes Konkurrenz-Gate

Aurik muss **pro Material UND pro Defektklasse** bestehen:
```
tape/vinyl/shellac/digital/vocal × hiss/crackle/dropout/reverb/hum/codec
```
Release failt bei regressiver Zelle auch wenn Gesamt-OQS besteht.

## PQS — Perceptual Quality Score

### Material-MOS-Schwellen (RELEASE_MUST)

| Material | MOS-Minimum |
|---|---|
| cd_digital / dat / mp3_high / aac | ≥ 4.5 |
| Tape | ≥ 4.2 |
| Vinyl | ≥ 4.0 |
| Shellac | ≥ 3.8 |
| Allgemein (ohne Material) | ≥ 3.8 |

> `assert mos >= 4.5` ohne Materialkontext ist ein **Programmierfehler**.

### Weitere PQS-Schwellen

| Metrik | Hard-Fail | Weltklasse |
|---|---|---|
| PQS NSIM | ≥ 0.70 | ≥ 0.90 |
| MCD (dB) | ≤ 8.0 | ≤ 3.0 |
| Spectral Coherence | ≥ 0.60 | ≥ 0.85 |

### quality_estimate-Formel (einzige erlaubte)
```python
quality_estimate = max(0.0, min(1.0,
    0.40 * (1 - defect_severity) + 0.60 * (pqs_mos - 1) / 4))
```
**VERBOTEN**: `quality_estimate * 1.15`
E2E-Pflicht: `result.quality_estimate >= 0.55`

## §8.4 Externes Mini-MUSHRA-Protokoll

Bei Änderungen an Kernphasen, PMGG, DefectScanner oder heavy ML-Fallbacks:
- Mindestens 6 Szenarien (2 Vocal)
- Mindestens 8 Hörer
- Pflichtbericht als Artefakt (Scores, Konfidenzen, Delta)
- Kein Release ohne gültiges Artefakt

## Restaurierungs-Modi

| Aspekt | Restoration | Studio 2026 |
|---|---|---|
| **Klangziel** | **Tonträgerkette invertieren** — Originalklang | Weltklasse-Studio-Klang |
| **LUFS** | Δ ≤ 1 LU (Input-nah) | −14 LUFS EBU R128 |
| **TonalCenter** | ≥ 0.95 | ≥ 0.97 |
| **Intervention** | Minimal — nur Tonträgerverluste invertieren | Maximal-zielgerichtet — volle Enhancement-Kette |
| **Natürlichkeit** | Original-Charakter + Studio-Ambience bewahren | Studio-Natürlichkeit (nicht synthetisch) |
| **Rauschboden** | Material-adaptiv (Shellac ≤ −45, Vinyl ≤ −55, Tape ≤ −60, Digital ≤ −72 dBFS) | ≤ −72 dBFS |
| **HPI-Gewichtung** | `timbral_fidelity` dominant (Nähe zum Original) | PQS-Improvement dominant |
| **Enhancement** | Nur Defekt-Beseitigung + Tonträgerverlust-Inversion | + Stem-Sep, Vocal-AI, Mastering, Stereo-Imaging |
| **Brillanz / Bass-Kraft** | ≥ 0.78 / ≥ 0.78 | ≥ 0.90 / ≥ 0.88 |

## Adaptive Qualitätsziele

**Statische Schwellwerte VERBOTEN.** Immer:
`get_adaptive_goals_and_config(audio, sr)` → material-/ära-/restorability-skaliert.

### Era-GP-Warmstart (§2.14)
- ≤ 1940: `noise_reduction_strength ~ N(0.90, 0.05)`
- ≤ 1960: N(0.75, 0.08)
- ≥ 1970: N(0.50, 0.10)

## Performance-Budget-Referenz

| Operation | Limit / Minute Audio |
|---|---|
| DefectScanner | ≤ 4 s |
| Phase-Pipeline | ≤ 240 s |
| FeedbackChain | ≤ 120 s |
| ExcellenceOptimizer | ≤ 60 s |
| RestorabilityEstimator | ≤ 5 s |

RT-Budget: `RT8_EXCELLENCE_BUDGET = 32.0` (Benchmark-Gate-Referenz).

## DSP-Spezialregeln (Benchmark-relevant)

- **Dithering**: POW-r Typ 3 → TPDF fallback. VERBOTEN: Truncation
- **MP3-Export**: LAME VBR V0 (bis 320 kbps). VERBOTEN: CBR
- **MRSA-Zonen**: sub_bass 65536 / mid_low 16384 / mid 8192 / presence 1024 / air 128

> Vollständige Qualitäts-Spezifikation: `.github/specs/07_quality_and_tests.md`
> AMRB-Implementation: `benchmarks/musical_restoration_benchmark.py`
