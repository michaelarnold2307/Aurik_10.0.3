"""sgmse_plugin — SGMSE+: Score-Based Generative Model for Speech Enhancement.

SGMSE+ (Richter et al. 2022) verwendet stochastische Differentialgleichungen (SDE)
zur Aufhebung von Rausch- und Hallprozessen. Überlegener Nachfolger von WPE für
kombinierte Enhancement + Dereverberation.

Verbesserung gegenüber WPE (2010):
    - SGMSE+ löst das inverse Problem via Score-Matching (p(clean|noisy))
    - Unterstützung breitbandiger 48 kHz Musikrestaurierung
    - Hallunterdrückung UND Rauschreduzierung in einem Schritt

Modell:
    Primär:   models/sgmse_plus/sgmse_plus.ts (~251 MB, TorchScript)
    Input:  [1, 2, n_fft//2+1, T] float32 (Real + Imag getrennt)
    Output: [1, 2, n_fft//2+1, T] float32 (denoised Real + Imag)
    Sigma:  Rauschpegel ∈ [0.01, 1.0] als skalarer Input

Fallback-Kaskade (§4.4):
    1. SGMSE+ TorchScript (dieser Plugin)
    2. WPE DSP (Nara-WPE, wpe_plugin.py)

Backward-Kompatibilität:
    Alle früheren Exporte (WpePlugin, SgmsePlugin, get_wpe_plugin, …)
    bleiben erhalten und zeigen auf wpe_plugin zur Rückwärtskompatibilität.

Referenz:
    Richter et al. "Speech Enhancement and Dereverberation with Diffusion-Based
    Generative Models" — IEEE/ACM TASLP 2022.
    https://github.com/sp-uhh/sgmse

Singleton: get_sgmse_plus_plugin() verwenden.
CPU-Only: CPUExecutionProvider.
"""

from __future__ import annotations

import logging
import math
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).parent.parent
_TS_PATH = _ROOT / "models" / "sgmse_plus" / "sgmse_plus.ts"

# Verarbeitungs-Konstanten (48 kHz)
_SR: int = 48_000
_N_FFT: int = 512  # 10.7 ms @ 48 kHz (typisch für SGMSE+)
_HOP: int = 128  # 2.7 ms
_WIN: int = 512

_lock_plus = threading.Lock()
_instance_plus: SGMSEPlusPlugin | None = None


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class SgmseResult:
    """Ergebnis der SGMSE+ Enhancement-Inferenz.

    Attributes:
        audio:      Bereinigtes / Dereverb-Audio, float32 ∈ [-1, 1]
        sr:         Sample-Rate (48000)
        model_used: "sgmse_plus_torchscript" | "wpe_dsp_fallback"
        snr_improvement_db: Geschätzter SNR-Gewinn in dB
    """

    audio: np.ndarray
    sr: int
    model_used: str
    snr_improvement_db: float = 0.0

    def __post_init__(self) -> None:
        self.audio = np.nan_to_num(self.audio, nan=0.0, posinf=0.0, neginf=0.0)
        self.audio = np.clip(self.audio, -1.0, 1.0)


# ---------------------------------------------------------------------------
# SGMSEPlusPlugin
# ---------------------------------------------------------------------------


