# Aurik 10 — Spec 14: Vollständigkeit & Perfektion

> **Version:** Aurik 10.0.1 · **Scope:** Fehlertoleranz, Reproduzierbarkeit, Ressourcen, Export-Intelligenz, Batch-Lernen
> **Status:** Normativ — alle hier spezifizierten Konzepte sind verbindlich. Implementierungsstatus pro § angegeben.

---

## §14.0 Prinzip

Aurik darf keinen Raum für „das hätte man noch verbessern können" lassen.
Jede Eventualität ist spezifiziert. Jeder Fehlerpfad ist definiert. Jede
Ressourcenentscheidung ist begründet. Jedes Exportformat ist material-adaptiv.

---

## IMPLEMENTIERT

### §14.1 ✅ Export-Intelligenz (Frontend-gesteuert)
### §14.2.1 ✅ ML-Fallback (PluginLifecycleManager)
### §14.2.2 ✅ Phase-Fehler-Handling (try/finally)
### §14.2.3 ✅ OOM-Schutz (OOM_PROBE + GC)
### §14.3 ✅ Seed-Deterministik (Phasen-Selektion)
### §14.4 ✅ Ressourcen-Budget (PerformanceGuard + ml_memory_budget)
### §14.5 ✅ Batch-Session (BatchSessionLearner)

## ROADMAP

### §14.2.4 ⏸️ Crash-Recovery (State-Serialisierung nötig)
### §14.7 ⏸️ Multi-Format Input (Mono/Surround/Ambisonics)
### §14.8 ⏸️ Non-Destructive Undo (delta_audio-Speicherung)
### §14.9 ⏸️ A/B-Vergleich (compare/delta/band_solo)
### §14.10 ⏸️ Umgebungs-Kompensation (Kopfhörer/Nahfeld/Auto)

---

**§14.1.1 Bit-Tiefe**
| Material | Bittiefe | Begründung |
|---|---|---|
| Wachszylinder, Schellack (≤1955) | 16-bit | Dynamikumfang < 40 dB → kein 24-bit-Gewinn |
| Vinyl, Kassette, Tonband | 16-bit | Max. Rauschabstand ~60 dB → 16-bit ausreichend |
| DAT, MiniDisc, CD/Digital | 24-bit | 96+ dB Dynamikumfang rechtfertigt 24-bit |
| Studio 2026 Modus | 24-bit | Produktionsqualität |

**§14.1.2 Sample-Rate**
| Eingang | Ausgang | Begründung |
|---|---|---|
| ≤48 kHz | 48 kHz | Standard-Restaurationsrate |
| 88.2/96 kHz | 96 kHz | Erhalt der vollen Bandbreite |
| >96 kHz | 96 kHz | Kein hörbarer Gewinn über 48 kHz Nyquist |

**§14.1.3 Container**
| Anwendungsfall | Format |
|---|---|
| Archiv/Produktion | FLAC (Level 8, 16/24-bit) |
| Streaming/Vorschau | FLAC (Level 5, 16-bit) |
| CD-kompatibel | WAV (16-bit, 44.1 kHz) |

---

## §14.2 Fehlertoleranz & Graceful Degradation (§14.2)

**§14.2.1 ML-Modell-Ausfall**
JEDES ML-Modell MUSS einen DSP-Fallback-Pfad haben. Kein Modell-Ausfall
darf die Pipeline blockieren. Reihenfolge der Fallbacks:
1. ONNX-Modell (primär)
2. PyTorch-Modell (sekundär, falls ONNX fehlschlägt)
3. DSP-Fallback (tertiär, deterministisch)
4. Passthrough (letzter Fallback — Audio unverändert zurückgeben)

**§14.2.2 Phase-Fehler**
Jede Phase wird in try/except mit `logger.warning()` ausgeführt.
Ein Phasen-Fehler:
- Bricht NUR die fehlerhafte Phase ab
- Gibt das unveränderte Audio zurück
- Loggt Phase-Name, Exception-Typ, Exception-Message
- Setzt `restoration_context["phase_errors"][phase_id] = error_info`
- Die Pipeline läuft mit den verbleibenden Phasen weiter

**§14.2.3 OOM-Schutz**
Vor jeder Phase: `OOM_PROBE` loggt RSS und verfügbaren RAM.
Bei < 2 GB verfügbar: ML-Modelle entladen, GC erzwingen.
Bei < 500 MB verfügbar: Pipeline mit Graceful-Degradation fortsetzen.

**§14.2.4 Crash-Recovery**
Nach jedem Phasen-Erfolg wird ein Recovery-Point geschrieben:
```python
RecoveryPoint(
    phase_id: str,
    audio_checksum: str,  # SHA256 der ersten 4096 Samples
    timestamp: float,
    rss_gb: float,
)
```
Bei Neustart: Recovery-Points prüfen, ab letztem erfolgreichen Punkt fortsetzen.

---

## §14.3 Deterministische Reproduzierbarkeit (§14.3)

**§14.3.1 Seed-basierte Deterministik**
```python
restore(audio, sr, seed=42)  # → immer identisches Ergebnis
```
Der Seed beeinflusst:
- Zufällige Initialisierungen (STFT-Fenster-Position)
- ML-Modell-Inferenz (deterministischer Mode)
- Dithering (Rausch-Generator mit Seed)

**§14.3.2 Nicht-deterministische Operationen (explizit deklariert)**
- ONNX GPU-Inferenz (hängt vom GPU-Treiber ab)
- Parallele Thread-Execution (nicht-deterministische Reihenfolge)
- System-Rauschquellen (Dithering-Qualität)

