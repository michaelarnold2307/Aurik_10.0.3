# Spec 13: Klangqualität für das menschliche Ohr

> **Status:** Normativ · **Version:** Aurik 9.12.11 · **Scope:** Perceptual Audio Quality, ISO 226, Listening Modes, Fatigue Prevention

## §13.1 Das menschliche Ohr als ultimatives Messinstrument

Aurik optimiert nicht für technische Metriken (SNR, THD, PESQ), sondern für das
menschliche Gehör. Diese Spec definiert die psychoakustischen Prinzipien, nach
denen alle Restaurierungsentscheidungen getroffen werden.

### §13.1.1 Frequenzabhängige Wahrnehmung (ISO 226:2003)

Das menschliche Ohr ist maximal empfindlich bei 3–4 kHz. Bei 100 Hz ist die
Empfindlichkeit ~20 dB geringer, bei 30 Hz ~40 dB. Aurik gewichtet daher:

- **Bass-Fehler (20–200 Hz):** 0.5× Gewichtung (Ohr ist unempfindlich)
- **Mitten-Fehler (200–2000 Hz):** 1.0× (Wärme, Natürlichkeit)
- **Präsenz-Fehler (2000–8000 Hz):** 1.5× (maximale Empfindlichkeit)
- **Luft-Fehler (8000–20000 Hz):** 0.7× (Altersabhängig, maskiert)

Diese Gewichtung ist in `§H` (GenreGoalProfile.psychoacoustic_weights) und
`§PQC` (PerceptualQualityCouncil) implementiert.

### §13.1.2 Simultane Maskierung

Ein lautes Signal bei Frequenz `f` maskiert leisere Signale in einem
Frequenzbereich von `f × 0.8` bis `f × 1.4` (Critical Bandwidth).
Aurik nutzt dies für:

- Defect-Audibility-Entscheidungen (nur hörbare Defekte werden repariert)
- Phase-Strength-Dosierung (Maskierung reduziert nötige Stärke)

## §13.2 Listening Modes (§Q)

Verschiedene Wiedergabeszenarien erfordern unterschiedliche Optimierung:

| Mode | Goal-Shift | Begründung |
|------|-----------|------------|
| **Kopfhörer** | Räumlichkeit +30%, Bass −15% | Kopfhörer haben keine natürliche Crossfeed-Räumlichkeit |
| **Nahfeld** | Neutral | Referenz-Abhörsituation |
| **Farfeld/Wohnzimmer** | Bass +15%, Wärme +10% | Raummoden + Fletcher-Munson bei niedriger Lautstärke |
| **Auto** | Bass +40%, Höhen +30%, Textverständlichkeit +30% | Straßenlärm-Maskierung, Bass-Resonanz |

Aktivierung: `restore(audio, sr, listening_mode="headphones")`

## §13.3 Hörermüdungs-Prävention (§T)

### §13.3.1 Das Problem

37 DSP-Phasen + 3 ML-Modelle erzeugen kumulativ ein „zu perfektes" Signal.
Das Gehirn interpretiert fehlende Mikro-Variation als „künstlich" → Ermüdung
nach 15–20 min Hören.

### §13.3.2 Der Humanization-Pass

```
HumanizationPass.apply(audio, sr, strength=0.15)
```

- Amplituden-Modulation: ±0.02 % bei 0.47 Hz (unterhalb der Wahrnehmungsschwelle)
- Phasen-Jitter: Allpass 1. Ordnung, g=0.00045, Verzögerung 0.3 ms
- Blend: 5 % bearbeitet + 95 % Original (nicht hörbar, aber spürbar)

Das Ergebnis klingt für das Ohr „lebendig" ohne messbare Klangveränderung.

## §13.4 Dynamik-Bogen-Erhalt (§O + §S)

### §13.4.1 LUFS Arc Preservation (§O)

Der Dynamik-Verlauf eines Songs (leise Strophe → lauter Refrain) MUSS erhalten
bleiben. Aurik misst Short-Term-LUFS in 8 Segmenten und prüft:

- Max. Abweichung pro Segment: 2 LU
- Max. Gesamt-Dynamik-Reduktion: 3 dB

### §13.4.2 Emotional Arc Preservation (§S)

Über die technische Dynamik hinaus misst Aurik die emotionale Kurve:

- **Arousal-Proxy:** Energie 2–8 kHz / Gesamtenergie (16 Segmente)
- **Valence-Proxy:** Spektrales Zentroid 200–2000 Hz (16 Segmente)
- **Kriterium:** Pearson-Korrelation > 0.85 zwischen Original und restauriert

## §13.5 Formant-Stabilität (§M)

Menschliche Stimmen sind besonders empfindlich gegenüber DSP-Artefakten.
Aurik überwacht nach stimm-beeinflussenden Phasen (Denoise, Dereverb):

- Spektrales Zentroid 200–4000 Hz (F2-Proxy)
- Harmonizität (HNR)
- **Grenzwert:** F2-Drift < 8 %, HNR-Verlust < 15 %

## §13.6 Stereo-Integrität (§N)

Das menschliche Ohr lokalisiert Schallquellen über interaurale Zeit- und
Pegeldifferenzen. Aurik schützt das Stereobild:

- ICCC (Interchannel Cross-Correlation) 200–8000 Hz
- **Grenzwert:** ICCC-Drop < 0.15 (15 %)
- Phasen: 13, 14, 15 werden überwacht

## §13.7 Bass-Punch-Balance (§L)

Die Balance zwischen „wummerndem" Sub-Bass und „knackigem" Kick ist
genre-abhängig und entscheidend für den Höreindruck:

- **Sub-Bass (20–60 Hz):** Energie-Integral
- **Kick-Punch (60–200 Hz):** Energie-Integral
- **Ratio:** Sub/Kick, Ziel 0.5–1.5 je nach Genre
- **Grenzwert:** Abweichung > 80 % vom Original → Stärke reduzieren

## §13.8 Qualitäts-Schwellwerte (Material-adaptiv)

| Material | Min. MOS | Min. Goal-Mean | Max. Defect-Residual |
|----------|----------|---------------|---------------------|
| Wachszylinder | 3.5 | 0.45 | 0.55 |
| Schellack | 3.8 | 0.50 | 0.50 |
| Vinyl | 4.0 | 0.60 | 0.40 |
| Kassette | 3.8 | 0.55 | 0.45 |
| Tonband | 4.2 | 0.65 | 0.35 |
| CD/Digital | 4.5 | 0.80 | 0.15 |

## §13.9 Referenz-Track-Kalibrierung (§V)

Der Nutzer kann eine Referenz-Aufnahme bereitstellen („so soll es klingen").
Aurik analysiert das Referenz-Spektrum (10 Bänder), LUFS, Stereo-Breite,
Dynamik-Range und passt die Goal-Targets entsprechend an.

Aktivierung: `restore(audio, sr, reference_audio=reference_array)`