class SGMSEPlusPlugin:
    """SGMSE+ Score-Based Speech/Music Enhancement (TorchScript-primary).

    Verarbeitet kombinierte Rausch- und Hallunterdrückung via score-basierter
    generativer Inferenz oder fällt auf WPE DSP zurück (§4.4 Spec).
    """

    def __init__(self) -> None:
        self._session: Any = None
        self._ts_model: Any = None
        self._model_loaded: bool = False
        self._try_load()

    def _try_load(self) -> None:
        """Lädt SGMSE+ TorchScript; sonst WPE-Fallback."""
        try:
            from backend.core.ml_memory_budget import try_allocate as _try_alloc
        except Exception:
            _try_alloc = None

        if _TS_PATH.exists():
            try:
                import os as _os

                import torch

                torch.set_num_threads(_os.cpu_count() or 4)  # §2.37 CPU-Thread-Budget
                if _try_alloc is not None and not _try_alloc("SGMSE+", size_gb=0.12):
                    logger.warning("SGMSE+: ML-Budget erschöpft — WPE-DSP-Fallback.")
                else:
                    self._ts_model = torch.jit.load(str(_TS_PATH), map_location="cpu")
                    self._ts_model.eval()
                    self._model_loaded = True
                    logger.info("✅ SGMSE+ TorchScript geladen (%s)", _TS_PATH.name)
                    try:
                        from backend.core.plugin_lifecycle_manager import register_plugin as _reg_plm

                        _reg_plm(
                            "SGMSE+",
                            size_gb=0.12,
                            unload_fn=lambda s=self: (
                                setattr(s, "_ts_model", None) or setattr(s, "_model_loaded", False)
                            ),
                        )
                    except Exception:
                        pass
                    return
            except Exception as exc:
                logger.warning("SGMSE+ TorchScript nicht ladbar: %s — WPE-DSP-Fallback aktiv.", exc)
                try:
                    from backend.core.ml_memory_budget import release as _rel

                    _rel("SGMSE+")
                except Exception:
                    pass

        logger.info(
            "SGMSE+ Modell nicht verfügbar (TorchScript: %s) — WPE-DSP-Fallback aktiv.",
            _TS_PATH,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    # Adaptive chunk size: 10 s when RAM is tight (< 6 GB free), else 30 s.
    # 10 s @ 48 kHz = 480k samples → STFT [1,2,257,3750] → ~15 MB + Torch
    # peak ~300–400 MB.  30 s → ~1 GB peak.  Scales to RAM pressure.
    _MAX_CHUNK_SAMPLES_LARGE: int = 30 * _SR  # 30 s — plenty of RAM
    _MAX_CHUNK_SAMPLES_SMALL: int = 10 * _SR  # 10 s — RAM-tight mode
    # 10 ms Hanning crossfade at chunk boundaries
    _OVERLAP_SAMPLES: int = int(0.01 * _SR)

    def _get_available_ram_gb(self) -> float:
        """Return available RAM in GB, or inf if psutil unavailable."""
        try:
            import psutil

            return psutil.virtual_memory().available / (1024**3)
        except Exception:
            return float("inf")

    def enhance(self, audio: np.ndarray, sr: int, sigma: float = 0.5) -> SgmseResult:
        """Kombinierte Rausch-/Hallunterdrückung via SGMSE+ oder WPE-Fallback.

        Algorithm (TorchScript-Pfad):
            1. STFT → Real/Imag [1, 2, F, T]
            2. SGMSE+ forward: score-basiertes Denoising bei Sigma σ
               (Ornstein–Uhlenbeck SDE: dx = -½βx dt + √β dW, t ∈ [0,1])
            3. ISTFT aus Enhanced Complex Spektrum

        Chunked processing (10–30 s adaptive) to prevent OOM on long files.
        RAM guard: falls < 3 GB verfügbar → WPE-DSP-Fallback sofort.

        Args:
            audio: float32, 48000 Hz, mono oder stereo
            sr:    Sample-Rate (muss 48000 sein)
            sigma: Rauschpegel-Schätzung ∈ [0.01, 1.0]. Standard 0.5 (adaptiv).

        Returns:
            SgmseResult mit bereinigtem Audio.
        """
        assert sr == 48_000, f"SR muss 48000 Hz sein, erhalten: {sr}"
        audio = np.nan_to_num(audio.astype(np.float32), nan=0.0, posinf=0.0, neginf=0.0)
        stereo = audio.ndim == 2 and audio.shape[1] == 2

        # ── RAM guard: < 3 GB available → WPE-DSP-Fallback ──────────
        # Threshold lowered from 4 GB to 3 GB to catch tighter RAM situations.
        # The SGMSE+ TorchScript SDE solver needs ≥1 GB headroom even for 10 s chunks.
        _use_ml = self._ts_model is not None
        if _use_ml:
            _avail_gb = self._get_available_ram_gb()
            if _avail_gb < 3.0:
                logger.warning(
                    "SGMSE+ RAM guard: nur %.1f GB frei (< 3 GB) — WPE-DSP-Fallback",
                    _avail_gb,
                )
                _use_ml = False

        def process_channel(ch: np.ndarray) -> np.ndarray:
            if _use_ml:
                return self._enhance_chunked(ch, sigma)
            return self._wpe_fallback(ch, sr)

        if stereo:
            left = process_channel(audio[:, 0])
            right = process_channel(audio[:, 1])
            n = min(len(left), len(right), len(audio))
            out = np.stack([left[:n], right[:n]], axis=1)
        else:
            mono = audio[:, 0] if audio.ndim == 2 else audio
            out = process_channel(mono)

        out = np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)
        out = np.clip(out, -1.0, 1.0)

        rms_in = float(np.sqrt(np.mean(audio**2))) + 1e-10
        rms_diff = float(np.sqrt(np.mean((out - audio) ** 2))) + 1e-10
        snr_imp = 20.0 * math.log10(rms_in / rms_diff) if rms_diff < rms_in else 0.0

        return SgmseResult(
            audio=out.astype(np.float32),
            sr=sr,
            model_used=("sgmse_plus_torchscript" if _use_ml else "wpe_dsp_fallback"),
            snr_improvement_db=float(np.clip(snr_imp, 0.0, 30.0)),
        )

    # ------------------------------------------------------------------
    # Chunked inference wrapper  (prevents OOM on long files)
    # ------------------------------------------------------------------

    def _enhance_chunked(self, mono: np.ndarray, sigma: float) -> np.ndarray:
        """Process mono audio in adaptive chunks (10–30 s) with Hanning crossfade.

        Adapts chunk size to available RAM:
        - ≥ 6 GB free → 30 s chunks (~1 GB peak per chunk)
        - < 6 GB free → 10 s chunks (~300 MB peak per chunk)
        Falls back to WPE if RAM drops below 2 GB between chunks.
        """
        import gc

        n_total = len(mono)

        # Adaptive chunk sizing based on available RAM
        _avail = self._get_available_ram_gb()
        if _avail < 6.0:
            chunk_len = self._MAX_CHUNK_SAMPLES_SMALL  # 10 s
            logger.info("SGMSE+ adaptive chunk: 10 s (%.1f GB frei)", _avail)
        else:
            chunk_len = self._MAX_CHUNK_SAMPLES_LARGE  # 30 s

        if n_total <= chunk_len:
            return self._enhance_torchscript(mono, sigma)

        overlap = self._OVERLAP_SAMPLES
        step = chunk_len - overlap
        out = np.zeros(n_total, dtype=np.float32)
        fade_in = np.hanning(2 * overlap)[:overlap].astype(np.float32)
        fade_out = np.hanning(2 * overlap)[overlap:].astype(np.float32)

        # Minimum RAM headroom required before each chunk.
        # 30 s chunks peak ~1 GB in U-Net forward pass; add 2.5 GB safety margin
        # for glibc heap fragmentation and OS memory pressure.
        # 10 s chunks peak ~300 MB; 1.5 GB safety margin is sufficient.
        _HEADROOM_LARGE = 3.5  # GB needed before a 30 s chunk
        _HEADROOM_SMALL = 2.0  # GB needed before a 10 s chunk

        pos = 0
        chunk_idx = 0
        while pos < n_total:
            end = min(pos + chunk_len, n_total)

            # ── Pre-chunk RAM guard ───────────────────────────────────
            # Proactively free pages before allocating the next chunk to
            # give psutil an accurate picture of truly available RAM.
            gc.collect()
            try:
                import ctypes as _ct_pre

                _ct_pre.CDLL("libc.so.6").malloc_trim(0)
            except Exception:
                pass
            _avail_pre = self._get_available_ram_gb()
            _headroom_needed = _HEADROOM_LARGE if chunk_len > self._MAX_CHUNK_SAMPLES_SMALL else _HEADROOM_SMALL
            if _avail_pre < _headroom_needed:
                logger.warning(
                    "SGMSE+ pre-chunk %d: %.1f GB frei < %.1f GB Headroom — WPE-Fallback für Rest (%.1f s)",
                    chunk_idx + 1,
                    _avail_pre,
                    _headroom_needed,
                    (n_total - pos) / _SR,
                )
                rest = self._wpe_fallback(mono[pos:], _SR)
                rest_len = min(len(rest), n_total - pos)
                out[pos : pos + rest_len] = rest[:rest_len]
                break

            chunk = mono[pos:end]
            enhanced = self._enhance_torchscript(chunk, sigma)

            if len(enhanced) < len(chunk):
                enhanced = np.pad(enhanced, (0, len(chunk) - len(enhanced)))
            elif len(enhanced) > len(chunk):
                enhanced = enhanced[: len(chunk)]

            if chunk_idx == 0:
                # First chunk: no fade-in, apply fade-out in overlap zone
                if end < n_total and len(enhanced) > overlap:
                    enhanced[-overlap:] *= fade_out
                out[pos:end] = enhanced
            else:
                # Apply fade-in at start of this chunk
                if len(enhanced) > overlap:
                    enhanced[:overlap] *= fade_in
                # Apply fade-out at end (unless last chunk)
                if end < n_total and len(enhanced) > overlap:
                    enhanced[-overlap:] *= fade_out
                # Overlap-add in crossfade zone
                out[pos : pos + overlap] += enhanced[:overlap]
                out[pos + overlap : end] = enhanced[overlap:]

            chunk_idx += 1
            pos += step

            # ── Aggressive memory cleanup between chunks ─────────────
            del chunk, enhanced
            gc.collect()
            # malloc_trim: return freed heap pages to OS immediately
            try:
                import ctypes as _ct

                _ct.CDLL("libc.so.6").malloc_trim(0)
            except Exception:
                pass

            # RAM check between chunks — adaptive: shrink or bail out
            _avail_now = self._get_available_ram_gb()
            if _avail_now < 1.5:
                logger.warning(
                    "SGMSE+ chunk %d: nur %.1f GB frei (< 1.5 GB) — rest via WPE-Fallback",
                    chunk_idx,
                    _avail_now,
                )
                # Fill remaining with WPE fallback
                if pos < n_total:
                    rest = self._wpe_fallback(mono[pos:], _SR)
                    rest_len = min(len(rest), n_total - pos)
                    out[pos : pos + rest_len] = rest[:rest_len]
                break
            elif _avail_now < 4.0 and chunk_len > self._MAX_CHUNK_SAMPLES_SMALL:
                # Downgrade to smaller chunks for remaining audio
                chunk_len = self._MAX_CHUNK_SAMPLES_SMALL
                step = chunk_len - overlap
                logger.info("SGMSE+ RAM dropping (%.1f GB) — switching to 10 s chunks", _avail_now)

        logger.info(
            "SGMSE+ chunked: %d chunks (adaptive) für %.1f s Audio, %.1f GB frei",
            chunk_idx,
            n_total / _SR,
            self._get_available_ram_gb(),
        )
        return np.clip(np.nan_to_num(out, nan=0.0), -1.0, 1.0)

    # ------------------------------------------------------------------
    # ONNX Inference (SGMSE+ deterministic forward pass @ optimal sigma)
    # ------------------------------------------------------------------

    def _stft(self, mono: np.ndarray) -> tuple[np.ndarray, int]:
        """STFT → Complex Spectrogram."""
        from scipy.signal import stft as scipy_stft

        n_orig = len(mono)
        _, _, Z = scipy_stft(
            mono.astype(np.float64),
            fs=_SR,
            nperseg=_WIN,
            noverlap=_WIN - _HOP,
            window="hann",
        )
        return Z.astype(np.complex64), n_orig

    def _istft(self, Z: np.ndarray, n_orig: int) -> np.ndarray:
        """Inverse STFT."""
        from scipy.signal import istft as scipy_istft

        _, x = scipy_istft(
            Z.astype(np.complex128),
            fs=_SR,
            nperseg=_WIN,
            noverlap=_WIN - _HOP,
            window="hann",
        )
        x = x.astype(np.float32)
        if len(x) > n_orig:
            x = x[:n_orig]
        elif len(x) < n_orig:
            x = np.pad(x, (0, n_orig - len(x)))
        return x

    def _enhance_onnx(self, mono: np.ndarray, sigma: float) -> np.ndarray:
        """SGMSE+ ONNX-Inferenz: Score-Based Enhancement."""
        assert self._session is not None
        try:
            Z, n_orig = self._stft(mono)
            # SGMSE+ input: [1, 2, F, T] — Real und Imag als separate Kanäle
            real_c = Z.real[np.newaxis, np.newaxis].astype(np.float32)
            imag_c = Z.imag[np.newaxis, np.newaxis].astype(np.float32)
            inp = np.concatenate([real_c, imag_c], axis=1)  # [1, 2, F, T]

            # ── Pad time dimension to multiple of _UNET_ALIGN ──
            T_orig = inp.shape[3]
            T_pad = (self._UNET_ALIGN - T_orig % self._UNET_ALIGN) % self._UNET_ALIGN
            if T_pad > 0:
                inp = np.pad(inp, ((0, 0), (0, 0), (0, 0), (0, T_pad)), mode="constant")

            # Sigma als skalarer Input (falls Modell diesen Eingang erwartet)
            input_names = [i.name for i in self._session.get_inputs()]
            feed: dict[str, np.ndarray] = {input_names[0]: inp}
            if len(input_names) > 1:
                feed[input_names[1]] = np.array([[[[sigma]]]], dtype=np.float32)

            ort_out = self._session.run(None, feed)
            out_arr = np.asarray(ort_out[0], dtype=np.float32)  # [1, 2, F, T]

            # ── Remove time padding ──
            if T_pad > 0:
                out_arr = out_arr[:, :, :, :T_orig]

            out_real = out_arr[0, 0] if out_arr.shape[1] >= 2 else out_arr[0, 0]
            out_imag = out_arr[0, 1] if out_arr.shape[1] >= 2 else np.zeros_like(out_real)

            Z_enhanced = (out_real + 1j * out_imag).astype(np.complex64)
            Z_enhanced = np.nan_to_num(Z_enhanced, nan=0.0, posinf=0.0, neginf=0.0)

            result = self._istft(Z_enhanced, n_orig)
            return np.clip(np.nan_to_num(result, nan=0.0), -1.0, 1.0)
        except Exception as exc:
            logger.warning("SGMSE+ ONNX-Inferenzfehler: %s — WPE-Fallback.", exc)
            return self._wpe_fallback(mono, _SR)

    # NCSNPP U-Net has ~5 downsampling steps → time dim must be multiple of 2^5=32
    # to avoid encoder/decoder skip-connection shape mismatch (torch.cat RuntimeError).
    _UNET_ALIGN: int = 32

    def _enhance_torchscript(self, mono: np.ndarray, sigma: float) -> np.ndarray:
        """SGMSE+ TorchScript-Inferenz: score [B,2,F,T] aus STFT-Features.

        Memory-optimized: avoids redundant array copies, explicitly deletes
        intermediates, and calls gc.collect + malloc_trim after inference.
        Time-dimension is zero-padded to a multiple of _UNET_ALIGN to prevent
        encoder/decoder skip-connection shape mismatches in NCSNPP.
        """
        assert self._ts_model is not None
        try:
            import gc

            import torch

            Z, n_orig = self._stft(mono)
            # Build [1, 2, F, T] tensor directly — no .copy() for y (same input)
            x_t = np.stack([Z.real, Z.imag], axis=0)[np.newaxis].astype(np.float32)
            del Z  # free complex spectrogram immediately (~44 MB per 30s)

            # ── Pad frequency dimension to multiple of _UNET_ALIGN ──
            # NCSNPP U-Net skip-connections also require aligned frequency bins.
            # Without this, audio lengths that produce F=351 bins (instead of 350)
            # trigger "Sizes of tensors must match" RuntimeError in torch.cat.
            F_orig = x_t.shape[2]
            F_pad = (self._UNET_ALIGN - F_orig % self._UNET_ALIGN) % self._UNET_ALIGN
            if F_pad > 0:
                x_t = np.pad(x_t, ((0, 0), (0, 0), (0, F_pad), (0, 0)), mode="constant")

            # ── Pad time dimension to multiple of _UNET_ALIGN ──
            T_orig = x_t.shape[3]
            T_pad = (self._UNET_ALIGN - T_orig % self._UNET_ALIGN) % self._UNET_ALIGN
            if T_pad > 0:
                x_t = np.pad(x_t, ((0, 0), (0, 0), (0, 0), (0, T_pad)), mode="constant")

            with torch.no_grad():
                xt_t = torch.from_numpy(x_t)
                # y = x_t for SGMSE+ (noisy input = conditioning) — share memory
                y_t = xt_t  # no copy — same tensor, saves ~88 MB
                t_t = torch.tensor([float(sigma)], dtype=torch.float32)
                out_t = self._ts_model(xt_t, y_t, t_t)

            del xt_t, y_t, t_t, x_t  # free torch tensors + numpy backing
            out_arr = out_t.detach().cpu().numpy().astype(np.float32)
            del out_t  # free torch output tensor

            # ── Remove time padding ──
            if T_pad > 0:
                out_arr = out_arr[:, :, :, :T_orig]

            # ── Remove frequency padding ──
            if F_pad > 0:
                out_arr = out_arr[:, :, :F_orig, :]

            out_real = out_arr[0, 0]
            out_imag = out_arr[0, 1] if out_arr.shape[1] > 1 else np.zeros_like(out_real)
            del out_arr  # free full output array, keep only slices

            Z_enhanced = (out_real + 1j * out_imag).astype(np.complex64)
            del out_real, out_imag
            Z_enhanced = np.nan_to_num(Z_enhanced, nan=0.0, posinf=0.0, neginf=0.0)
            result = self._istft(Z_enhanced, n_orig)
            del Z_enhanced

            # Aggressive cleanup: GC + malloc_trim to return memory to OS
            gc.collect()
            try:
                import ctypes as _ct

                _ct.CDLL("libc.so.6").malloc_trim(0)
            except Exception:
                pass

            return np.clip(np.nan_to_num(result, nan=0.0), -1.0, 1.0)
        except Exception as exc:
            # Detect Torch / system OOM and re-raise as Python MemoryError so
            # UV3's §2.39 OOM-Recovery-Checkpoint handler can fire instead of
            # silently swallowing the error and calling WPE (which may also OOM).
            _exc_str = str(exc).lower()
            _is_oom = any(kw in _exc_str for kw in ("not enough memory", "malloc", "out of memory", "allocat", "oom"))
            if _is_oom:
                logger.error(
                    "SGMSE+ TorchScript OOM erkannt: %s — re-raise als MemoryError für UV3-Checkpoint",
                    exc,
                )
                raise MemoryError(f"SGMSE+ Torch-OOM: {exc}") from exc
            logger.warning("SGMSE+ TorchScript-Inferenzfehler: %s — WPE-Fallback.", exc)
            return self._wpe_fallback(mono, _SR)

    # ------------------------------------------------------------------
    # WPE DSP Fallback
    # ------------------------------------------------------------------

    def _wpe_fallback(self, mono: np.ndarray, sr: int) -> np.ndarray:
        """WPE-Dereverberation als Fallback (wpe_plugin, §4.4)."""
        try:
            from plugins.wpe_plugin import get_wpe_plugin

            plugin = get_wpe_plugin()
            result = plugin.enhance(mono, sr)
            if hasattr(result, "audio"):
                return np.clip(np.nan_to_num(result.audio.flatten(), nan=0.0), -1.0, 1.0)
            # Legacy: result ist ndarray
            arr = np.asarray(result, dtype=np.float32).flatten()
            return np.clip(np.nan_to_num(arr, nan=0.0), -1.0, 1.0)
        except Exception as exc:
            logger.error("WPE-Fallback fehlgeschlagen: %s — Audio unverändert.", exc)
            return np.clip(np.nan_to_num(mono.copy(), nan=0.0), -1.0, 1.0)


