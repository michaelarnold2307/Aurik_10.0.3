---
name: fix-metric
description: "Ändert oder debuggt Musical-Goal-Metriken in Aurik 9. Use when: Metrik, Goal, Schwellwert, Kalibrierung, Divisor, Recalibration, BrillanzMetric, WaermeMetric, NatuerlichkeitMetric, TonalCenterMetric, PMGG-Proxy, _PRECISE_METRICS, Sub-Metrik, Pareto."
argument-hint: "Welche Metrik? (z.B. 'BrillanzMetric Divisor anpassen', 'TonalCenter False-Regression debuggen')"
---

# Aurik 9 — Musical-Goal-Metriken ändern / debuggen

## 14 Musical Goals — Vollständige Schwellwerte (v9.10.77)

| Ziel | Klasse | Prio | Restoration | Studio 2026 |
|---|---|---|---|---|
| Natürlichkeit | `NatuerlichkeitMetric` | P1 | ≥ 0.90 | ≥ 0.90 |
| Authentizität | `AuthentizitaetMetric` | P1 | ≥ 0.88 | ≥ 0.88 |
| Tonales Zentrum | `TonalCenterMetric` | P2 | ≥ 0.95 | ≥ 0.97 |
| Timbre-Authentizität | `TimbralAuthenticityMetric` | P2 | ≥ 0.87 | ≥ 0.87 |
| Artikulation | `ArticulationMetric` | P2 | ≥ 0.85 | ≥ 0.85 |
| Emotionalität | `EmotionalitaetMetric` | P3 | ≥ 0.82 | ≥ 0.87 |
| Mikro-Dynamik | `MicroDynamicsMetric` | P3 | ≥ 0.88 | ≥ 0.92 |
| Groove | `GrooveMetric` | P3 | ≥ 0.83 | ≥ 0.88 |
| Transparenz | `TransparenzMetric` | P4 | ≥ 0.82 | ≥ 0.89 |
| Wärme | `WaermeMetric` | P4 | ≥ 0.75 | ≥ 0.80 |
| Bass-Kraft | `BassKraftMetric` | P4 | ≥ 0.78 | ≥ 0.88 |
| Separation-Treue | `SeparationFidelityMetric` | P4 | ≥ 0.78 | ≥ 0.85 |
| Brillanz | `BrillanzMetric` | P5 | ≥ 0.78 | ≥ 0.90 |
| Raumtiefe | `SpatialDepthMetric` | P5 | ≥ 0.70 | ≥ 0.78 |

> Pareto-Differenzierung (v9.10.77): Restoration senkt P3–P5 auf physikalisch erreichbare Werte.
> Pareto-Konflikte: Bass↔Transparenz [0.7], Brillanz↔Wärme [0.6].

## §2.29d Differenziertes Regressions-Regime (v9.10.122)

| Prio-Klasse | Goals | Regime | PMGG-Verhalten |
|---|---|---|---|
| **P1/P2** | Natürlichkeit, Authentizität, TonalCenter, Timbre, Artikulation | **Hart** | Keine Phase darf verschlechtern. Retry-Kaskade bei Regression |
| **P3–P5** | Emotionalität, MikroDynamik, Groove, Transparenz, Wärme, Bass, SepFidelity, Brillanz, Raumtiefe | **Pipeline-Netto-Budget** | Einzelphasen dürfen vorübergehend verschlechtern. MusicalGoalsChecker prüft am Kettenende: alle Goals ≥ Schwellwert |

**Warum**: De-Hiss MUSS kurzfristig Wärme senken, damit spätere Phasen auf sauberem Fundament arbeiten. Per-Phase-Block erzwingt übervorsichtiges Wet/Dry → Restlärm → Tiefen-Immersion zerstört.

## §2.44 Holistic Perceptual Gate — HPI (v9.10.122)

**Letztes Gate vor Export.** Misst Gesamt-Hörverbesserung statt nur Einzel-Goals:

### Restoration-Modus
```
HPI = MERT_similarity(input, output) × timbral_fidelity(input, output) × artifact_freedom × emotional_arc_preservation
```
- `timbral_fidelity` dominant: strukturelle Klangkohärenz (nicht bloße Input-Ähnlichkeit)
- `artifact_freedom` (§2.49): ≥ 0.95 Pflicht — Musical Noise, Pre-Echo, Spectral Holes, Rauschtextur
- `emotional_arc_preservation`: Arousal/Valence-Bogen + Makrodynamik + Lyrics-Salienz (§2.36)
- RestorabilityEstimator > 0.85 → strengeres Gate (kaum Intervention nötig)

