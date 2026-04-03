"""
backend/core/psychoacoustic_masking_model.py — Psychoakustisches Masking-Modell (Aurik 9 §4.5)
===========================================================================
ISO 11172-3 Simultane + Temporale Maskierung als OMLSA-Gain-Modifier.
Stille-Segmente (<= SILENCE_DB) erhalten Gain ≤ SILENCE_GAIN_MAX = 0.30.
SR-Invariante: assert sr == 48000 in compute_threshold().
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

import numpy as np

# ---------------------------------------------------------------------------
# Öffentliche Konstanten (§4.5, §8.2)
# ---------------------------------------------------------------------------
SILENCE_DB: float = -40.0  # Schwelle Stille (≤ -30 dBFS, §8.2)
GAIN_FLOOR: float = 0.10  # Mindest-Gain (G_floor, §4.5)
N_BARK: int = 24  # Anzahl Bark-Bänder
SILENCE_GAIN_MAX: float = 0.30  # Maximaler Gain in Stille-Frames
POST_MASK_MS: float = 100.0  # Temporale Post-Masking-Dauer in ms

# ISO 11172-3 Masking-Slopes: alpha_b ≈ 14.5 + b [dB/Bark] — monoton steigend
_MASKING_SLOPE_DB: list[float] = [14.5 + float(b) for b in range(N_BARK)]


# ---------------------------------------------------------------------------
# MaskingResult
# ---------------------------------------------------------------------------
@dataclass
class MaskingResult:
    """Rückgabe-Container von PsychoacousticMaskingModel.compute_threshold()."""

    gain_modifier: np.ndarray  # [n_frames × 24] float32 ∈ [GAIN_FLOOR, 1.0]
    masking_threshold: np.ndarray  # [n_frames × 24] float32 ≥ 0
    silence_frames: np.ndarray  # [n_frames] bool — True = Stille (<= SILENCE_DB)
    post_mask_frames: np.ndarray  # [n_frames] bool — True = temporale Maskierung aktiv
    n_frames: int
    n_bark_bands: int = N_BARK

    # Rückwärtskomp. Alias
    @property
    def gain_mask(self) -> np.ndarray:
        return self.gain_modifier

    @property
    def threshold_bark(self) -> np.ndarray:
        return self.masking_threshold

    def as_dict(self) -> dict[str, Any]:
        return {
            "n_frames": self.n_frames,
            "n_bark_bands": self.n_bark_bands,
            "silence_fraction": float(np.mean(self.silence_frames)),
            "post_mask_fraction": float(np.mean(self.post_mask_frames)),
            "gain_modifier_mean": float(np.mean(self.gain_modifier)),
        }


# ---------------------------------------------------------------------------
# PsychoacousticMaskingModel
# ---------------------------------------------------------------------------
class PsychoacousticMaskingModel:
    """Psychoakustisches Masking-Modell (ISO 11172-3, §4.5).

    Gleichzeitige Maskierung: pro Bark-Band b:
        MT_b = Signal_b · 10^(-alpha_b / 10)
    Stille-Segmente: Gain ≤ SILENCE_GAIN_MAX = 0.30
    Perkussive Transienten: Post-Masking 50–200 ms
    """

    def __init__(self, g_floor: float = GAIN_FLOOR) -> None:
        self.g_floor = float(np.clip(g_floor, 0.0, 1.0))

    # ------------------------------------------------------------------
    # Interne Hilfsmethode
    # ------------------------------------------------------------------
    def _build_bark_bins(self, sr: int) -> np.ndarray:
        """Gibt N_BARK+1 Kanten der Bark-Bänder als float32-Array zurück.

        24 Bänder = 25 Kantenpositionen in Hz.
        Basiert auf Zwicker & Fastl (1990): BARK_EDGES_HZ.
        """
        bark_edges_hz = np.array(
            [
                20,
                100,
                200,
                300,
                400,
                510,
                630,
                770,
                920,
                1080,
                1270,
                1480,
                1720,
                2000,
                2320,
                2700,
                3150,
                3700,
                4400,
                5300,
                6400,
                7700,
                9500,
                12000,
                15500,
            ],
            dtype=np.float32,
        )
        return bark_edges_hz  # 25 Elemente = N_BARK + 1

    # ------------------------------------------------------------------
    @staticmethod
    def _build_bark_band_mask(fft_freqs: np.ndarray, bark_edges: np.ndarray) -> np.ndarray:
        """Pre-compute boolean band assignment matrix [N_BARK × n_bins].

        Returns float32 mean-weights: for each band, 1/count where bin belongs,
        so that matrix-multiply with spec_sq gives mean energy per band.
        """
        n_bins = fft_freqs.shape[0]
        mask = np.zeros((N_BARK, n_bins), dtype=np.float32)
        for b in range(N_BARK):
            sel = (fft_freqs >= bark_edges[b]) & (fft_freqs < bark_edges[b + 1])
            cnt = int(sel.sum())
            if cnt > 0:
                mask[b, sel] = 1.0 / cnt
        return mask

    # ------------------------------------------------------------------
    def compute_threshold(self, audio: np.ndarray, sr: int) -> MaskingResult:
        """Berechnet Masking-Schwelle und Gain-Modifier (vektorisiert).

        Args:
            audio: float32/64 mono oder stereo (channel-first (2,N) oder channel-last (N,2))
            sr:    Sample-Rate — MUSS 48000 sein (§6.6 SR-Invariante)

        Returns:
            MaskingResult mit gain_modifier, masking_threshold,
            silence_frames, post_mask_frames
        """
        assert sr == 48000, f"SR muss 48000 Hz sein, erhalten: {sr}"

        arr = np.nan_to_num(np.asarray(audio, dtype=np.float32))
        # Stereo → Mono: axis-korrekt für beide Konventionen (N,2) und (2,N)
        if arr.ndim == 2:
            if arr.shape[0] <= arr.shape[1]:
                # channel-first (2, N) → mean over axis=0 → (N,)
                mono = arr.mean(axis=0)
            else:
                # channel-last (N, 2) → mean over axis=1 → (N,)
                mono = arr.mean(axis=1)
        else:
            mono = arr

        if mono.size == 0:
            empty = np.zeros((1, N_BARK), dtype=np.float32)
            return MaskingResult(
                gain_modifier=np.full((1, N_BARK), self.g_floor, dtype=np.float32),
                masking_threshold=empty,
                silence_frames=np.array([True], dtype=bool),
                post_mask_frames=np.array([False], dtype=bool),
                n_frames=1,
            )

        frame = max(256, sr // 100)  # 480 samples @ 48 kHz
        hop = frame // 2

        # Cap at 60 s for masking-scalar statistics (median over time is
        # representative; avoiding 86–173 MB float64 allocations on long files
        # which can cause segfaults in numpy C extensions under memory pressure).
        _max_samples = sr * 60  # 2 880 000 @ 48 kHz
        if mono.size > _max_samples:
            # Centre crop: most musically representative region
            _start = (mono.size - _max_samples) // 2
            mono = mono[_start : _start + _max_samples]

        n_frames = max(1, (mono.size - frame) // hop + 1)

        # ── Batch-FFT: alle Frames auf einmal (eliminiert Python-Loop) ──
        # Use sliding_window_view (numpy ≥ 1.20) — safe alternative to
        # as_strided; avoids manual stride arithmetic that can segfault.
        mono_safe = np.ascontiguousarray(np.clip(np.nan_to_num(mono), -1.0, 1.0), dtype=np.float32)
        # sliding_window_view returns a read-only view (n_samples-frame+1, frame);
        # index by [::hop] to get exactly n_frames rows, then copy for rfft safety.
        segments = np.lib.stride_tricks.sliding_window_view(mono_safe, window_shape=frame)[::hop].copy()
        n_frames = segments.shape[0]  # recalculate after crop + window

        # RMS per frame (vectorized)
        rms_sq = np.mean(segments.astype(np.float64) ** 2, axis=1) + 1e-12
        rms_db = 10.0 * np.log10(rms_sq)  # 20*log10(sqrt(x)) = 10*log10(x)

        sil_frms = rms_db <= SILENCE_DB

        # Temporal post-masking (sequential — unavoidable due to state dependency)
        post_mask_frames_count = max(1, int(POST_MASK_MS * 1e-3 * sr / hop))
        post_frms = np.zeros(n_frames, dtype=bool)
        prev_loud = -999
        for i in range(n_frames):
            if not sil_frms[i]:
                prev_loud = i
            elif prev_loud >= 0 and (i - prev_loud) <= post_mask_frames_count:
                post_frms[i] = True

        # Batch FFT → power spectrum (n_frames, n_bins)
        spec_sq = np.abs(np.fft.rfft(segments, n=frame, axis=1)).astype(np.float32) ** 2

        # Pre-computed bark-band mean-weight matrix [N_BARK × n_bins]
        bark_edges = self._build_bark_bins(sr)
        fft_freqs = np.fft.rfftfreq(frame, d=1.0 / sr).astype(np.float32)
        band_mask = self._build_bark_band_mask(fft_freqs, bark_edges)

        # Band energies: (n_frames, N_BARK) via matrix multiply
        band_energy = spec_sq @ band_mask.T  # (n_frames, n_bins) @ (n_bins, N_BARK)

        # Masking threshold: ISO 11172-3 — slope attenuation per band
        slope_atten = np.array([10.0 ** (-s / 10.0) for s in _MASKING_SLOPE_DB], dtype=np.float32)  # (N_BARK,)
        mask_thr = np.maximum(0.0, band_energy * slope_atten[np.newaxis, :])

        # Gain modifier: relative band energy → gain
        total_e = np.sum(band_energy, axis=1, keepdims=True) + 1e-12  # (n_frames, 1)
        rel = band_energy / total_e * N_BARK  # (n_frames, N_BARK)

        # Default: normal masking (g = 0.3 + 0.7 * rel)
        gain_mod = np.clip(0.3 + 0.7 * rel, self.g_floor, 1.0).astype(np.float32)

        # Silence frames: gain capped at SILENCE_GAIN_MAX
        if sil_frms.any():
            g_sil = np.clip(SILENCE_GAIN_MAX * rel[sil_frms], self.g_floor, SILENCE_GAIN_MAX)
            gain_mod[sil_frms] = g_sil.astype(np.float32)

        # Post-masking frames: wider gain range
        pm_only = post_frms & ~sil_frms  # post-masking but not already silence
        if pm_only.any():
            g_pm = np.clip(0.5 + 0.5 * rel[pm_only], self.g_floor, 1.0)
            gain_mod[pm_only] = g_pm.astype(np.float32)

        gain_mod = np.nan_to_num(gain_mod)
        mask_thr = np.nan_to_num(mask_thr)
        np.clip(gain_mod, self.g_floor, 1.0, out=gain_mod)
        np.clip(mask_thr, 0.0, None, out=mask_thr)

        return MaskingResult(
            gain_modifier=gain_mod,
            masking_threshold=mask_thr,
            silence_frames=sil_frms,
            post_mask_frames=post_frms,
            n_frames=n_frames,
        )

    def apply_adaptive_gain(
        self,
        gain_mask: np.ndarray,
        masking_result: MaskingResult | np.ndarray,
    ) -> np.ndarray:
        """Skaliert gain_mask mit dem Masking-Modifier.

        Args:
            gain_mask:       [n_frames × 24] Eingangs-Gain
            masking_result:  MaskingResult oder np.ndarray (Rückwärtskomp.)

        Returns:
            Gain-Maske geclippt auf [G_floor, 1.0], NaN-frei
        """
        g = np.nan_to_num(np.asarray(gain_mask, dtype=np.float32))
        if g.ndim != 2:
            return np.clip(g, self.g_floor, 1.0)

        # MaskingResult oder raw ndarray als Masking-Modifier
        if isinstance(masking_result, MaskingResult):
            t = masking_result.gain_modifier
        else:
            t = np.nan_to_num(np.asarray(masking_result, dtype=np.float32))

        rows = min(g.shape[0], t.shape[0]) if t.ndim >= 1 else g.shape[0]
        cols = min(g.shape[1], t.shape[1]) if t.ndim == 2 else g.shape[1]
        out = g.copy()
        if t.ndim == 2 and rows > 0 and cols > 0:
            scale = np.clip(t[:rows, :cols], 0.3, 1.0)
            out[:rows, :cols] *= scale
        return np.clip(np.nan_to_num(out), self.g_floor, 1.0)


# ---------------------------------------------------------------------------
# Singleton (§3.2 Double-Checked Locking)
# ---------------------------------------------------------------------------
_instance: PsychoacousticMaskingModel | None = None
_lock = threading.Lock()


def get_masking_model() -> PsychoacousticMaskingModel:
    """Thread-sicherer Singleton-Accessor."""
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = PsychoacousticMaskingModel()
    return _instance


# Alias für Rückwärtskompatibilität
def get_psychoacoustic_masking_model() -> PsychoacousticMaskingModel:
    return get_masking_model()


# ---------------------------------------------------------------------------
# Convenience-Funktion
# ---------------------------------------------------------------------------
def compute_masking_threshold(audio: np.ndarray, sr: int) -> MaskingResult:
    """Convenience-Wrapper: Masking-Schwelle berechnen."""
    return get_masking_model().compute_threshold(audio, sr)


__all__ = [
    "GAIN_FLOOR",
    "N_BARK",
    "SILENCE_DB",
    "SILENCE_GAIN_MAX",
    "_MASKING_SLOPE_DB",
    "MaskingResult",
    "PsychoacousticMaskingModel",
    "compute_masking_threshold",
    "get_masking_model",
    "get_psychoacoustic_masking_model",
]
