---
name: aurik-dsp-decision
description: "Wählt DSP-Algorithmen und SOTA-Modelle für Aurik 9. Use when: SOTA, Modell, Fallback, OMLSA, PGHI, STFT, FFT, Wiener, LPC, Crossfade, Dithering, MRSA, Frequenzband, Phase-Rekonstruktion, Normalisierung, LUFS, Export."
argument-hint: "Welcher DSP-Bereich? (z.B. 'NR-Modell für Vinyl wählen', 'PGHI vs Griffin-Lim')"
---

# Aurik DSP Decision Guide — SOTA Model & Algorithm Selection

## Entscheidungsbaum: Wann welches Modell?

[Material-Type] × [DefectType] → [Modell-Empfehlung]

## SOTA-ML-Entscheidungsmatrix

| Aufgabe | PRIMÄR | FALLBACK | VERBOTEN |
|---|---|---|---|
| Noise Reduction (Vocals/Gesang) | DeepFilterNet v3.II (energy_bias=−6 dB Pflicht) | OMLSA+IMCRA | DTLN, RNNoise |
| Noise Reduction (rein instrumental) | OMLSA/IMCRA (kein Vocal-Prior) | DeepFilterNet v3.II (energy_bias=−9 dB) | DTLN, RNNoise |
| Stem Separation Vocals | MelBandRoformer (`bs_roformer_plugin`) | MDX23C (Kim_Vocal_2), NMF-β | OpenUnmix |
| Stem Separation Instrumental | MDX23C (`mdx23c_plugin`, Kim_Inst) | HTDemucs-6s (Legacy), NMF-β | OpenUnmix |
| Audio Super-Resolution | AudioSR | Sinusoidal + Stoch. Modeling | SEGAN |
| Codec Artefakte | Apollo | Resemble-Enhance | MetricGAN+ |
| Pitch Estimation | FCPE | CREPE → PESTO → pYIN | SWIPE, YIN |
| Vocoding | Vocos 48 kHz nativ | Vocos 44,1 kHz → BigVGAN v2 → HiFi-GAN | WaveNet RT |
| Inpainting generativ | Flow Matching | CQTdiff+ → DiffWave | einfache Interpolation |
| Audio Tagging | BEATs iter3 | PANNs CNN14 | — |
| MOS-Schätzung Musik | VERSA | SingMOS (Gesang) → PQS-MOS (eigen) | DNSMOS, NISQA, CDPAM, PESQ |
| Dereverb | SGMSE+ (`sgmse_plugin`, TorchScript) | WPE (nara_wpe) → NumPy-WPE → OMLSA | einfacher Bandpass |
| Lyrics-Transcription | Whisper-Tiny ONNX | energy_segmentation_dsp | — |

## Verbotene Modelle & Begründungen

- PESQ: Sprach-Metrik (Telefonband 300–3400 Hz), ungeeignet für Musik
- DNSMOS: DNS-Challenge (Sprach-Corpus), nicht für Musikrestaurierung validiert
- NISQA: Sprach-NarrowBand-CNN, keine Musikperzeption
- STOI: Nur Sprachverständlichkeit (150–5000 Hz), kein Musik-Maß
- DTLN: Für RT-Sprach-Denoising optimiert, zerstört musikalische Obertöne
- RNNoise: WebRTC-Sprach-Stack, kein Musik-Support
- SEGAN: Überpädagogischer Ansatz, Artefakte bei Musik
- MetricGAN+: STOI-optimiert → Musik-irrelevant
- OpenUnmix: Veraltet, schlechtere Separation als MDX23C
- WaveNet RT: Zu langsam für RT, Artefakte bei Nicht-Sprache
- POLQA: Sprach-Metrik (wie PESQ), keine Musikvalidierung

> **Grundsätzlich**: Aurik restauriert **Musik mit Gesang**, keine gesprochene Sprache.
> Sprach-optimierte Modelle (DNS4, DTLN, RNNoise, DNSMOS, PESQ, NISQA, STOI)
> sind für Musik kontraproduktiv — sie modellieren Formant-Trajektorien und
> Sprachpausen-Statistik, nicht harmonische Strukturen und Transienten.

## Integrations-Checklist (neue Modelle)

1. [ ] Lokal gebündelt (kein Download-Code in Produktion)
2. [ ] models/manifest.json v2 Eintrag
3. [ ] SHA256-Prüfsumme hinterlegt
4. [ ] Post-2018-DSP-Fallback definiert
5. [ ] SR=48000 Konformität geprüft
6. [ ] Musik-spezifischer Benchmark (nicht PESQ/DNSMOS)
7. [ ] Material × DefectType Mapping eingetragen
8. [ ] Plugin-Policy-Konformität (§11.3 specs/08)
9. [ ] Thread-safe Singleton-Integration