### Studio-2026-Modus
```
HPI = studio_quality_gain × PQS_improvement × artifact_freedom × emotional_arc_preservation
```
- PQS-Improvement dominant: Qualität steigern > Original-Treue
- `studio_quality_gain`: Abstand zu Referenz-Studioniveau (−14 LUFS, Noise ≤ −72 dBFS, Separation, Klarheit)
- MERT fängt nur musikalische Identität ab (Melodie, Rhythmus), nicht Klangfarbe

| Bedingung | Aktion |
|---|---|
| `HPI > 0` | Export erlaubt |
| `HPI ≤ 0` | Rollback auf weniger aggressive Variante |

**Begründung**: 14 Goals einzeln bestanden ≠ Gesamtklang verbessert. Ein Synthesizer erreicht hohe Spectral Flatness (= hoher Natürlichkeits-Score) obwohl er künstlich klingt. HPI fragt: "Hört sich das **als Ganzes** besser an?"

### HPI-Komponenten
- **MERT_similarity**: Embedding-Distanz zwischen Input/Output — misst ob der musikalische Charakter erhalten bleibt
- **timbral_fidelity** (Restoration): MFCC-Distanz + Spectral-Envelope-Korrelation + Crest-Factor-Erhalt — misst **strukturelle Klangkohärenz** zum Original. Bei schwerer Degradation (Restorability ≤ 50): zusätzlicher Referenz-Vektor aus genre-/ära-typischen Hochqualitäts-Embeddings als Orientierung
- **artifact_freedom** (beide Modi): Artefakt-Freiheit-Score (§2.49) — Musical Noise, Pre-Echo, Spectral Holes, Phase-Cancellation. Multiplikator im HPI; bei Artefakten → HPI sinkt drastisch
- **PQS_improvement** (Studio 2026): `PQS(output) - PQS(input)` — technische Qualitätssteigerung
- **studio_quality_gain** (Studio 2026): Abstand zu Referenz-Studioniveau (−14 LUFS, Noise ≤ −72 dBFS)
- **emotional_arc_preservation**: Arousal/Valence-Bogen-Korrelation + **Makrodynamik** (Vers-/Refrain-/Bridge-Pegelrelationen) + Lyrics-Salienz (§2.36: Phonem-Boost-Konsistenz)

### Referenz-Paradoxon (Restoration)
Das Studio-Original ist unbekannt. `timbral_fidelity(input, output)` misst daher nicht „wie ähnlich klingt es dem degradierten Input?", sondern „besitzt der Output die **strukturelle akustische Kohärenz** einer natürlichen, unbearbeiteten Aufnahme?" — Spectral-Envelope-Kontinuität, Crest-Factor-Konsistenz, MFCC-Stabilität. Bei leichter Degradation (Restorability > 70) ist der Input eine gute Annäherung ans Original → hohe Input-Treue angemessen. Bei schwerer Degradation (Restorability ≤ 50) ist der Input weit vom Original entfernt → Referenz-Anker wechselt zu MERT-Embeddings aus GP-Memory (genre × material × ära).

**MERT-Referenz-Aufbau**: 36 Bootstrap-Prototypen (12 Genres × 3 Ära-Bins) → inkrementell verfeinert nach erfolgreichen Restaurierungen (EMA α = 0.15). Fallback: Genre-Familie → Ära-Median → rein gegen Input. Details: Spec 02 §2.44.

## Sub-Metriken (Pflicht-Implementierungsdetails)

| Metrik | Sub-Metriken | Pflicht-Schwellen |
|---|---|---|
| `TimbralAuthenticityMetric` | MFCC-Pearson, Spectral-Centroid-Korrelation, Rolloff-Abw. | ≥ 0.95, ≥ 0.93, ≤ 5 % |
| `ArticulationMetric` | Transient-Shape-Korrelation, Attack-Time-Abw. | ≥ 0.90, ≤ 10 ms |
| `TonalCenterMetric` | Chroma-Korrelation, Key-Shift | ≥ 0.95, 0 Cent |
| `BrillanzMetric` / `WaermeMetric` | ISO 226:2023 Equal-Loudness gewichtet | Kein lineares Energiemessen |
| `BassKraftMetric` | Virtual Pitch (Missing Fundamental) 120–500 Hz | Oberton-Analyse |
| `SeparationFidelityMetric` | SDR, SIR nach NMF | ≥ 8 dB, ≥ 12 dB |
| `SpatialDepthMetric` | IACC (Blauert 1997), Mono → GoalApplicability deaktiviert | < 0.70 = Phantom-Center-Collapse |

