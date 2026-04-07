---
name: ml-plugin
description: "Integriert ML-Plugins in Aurik 9 mit Memory-Budget, Fallback-Kaskaden und Headroom-Guards. Use when: Plugin, ONNX, torch, try_allocate, ml_memory_budget, Headroom, Fallback, InferenceSession, Lazy-Load, PluginLifecycleManager, release_mode, DSP-Fallback, OOM."
argument-hint: "Welches Plugin? (z.B. 'AudioSR integrieren', 'SGMSE+ Fallback debuggen')"
---

# Aurik 9 — ML-Plugin integrieren / debuggen

## Memory-Budget-Pflicht (RELEASE_MUST)

**Jeder** ML-Modell-Load MUSS diesen Ablauf einhalten:

```python
from backend.core.ml_memory_budget import get_ml_memory_budget
from backend.core.plugin_lifecycle_manager import get_plugin_lifecycle_manager

budget = get_ml_memory_budget()
plm = get_plugin_lifecycle_manager()

# 1. Budget prüfen — VOR torch.load() / InferenceSession()
if not budget.try_allocate("my_model", size_gb=1.2):
    logger.warning("ml_budget_denied model=my_model required_gb=1.2")
    budget.release("my_model")  # safety cleanup
    return _dsp_fallback(audio, sr)  # PFLICHT: DSP-Fallback

try:
    # 2. Modell laden
    model = onnxruntime.InferenceSession(path, providers=["CPUExecutionProvider"])
    # 3. LRU-Tracking registrieren
    plm.register("my_model", size_gb=1.2, unload_fn=lambda: del_model())
except Exception:
    budget.release("my_model")  # 4. IMMER release bei Fehler
    return _dsp_fallback(audio, sr)
```

### Verboten
- `plm.try_allocate()` — **existiert nicht**, nur `ml_memory_budget.try_allocate()`
- `torch.load(..., map_location="cuda")` — CPU-only
- ML-Load ohne `try_allocate()` davor

### Auto-Budget-Formel
`max(4.0, min(12.0, RAM_GB / 3))` — bei fehlendem `psutil`: keine physischen RAM-Checks.

## §2.38a Headroom-Guard (RELEASE_MUST)

Für schwere ML-Pfade (SGMSE+, ResembleEnhance, AudioSR, CQTdiff/FlowMatching):

1. **Vor Load**: Physischer RAM-Headroom prüfen (mono/stereo, Dateilänge)
2. **Bei knappem RAM**: `evict_stale_plugins()` + `gc.collect()` + `malloc_trim(0)`
3. **Wenn Guard triggert**: DSP-Fallback innerhalb derselben Phase — **kein Phase-Skip**

**Structured Fallback-Metadaten** (Pflicht in `RestorationResult.metadata["ml_guard_events"]`):
```python
{
    "phase_id": "phase_20",
    "model": "sgmse_plus",
    "reason": "insufficient_ram",
    "required_gb": 2.8,
    "available_gb": 1.9,
    "channels": 2,
    "duration_s": 240.0,
    "fallback": "wpe_dsp"
}
```

Phase MUSS in `deferred_phases` → KMV Stufe 2 zieht Vollqualität nach.

## Hybrid-Release-Mode (RELEASE_MUST)

`release_mode` ∈ `primary | fallback | blocked`

| Kaskade | Primär | Fallback 1 | Fallback 2 |
|---|---|---|---|
| Noise-Reduction | DeepFilterNet | OMLSA/IMCRA | Spectral-Gating |
| Dereverb | SGMSE+ (TorchScript) | WPE (nara_wpe) | OMLSA |
| Stem-Separation | MDX23C | NMF (SDR ≥ 5 dB) | Bypass (kein Stem-Processing) |
| Super-Resolution | AudioSR | NVSR | Spectral-Band-Replication |
| Phase-Reconstruction | MP-SENet | Vocos ONNX | PGHI-ISTFT |
| Pitch-Tracking | CREPE | pYIN | YIN |
| Music-Understanding | MERT | MFCC-Similarity (12 Koeff.) | Bypass (HPI ohne MERT) |
| MOS-Schätzung | VERSA | PQS-DSP | — |
| Inpainting | Flow Matching | CQTdiff+ | DiffWave |

**Invariante**: Kein ML-Failure darf die Pipeline vollständig abbrechen. Jeder Fallback wird in `RestorationResult.metadata["ml_fallbacks_used"]` protokolliert.

Quarantänisierte Crash-Kandidaten (z.B. RMVPE): NICHT als Primärpfad.

## Lazy-Load-Pflicht (Budget > 4 GB allein)

| Modell | Größe | Lazy-Load |
|---|---|---|
| AudioSR | 5.9 GB | Pflicht |
| MERT-v1-330M | 3.9 GB | Pflicht |

## ONNX-Sessions — Pflicht-Konfiguration

```python
session = onnxruntime.InferenceSession(
    model_path,
    providers=["CPUExecutionProvider"],
    sess_options=_get_onnx_options()
)

def _get_onnx_options():
    opts = onnxruntime.SessionOptions()
    opts.intra_op_num_threads = os.cpu_count()
    opts.graph_optimization_level = onnxruntime.GraphOptimizationLevel.ORT_ENABLE_ALL
    return opts
```

## Torch-Modelle — Pflicht-Konfiguration

```python
model = torch.jit.load(path, map_location="cpu")
model.eval()
torch.set_num_threads(os.cpu_count())
```

## MelBandRoformer (860 MB, ONNX)

48k→44.1k→48k Resampling (Lanczos-4, SNR ≈ −0.8 dB).
Bei 48k-nativem Modell dieses bevorzugen.

## SOTA-Entscheidungsmatrix (Kurzform)

| Aufgabe | PRIMÄR | FALLBACK | VERBOTEN |
|---|---|---|---|
| NR Vocals | DeepFilterNet v3.II | OMLSA+IMCRA | DTLN, RNNoise |
| NR Instrumental | OMLSA/IMCRA | DeepFilterNet (bias=−9) | DTLN, RNNoise |
| Stem-Sep Vocals | MelBandRoformer | MDX23C, NMF-β | OpenUnmix |
| Audio SR | AudioSR | Sinusoidal+Stoch | SEGAN |
| Pitch | FCPE | CREPE → PESTO → pYIN | SWIPE, YIN |
| Vocoding | Vocos 48k | BigVGAN → HiFi-GAN | WaveNet RT |
| Inpainting | Flow Matching | CQTdiff+ → DiffWave | Interpolation |
| Dereverb | SGMSE+ | WPE → OMLSA | Bandpass |

> Vollständige Matrix: `.github/specs/04_dsp_standards.md` §4.4
> Plugin-Matrix (51 Plugins): `.github/specs/08_architecture_and_distribution.md`

## Checkliste neues ML-Plugin

```
□ plugins/<name>_plugin.py
□ ml_memory_budget.try_allocate(name, size_gb) VOR Load
□ ml_memory_budget.release(name) in ALLEN Fehler-Pfaden
□ plm.register(name, size_gb, unload_fn) nach erfolgreichem Load
□ DSP-Fallback für ImportError UND Budget-Überschreitung
□ providers=["CPUExecutionProvider"] (ONNX) / map_location="cpu" (Torch)
□ Headroom-Guard für schwere Modelle (> 1 GB)
□ models/manifest.json: sha256 + bundled_path + size_gb + fallback
□ Tests als ml/slow markieren wenn Timeout ≥ 30 s
□ CHANGELOG.md Eintrag
```