## Versionsmatrix

| Modell | Version | Eingebunden seit |
|---|---|---|
| DeepFilterNet | v3.II | Aurik 9.0 |
| MelBandRoformer | 860 MB ONNX | Aurik 9.10.x |
| HTDemucs | 6s ONNX | Aurik 9.10.x |
| MDX23C | Kim_Vocal_2 / Kim_Inst | Aurik 9.0 (Fallback) |
| Apollo | v1 TorchScript | Aurik 9.0 |
| FCPE | ONNX | Aurik 9.10.x |
| CREPE | full ONNX | Aurik 9.0 (Fallback) |
| Vocos | 48 kHz nativ ONNX | Aurik 9.10.x |
| BEATs | iter3 ONNX 90 MB | Aurik 9.10.x |
| PANNs | CNN14 ONNX | Aurik 9.0 (Fallback) |
| VERSA | PyTorch Checkpoint | Aurik 9.10.x |
| SGMSE+ | TorchScript 251 MB | Aurik 9.10.x |
| WPE | nara_wpe | Aurik 9.10.43 (Fallback) |
| Flow Matching | ONNX/PT | Aurik 9.10.x |
| Whisper-Tiny | ONNX 39 MB | Aurik 9.10.46b |
| HiFi-GAN | V2 ONNX | Aurik 9.0 (Fallback) |
| DiffWave | ONNX | Aurik 9.0 (Fallback) |
| Resemble-Enhance | ONNX 722 MB | Aurik 9.0 (Fallback) |

## DSP-Pflichtregeln (immer gültig)

### MRSA-Zonen (5 Pflicht-Zonen)
| Zone | FFT-Size | Bereich |
|---|---|---|
| sub_bass | 65536 | < 80 Hz |
| mid_low | 16384 | 80–500 Hz |
| mid | 8192 | 500 Hz–4 kHz |
| presence | 1024 | 4–8 kHz |
| air | 128 | > 8 kHz |

PGHI per Zone, Kreuzfade Hanning 10 ms. **VERBOTEN**: willkürliche FFT-Größen.

### Phase-Rekonstruktion
- **PGHI** nach jeder Spektral-Modifikation (bewahrt IPD → Raumtiefe)
- **VERBOTEN**: `griffinlim()` als Studio-Endschritt → Vocos/HiFi-GAN
- **VERBOTEN**: `np.fft.rfft/istft` ohne PGHI nach Magnitude-Änderung

### Normalisierung
- **LUFS ITU-R BS.1770-5** — immer
- **VERBOTEN**: RMS- oder Peak-Normalisierung

### Dithering (Export)
- **Primär**: POW-r Typ 3
- **Fallback**: TPDF
- **VERBOTEN**: Truncation ohne Dithering

### MP3-Export
LAME VBR V0 (`ffmpeg q:a=0`, bis 320 kbps, ≈245 kbps Ø).
**VERBOTEN**: CBR für Restaurierungsausgaben (Pre-Echo auf Transienten).

### LPC
Ord. 30–40 bei 48 kHz. **VERBOTEN**: Ordnung < 16.

### Wiener-Filter
**VERBOTEN** als primärer NR: `scipy.signal.wiener()` → OMLSA/DeepFilterNet.

### Print-Through (Phase 29, reel_tape)
Bidirektionale LMS mit alpha_pre ≠ alpha_post. **VERBOTEN**: Comb-Filter oder symmetrisches Modell.

### Vintage Aesthetics (§5)
- **SOFT_SATURATION** (Röhren/Tape) = BEWAHREN
- **CLIPPING** (flat_tops > 0.1 % UND THD_odd > THD_even×1.5) = REPARIEREN
- 1920–1940: Rolloff ≤ 7 kHz nicht erweitern, H2/H4 bewahren
- 1940–1975: phase_22 nur emulieren, nie eliminieren

### §2.12 PolyphonicSpeedCurveEstimator
BasicPitch ONNX → Konfidenz-Median ≥ 2 Voices → Savitzky-Golay.
`try_allocate("BasicPitch", 0.12)` Pflicht. GrooveMetric DTW ≤ 8 ms.

### Chunk-Verarbeitung (§7.6)
Severity ≥ 0.6 → 5 s, ≥ 0.3 → 15 s, sonst 60 s (Min 2 s / Max 120 s).
Crossfade: Hanning 10 ms. Modul: `backend/core/adaptive_chunk_processor.py`

### §2.42 SourceFidelityReconstructor
Generationsverlust-Kompensation: `compute_correction_curve_db()` je Ära/Material.
Cap: 12.0 dB. Linear-Phase FIR (257 Taps, firwin2, boosts only).

> Vollständige DSP-Standards: `.github/specs/04_dsp_standards.md` §4.4–4.5