## §9.7.15 Metriken-Recalibration (v9.10.120)

| Metrik | Änderung | Wissenschaftliche Basis |
|---|---|---|
| **Brillanz** | HF Crest-Divisor 13.5 → **10.5** | Fastl & Zwicker 2007 §8.3 |
| **Transparenz** | 5-Band-Crest-Divisor 8.8 → **7.0** | Moore & Glasberg 1983 |
| **Wärme** | H2/H4 Even-Harmonic-Divisor 9.0 → **5.0** | Fletcher & Rossing |
| **Natürlichkeit** | Flatness ×2→×2.5, ZCR-Var ×100→×60, Contrast ÷30→÷25, Onset ÷10→÷8 | Johnston 1988 |
| **Emotionalität** | LUFS Pre-Norm auf −14 LUFS | Loudness-invariant |
| **PQS NSIM** | Pearson → ERB-gewichtete Korrelation (300–4000 Hz) | Patterson et al. 1992 |
| **PQS MCD** | Pseudo-RMS → echte Mel-Cepstral Distortion (13 MFCCs) | Kubichek 1993 |

## SNR-robuste PMGG-Proxy-Fixes (§9.7.11–14, v9.10.91–92)

### §9.7.11 tonal_center — K-S Proxy
Krumhansl-Schmuckler-Key-Detection — SNR-invariant. Alle früheren Exclusions entfernt.

### §9.7.12 brillanz — HF Spectral Crest Factor (2–16 kHz)
p95/p50-Crest-Factor statt HF-Energie-Ratio. Noise hebt p50-Median → Crest steigt nach Denoise.
`BrillanzMetric`-Preservation-Penalty entfernt (kontraproduktiv).

### §9.7.13 transparenz — Multi-Band Spectral Crest (5 Oktavbänder 250 Hz–8 kHz)
5-Oktavband-Crest-Mittelwert statt 75%-Rolloff-Proxy.
**Bug-fix**: `TransparenzMetric.measure()` hatte kein `reference=`-Parameter → TypeError in Precise-Override.

### §9.7.14 waerme — Even-Harmonic-Ratio + Warmth Ratio
**Primär**: Even-Harmonic-Ratio `THD_even / THD_total` (H2/H4 gerade Obertöne vs. gesamte THD), ISO 226:2023 gewichtet. Misst die wahrgenommene Wärme von Röhren/Bandmaschinen, nicht bloßen Spektral-Tilt.
**Sekundär**: Sub-Band-Verhältnis E(200–800)/E(800–3000) als Spektral-Tilt-Proxy. Reverb-invariant.
**Begründung Upgrade**: Ein parametrischer EQ-Boost bei 400 Hz erhöht das Sub-Band-Verhältnis (= hoher Score), erzeugt aber keine wahrgenommene Wärme. Gerade Harmonische (H2, H4) sind der akustische Fingerabdruck von Röhren-/Bandsignalketten (Fletcher & Rossing).

## §2.29b Stable-Metric-Invariante

**NIEMALS** in `_PRECISE_METRICS` aufnehmen:
- Metriken mit ML-zustandsäbhangigem Gewicht (z.B. `NatuerlichkeitMetric` — CREPE-Load-State)
- Neue Metriken ohne Nachweis: Eigenrauschen ≤ 0.02 auf identischen Audio-Paaren

**Root-Cause NatuerlichkeitMetric**: CREPE ändert w_crepe 0.0→0.18 zwischen before/after →
Pseudo-Regression Δ ≈ 0.15–0.28 → false P1-Kaskade → Phase_03 best-effort @ 5.6 % →
Noise-Floor −55 dBFS → **Tiefen-Immersion zerstört**.

### [TARGET_2026] NatuerlichkeitMetric-Reform (§9.7.16)

**Problem**: Aktuelle Sub-Metriken (Spectral Flatness, ZCR-Varianz, Spectral Contrast, Onset-Dichte) sind Signal-Statistiken, keine Wahrnehmungs-Features. Ein Synthesizer hat hohe Flatness und gleichmäßige ZCR → hoher Score. Eine Jazz-Bar-Aufnahme mit natürlicher Raumakustik hat niedrige Flatness → niedriger Score. Der Hörer empfindet das Gegenteil.

