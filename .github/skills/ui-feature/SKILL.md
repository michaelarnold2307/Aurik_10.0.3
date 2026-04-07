---
name: ui-feature
description: "Implementiert UI/Frontend-Features für Aurik 9 (PyQt5, Signale, Thread-Safety). Use when: Qt, QWidget, Signal, Progress, Thread-Safety, ModernMainWindow, BatchProcessingThread, Shortcut, Bridge, _dispatch_to_gui, preanalysis, magic button, waveform, defect animation."
argument-hint: "Welches UI-Feature? (z.B. 'Progress-Bar hängt', 'neues Signal hinzufügen')"
---

# Aurik 9 — UI/Frontend-Feature implementieren

## Thread-Safety (ABSOLUTES VERBOT)

**Kein Qt-Widget-Zugriff aus Hintergrundthreads.**

```python
# Pattern: Signal-Dispatch
_gui_dispatch = pyqtSignal(object)
# connect: self._gui_dispatch.connect(lambda fn: fn())
# Aufruf aus Thread:
self._dispatch_to_gui(lambda: widget.setText("..."))
# Alternative:
QTimer.singleShot(0, lambda: widget.setText("..."))
```

## Progress Bar (ModernMainWindow)

- **`setRange(0, 10000)`** immer — 1 Einheit = 0.01 %
- Signale senden 0–100, Slot skaliert `v * 100`
- `setValue(10000)` = Completion
- **VERBOTEN**: `setRange(0, 100)` in ModernMainWindow

## Shortcuts (`_setup_shortcuts`)

| Key | Aktion |
|---|---|
| Space | Play/Pause |
| A | Original |
| B | Restauriert |
| Ctrl+O | Öffnen |
| Ctrl+S | Export |
| Ctrl+R | Restoration |
| Ctrl+Shift+R | Studio 2026 |
| Escape | Abbruch |
| Ctrl+Z | Pfad-Clipboard |
| L | Lyrics-Overlay |

## BatchProcessingThread — Signal-Kontrakt

| Signal | Typ |
|---|---|
| `item_started` | `str` (path) |
| `item_progress` | `str, int` (0–100) |
| `item_finished` | `str` |
| `item_finished_with_result` | `str, object` |
| `item_error` | `str, str` |
| `all_finished` | — |
| `defect_update` | `dict` |
| `phase_update` | `str` |
| `waveform_data` | `ndarray, int` |
| `mode_update` | `str` |
| `ml_status_update` | `bool, list` |
| `phase_progress` | `int` (0–100) |
| `scan_progress` | `float` (0.0–1.0) |
| `quality_update` | `float` (0.0–5.0) |

`progress_callback`-Signatur: `(pct: int, msg: str, elapsed_s: float = 0.0) → None`

## Echtzeit-UX-Features (§11.4a)

| Feature | Implementierung |
|---|---|
| Phase-Fortschritt | `phase_progress_bar` (5 px, lila Gradient) unter Hauptleiste |
| Defekte-Animation | Count-up (22 Frames × 85 ms); `_PHASE_REDUCES` senkt Scores ×0.3 |
| Varianten-Wettkampf | `★name_1 (4.12) › name_2 (3.87)` Rangliste |
| Quality-Meter | `quality_meter_widget.set_mos()`, startet 2.5 → 4.2 |
| Phasen-Erklärung | `_PHASE_EXPL`-Dict (22 Einträge) → Statuszeile |
| Waveform-Scan | oranger Cursor (12px Glow + 2px DashLine), `set_scan_pos(-1.0)` aus |
| Vorab-Hörprobe | `QTimer.singleShot(1400, _auto_preview_restored)` — erste 5 s |

## §11.4b Schadensmarker-Lebenszyklus

| Phase | Waveform | Defekt-Chip |
|---|---|---|
| `detected` | Farbiger Marker (saturierte Farbe je Defekttyp) erscheint per Count-up-Animation | Roter/amber Severity-Chip mit Fortschrittsbalken |
| `correcting` | Marker bleibt sichtbar bis Phasenanfang; verschwindet sobald Score ≤ 0.01 (`_tick_defect_removal`, 75 ms per Pop) | Amber → orange bei aktivem Repair; `🔧 Defektname` mit hellem Hintergrund |
| **Phase abgeschlossen** (score ≤ 0.01) | **Marker verschwindet vollständig** aus der Wellenform — kein grünes Overlay | **Grüner Haken-Chip** (kein Fortschrittsbalken) — `&#10003; Defektname` in `#4DC878`, Rand `rgba(77,200,120,0.45)` |
| `completed` | Alle Marker verschwunden; dezente grüne Vollton-Tinte (alpha 14) | Grüne Haken-Chips für alle behobenen Defekte |

### Implementierungs-Details