**§14.3.3 Reproduzierbarkeits-Garantie**
Audio-Identität (SHA256) bei gleichem Seed garantiert für:
- Alle DSP-Operationen
- Alle CPU-ML-Inferenzen
- Alle Export-Formate

---

## §14.4 Ressourcen-Budget-Enforcement (§14.4)

**§14.4.1 Zeit-Budget**
Vor Pipeline-Start: `time_budget_s = audio_duration_s × 32` (Quality-Mode).
`PerformanceGuard` überwacht kontinuierlich:
- Bei 80% Budget: Phasen mit `phase_priority=low` überspringen
- Bei 95% Budget: Nur `_NEVER_SKIP`-Phasen ausführen
- Bei 100% Budget: Pipeline mit bestem Zwischenergebnis beenden

**§14.4.2 RAM-Budget**
`ml_memory_budget` verwaltet 10.4 GB Pool:
- Plugin-Load: Budget prüfen → bei Überschreitung LRU-Entladung
- Plugin-Lifecycle-Manager: Look-Ahead-Entladung vor großen Phasen
- ROM-Modelle (ONNX) haben Vorrang vor RAM-Modellen (PyTorch)

**§14.4.3 GPU-Budget**
24 GB VRAM (ROCm). Fair-Share zwischen:
- Inferenz-Modelle (DeepFilterNet, PANNs, CREPE)
- Training-freie Modelle (MERT, CLAP, Whisper)
- Batched-Inferenz für lange Audiodateien

---

## §14.5 Batch-Session-Lernen (§14.5)

**§14.5.1 Cross-File Intelligence**
`BatchSessionLearner` persistiert pro Session:
- `material_prior`: Tonträger-Verteilung über alle Files
- `era_prior`: Ära-Verteilung
- `genre_prior`: Genre-Verteilung
- `defect_prior`: Defekt-Häufigkeiten
- `restoration_params`: Erfolgreiche Parameter pro Material/Genre-Kombination

**§14.5.2 Artist-Clustering**
Bei >2 Files mit gleichem `song_id`-Präfix (gleicher Künstler):
- Stimm-Modell wird session-übergreifend gemittelt
- Genre-Klassifikation wird sicherer
- Restaurierungsparameter werden stabiler

**§14.5.3 Session-Report**
Nach Batch-Abschluss:
```json
{
  "files_processed": 12,
  "files_improved": 10,
  "files_unchanged": 1,
  "files_degraded": 0,
  "files_skipped": 1,
  "mean_mos_gain": 0.8,
  "dominant_material": "vinyl",
  "dominant_era": "1970",
  "mean_restoration_time_s": 842.3
}
```

---

## §14.6 §v9.15 ROADMAP (spezifiziert, nicht implementiert)

## §14.7 Multi-Format Input (§14.7)

- Mono: Duplizieren auf beide Kanäle. Mono-kompatible Phasen bevorzugen.
- Ambisonics (4ch): Nur Kanal 1 (omni) restaurieren, Rest passthrough.
- Surround (5.1/7.1): Front L/R restaurieren, Center mischen, Rear passthrough.
- Variable Sample-Rate: Automatisch auf 48 kHz resamplen.

## §14.8 Non-Destructive Editing History (§14.8)

Jede Phasen-Operation speichert:
- `delta_audio`: Differenzsignal (original − bearbeitet)
- `phase_params`: Vollständige Parameter
- `phase_version`: Code-Version der Phase

Vollständiges Undo/Redo durch Rückwärts-Anwendung aller Deltas.

## §14.9 A/B-Vergleichs-Framework (§14.9)

- `compare_mode`: Instant-Umschaltung Original ↔ Restauriert
- `delta_mode`: Nur das Differenzsignal abhören
- `band_solo`: Einzelne Frequenzbänder isoliert vergleichen
- `timeline_markers`: Sprung zu markanten Stellen (Strophenanfang, Refrain)

## §14.10 Wiedergabe-Umgebungs-Kompensation (§14.10)

| Umgebung | Korrektur |
|---|---|
| Kopfhörer (open) | Bass −2 dB @ 60 Hz (fehlende Raumverstärkung) |
| Kopfhörer (closed) | Bass −1 dB, Höhen +1 dB |
| Nahfeld (1m) | Neutral |
| Wohnzimmer (3m) | Bass +2 dB, Präsenz +1 dB |
| Auto | Bass +4 dB, Höhen +3 dB, Dynamics komprimiert |

## §14.11 Metadaten-Erhalt & Anreicherung (§14.11)

- Original-Tags (ID3, Vorbis, FLAC) werden 1:1 übernommen
- Aurik-eigene Tags werden hinzugefügt:
  - `AURIK_VERSION`: Version der Pipeline
  - `AURIK_SEED`: Reproduzierbarkeits-Seed
  - `AURIK_CHAIN`: Tonträgerkette
  - `AURIK_MATERIAL`: Primär-Material
  - `AURIK_ERA`: Erkannte Ära
  - `AURIK_MOS`: VERSA MOS nach Restaurierung
  - `AURIK_DURATION_S`: Verarbeitungsdauer

---

> **Letzte Änderung:** v9.20.3 — Implementiert: Export-Intelligenz, Fehlertoleranz, Deterministik,
> Ressourcen-Budget, Batch-Lernen. Roadmap: Multi-Format, Undo, A/B, Umgebung, Metadaten.