**Reformulierung — modus-differenziert**:

| Aspekt | Restoration | Studio 2026 |
|---|---|---|
| **Definition** | "Klingt wie die echte Aufnahme" — Original-Charakter: Raumakustik, Vintage-Wärme, Ära-Klang bewahren | "Klingt wie ein echtes Instrument in einem professionellen Studio" — nicht synthetisch, nicht überbearbeitet |
| **Primär-Proxy** | MERT-Embedding-Distanz zum Input (Charakter bewahrt?) | MERT-Embedding-Distanz zu Studio-Referenzen (Studio-typisch?) |
| **Harmonic Coherence** | Obertonstruktur des Originals — auch mit Ära-typischen Verzerrungen | Saubere, kohärente Obertonstruktur ohne Artefakte |
| **Micro-Variation** | Originale Frame-zu-Frame-Variation bewahren | Musikalisch sinnvolle Variation — Glättung steriler Artefakte, nicht des Spiels |

**Bis zur Reform**: `NatuerlichkeitMetric` nur im Export-Gate (MusicalGoalsChecker), nie in PMGG-Delta-Checks (§2.29b). HPI (§2.44) übernimmt die holistische Bewertung.

## Qualitätsmessung (§8.1)

| Metrik | Hard-Fail | Weltklasse |
|---|---|---|
| PQS MOS | ≥ 3.8 (generell) / ≥ 4.5 (digital) | ≥ 4.5 (digital) |
| PQS NSIM | ≥ 0.70 | ≥ 0.90 |
| MCD (dB) | ≤ 8.0 | ≤ 3.0 |
| Spectral Coherence | ≥ 0.60 | ≥ 0.85 |

> MOS ≥ 4.5 NUR für cd_digital/dat/mp3_high/aac. Shellac ≥ 3.8, Vinyl ≥ 4.0, Tape ≥ 4.2.

**quality_estimate-Formel** (einzige erlaubte):
`quality_estimate = max(0.0, min(1.0, 0.40 * (1 - defect_severity) + 0.60 * (pqs_mos - 1) / 4))`
VERBOTEN: `quality_estimate * 1.15`

## Materialklassifikations-Konflikte

Priorität: höhere Konfidenz. Bei Gleichstand: höchster Defekt-Score. Sonst: konservativerer Typ.
Entscheidungsweg MUSS im Log dokumentiert werden.

## Universelle Garantien (§8.2)

| Garantie | Schwellwert |
|---|---|
| Kein NaN/Inf | `np.isfinite(audio).all()` |
| Kein Clipping | `np.max(np.abs(audio)) ≤ 1.0` |
| Chroma-Korrelation | Pearson ≥ 0.95 |
| LUFS Pass-Through (SNR>40dB) | Verlust ≤ 0.05 MOS, ≤ 0.3 LU |
| Rauschboden (Restoration) | Material-adaptiv: Shellac ≤ −45, Vinyl ≤ −55, Tape ≤ −60, Digital ≤ −72 dBFS |
| Rauschboden (Studio 2026) | ≤ −72 dBFS |
| Mikro-Dynamik | Pearson LUFS-Profil (400 ms) ≥ 0.92 |
| Emotionaler Bogen (≥30s) | Arousal ≥ 0.85, Valence ≥ 0.80 |
| FeedbackChain-Rollback | |MOS_neu − MOS_alt| > 0.05 |

## Adaptive Schwellwerte (§2.31–§2.34)

**Statische Schwellwerte VERBOTEN.** Vor jeder Restaurierung skalieren:
`get_adaptive_goals_and_config(audio, sr)` → adaptiertes GoalApplicabilityFilter + PhysicalCeilingEstimator.
P1+P2-Regression → FeedbackChain-Rollback; Ceiling Δ < 3 % → Terminierung.

## Perceptuelle Pflicht-Messwerte

| Messwert | Schwelle |
|---|---|
| LUFS-Diff | ≤ 1 LU |
| Chroma Pearson | ≥ 0.95 |
| Groove DTW | ≤ 8 ms RMS |
| Transient Attack | ≤ ±2 ms |
| MERT-Harmonizität | ≥ 0.85 |

> Vollständige Goal-Spezifikation: `.github/specs/01_musical_goals.md`