- `_show_resolved_markers = False` — keine grünen Overlay-Rechtecke in der Wellenform (§11.4b)
- `_tick_defect_removal()` in `WaveformWidget`: 75 ms Timer, 1–2 Instanzen pro Tick; verschiebt Segmente nach `_resolved_locations` + setzt `_recently_resolved_ts[dk]` für optionale Flash-Logik
- **Haken-Chip-Rendering**: wenn `fix_ratio >= _green_threshold` (0.75 bei `completed`, 0.95 sonst) → kein `_bar`, nur `&#10003; name` mit grünem Border-Chip
- **Fortschrittsbalken** (`■■■■■`, `■■■□□`, `■□□□□`) nur bei nicht-aufgelösten Chips
- Chip-HTML-Struktur für Haken: `<span style="...background:rgba(77,200,120,0.13);border:1px solid rgba(77,200,120,0.45);border-radius:4px;padding:0 5px;">&#10003; Name</span>`

## Async-Analyse-Kette (Datei-Öffnen)

5 Daemon-Threads: `_bg_load` → `_carrier_bg` → `_detect_era_genre_bg` → `_estimate_restorability_bg` → `_run_defect_scan_bg`

### Magic-Button-Synchronisations-Gate

Buttons bleiben deaktiviert bis **beide** fertig: `_run_defect_scan_bg` UND `_detect_era_genre_bg`.
Freigabe über `_try_signal_preanalysis_done(flag)` → `_finalize_preanalysis()`.
Timeout: `QTimer.singleShot(15_000, _preanalysis_timeout)`.

**VERBOTEN**: `_set_magic_buttons_enabled(True)` direkt in _run_defect_scan_bg oder _detect_era_genre_bg.

### State-Reset in `_load_file`
```python
_preanalysis_flags: set[str] = set()
_preanalysis_timeout_fired = False
_preanalysis_finalized_for = ""
```

### `_carrier_bg` Pflicht-Invarianten (v9.10.97)
- MUSS `get_medium_detector().detect(audio, sr, file_ext=...)` nutzen — NICHT `medium_classifier.classify_medium()`
- `MediumDetectionResult.transfer_chain` → HTML mit `&nbsp;→&nbsp;`
- `chip_era`: **NIEMALS** `_show_chip(self.chip_era, ...)` — Ära steht im detected_medium_label

## Watchdog-Timer

```python
QTimer(self); setSingleShot(True)
_per_file_ms = max(5_400_000, int(audio_dur_s * 32_000) + 1_800_000)
_watchdog_ms = max(5_400_000, n_files * _per_file_ms)  # Min 90 Min
# Callback: requestInterruption() → wait(3000) → terminate()
```

## Bridge-Fallback (`_BRIDGE_AVAILABLE`)

```python
try:
    from backend.api.bridge import export_guard, ...
    _BRIDGE_AVAILABLE = True
except ImportError:
    _BRIDGE_AVAILABLE = False
    # Stubs: _export_guard vollständig (NaN+Clip), alle anderen: return None
```

### Bridge-Funktionen (vollständige Liste)
`export_guard`, `get_audio_file_validator`, `get_defect_scanner`, `get_defect_type`,
`get_quality_mode`, `get_restorer_classes`, `get_medium_classifier_fn`, `get_era_classifier_fn`,
`get_genre_classifier_fn`, `get_restorability_estimator_class`, `get_carrier_forensics_fn`,
`get_audio_exporter_class`, `cache_defect_result`, `get_cached_defect_result`,
`clear_defect_cache`, `warmup_models_background`

## KMV Stufe-2 UI

- `refinement_progress_bar`: 3 px, türkis `#00BCD4`, unter phase_progress_bar
- Text: `"ML-Veredelung: 3/5 Phasen verbessert..."`
- Fertig: `"Export vollständig restauriert ✓ — ML-Qualität"` (5 s Notification)
- Escape → `requestInterruption()` trifft BatchThread UND MLRefinementThread

### MLRefinementThread Signale
```python
refinement_started(str, int)      # output_path, n_deferred
refinement_phase_done(str, float) # phase_id, quality_delta
refinement_progress(int, str)     # 0–100, phase_name
refinement_complete(str, object)  # output_path, RestorationResult
refinement_cancelled(str)         # output_path
```

## No-Competing-Instances

- Single-Orchestrator: `get_aurik_denker()` Singleton
- `isRunning()==True` → neue Starts blockieren
- Atomisches Schreiben: `.tmp` → `os.replace`
- UI-Gating: Magic-Buttons während Verarbeitung deaktiviert

> Frontend liegt in: `Aurik910/` (NICHT `frontend/`)
> Vollständige UX-Spezifikation: `.github/specs/08_architecture_and_distribution.md` §11.4