# ---------------------------------------------------------------------------
# Singleton (§3.2 Double-Checked Locking)
# ---------------------------------------------------------------------------


def get_sgmse_plus_plugin() -> SGMSEPlusPlugin:
    """Thread-sicherer Singleton-Accessor für SGMSE+."""
    global _instance_plus
    if _instance_plus is None:
        with _lock_plus:
            if _instance_plus is None:
                _instance_plus = SGMSEPlusPlugin()
    return _instance_plus


def enhance_sgmse(audio: np.ndarray, sr: int, sigma: float = 0.5) -> SgmseResult:
    """Convenience-Wrapper für get_sgmse_plus_plugin().enhance()."""
    return get_sgmse_plus_plugin().enhance(audio, sr, sigma)


# ---------------------------------------------------------------------------
# Backward-Kompatibilität: WPE-Exporte aus wpe_plugin re-exportieren
# ---------------------------------------------------------------------------
from plugins.wpe_plugin import (
    SGMSEPlugin,
    SgmsePlugin,
    WpePlugin,
    enhance,
    get_sgmse_plugin,
    get_wpe_plugin,
)

__all__ = [
    "SGMSEPlugin",
    # Neue SGMSE+-Implementierung
    "SGMSEPlusPlugin",
    "SgmsePlugin",
    "SgmseResult",
    # Backward-Kompatibilität (WPE-Basis)
    "WpePlugin",
    "enhance",
    "enhance_sgmse",
    "get_sgmse_plugin",
    "get_sgmse_plus_plugin",
    "get_wpe_plugin",
]
