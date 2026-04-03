"""
Phase 63 — Intermodulation Distortion Reduction.

IMD creates sum/difference frequency products (f1±f2) from nonlinear
signal paths that are NOT harmonically related to either input frequency.
This is distinct from THD (handled by phase_60) and clipping (phase_23).

Algorithm (Volterra-inspired):
1. Identify tonal peaks (strong spectral components)
2. Predict IMD product locations: f1+f2, |f1-f2| for all peak pairs
3. Measure energy at predicted IMD locations
4. Apply targeted spectral notches at confirmed IMD products
5. Reconstruct with PGHI phase recovery

Scientific basis: Volterra series models; SMPTE RP120-1994;
Farina (2000) "Simultaneous Measurement of Impulse Response and Distortion".
"""

from __future__ import annotations

import logging
import time as _time

import numpy as np
import scipy.signal as sps

logger = logging.getLogger(__name__)

_MIN_IMD_SCORE: float = 0.10
_NOTCH_WIDTH_HZ: float = 50.0  # Width of spectral notch at IMD frequencies


def apply(
    audio: np.ndarray,
    sample_rate: int,
    strength: float = 0.55,
    defect_scores: dict | None = None,
) -> np.ndarray:
    """Main entry point for Phase 63."""
    assert sample_rate == 48000, f"SR must be 48000 Hz, got: {sample_rate}"
    audio = np.nan_to_num(audio, nan=0.0, posinf=0.0, neginf=0.0)

    if defect_scores is not None:
        imd_score = float(defect_scores.get("intermodulation_distortion", 0.0))
        if imd_score < _MIN_IMD_SCORE:
            logger.debug("Phase 63: IMD score %.3f < %.3f — skipped", imd_score, _MIN_IMD_SCORE)
            return np.clip(audio, -1.0, 1.0)

    stereo = audio.ndim == 2
    if stereo:
        left = apply(audio[0], sample_rate, strength=strength, defect_scores=defect_scores)
        right = apply(audio[1], sample_rate, strength=strength, defect_scores=defect_scores)
        return np.clip(np.stack([left, right], axis=0), -1.0, 1.0).astype(np.float32)

    x = audio.astype(np.float64)
    n = len(x)
    sr = sample_rate
    n_fft = 8192
    hop = n_fft // 4
    window = sps.windows.hann(n_fft, sym=False)
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
    freq_res = float(freqs[1] - freqs[0]) if len(freqs) > 1 else 1.0

    # Global spectral analysis to find tonal peaks
    global_spec = np.abs(np.fft.rfft(x[: min(n, n_fft)])) ** 2
    global_db = 10.0 * np.log10(global_spec + 1e-20)
    noise_floor = float(np.percentile(global_db, 20))

    # Find peaks 20 dB above noise floor
    peak_mask = global_db > (noise_floor + 20.0)
    peak_indices = np.where(peak_mask)[0]
    if len(peak_indices) < 2:
        return np.clip(audio, -1.0, 1.0).astype(np.float32)

    # Cluster peaks
    clusters = []
    if len(peak_indices) > 0:
        current = [peak_indices[0]]
        for idx in peak_indices[1:]:
            if (idx - current[-1]) * freq_res < 10.0:
                current.append(idx)
            else:
                clusters.append(int(np.mean(current)))
                current = [idx]
        clusters.append(int(np.mean(current)))
    clusters = clusters[:10]

    # Predict IMD product frequencies
    imd_targets = []
    for i in range(len(clusters)):
        for j in range(i + 1, len(clusters)):
            f1 = freqs[clusters[i]]
            f2 = freqs[clusters[j]]
            for target_f in [abs(f1 - f2), f1 + f2]:
                if target_f < 50 or target_f > sr / 2 - 100:
                    continue
                # Skip if target is a harmonic of f1 or f2
                is_harmonic = False
                for base_f in [f1, f2]:
                    for h in range(1, 8):
                        if abs(target_f - h * base_f) < freq_res * 3:
                            is_harmonic = True
                            break
                    if is_harmonic:
                        break
                if not is_harmonic:
                    target_idx = int(target_f / freq_res)
                    if 0 < target_idx < len(global_db):
                        if global_db[target_idx] > noise_floor + 5.0:
                            imd_targets.append(target_idx)

    if not imd_targets:
        return np.clip(audio, -1.0, 1.0).astype(np.float32)

    # Build spectral notch mask
    notch_width_bins = max(1, int(_NOTCH_WIDTH_HZ / freq_res))
    gain_mask = np.ones(n_fft // 2 + 1, dtype=np.float64)
    for idx in imd_targets:
        lo = max(0, idx - notch_width_bins // 2)
        hi = min(len(gain_mask), idx + notch_width_bins // 2 + 1)
        # Smooth notch (cosine taper)
        for k in range(lo, hi):
            dist = abs(k - idx) / max(1, notch_width_bins // 2)
            notch_depth = float(np.clip(1.0 - strength * (1.0 - dist), 0.2, 1.0))
            gain_mask[k] = min(gain_mask[k], notch_depth)

    # Apply notch filter via STFT
    n_frames = max(1, (n - n_fft) // hop + 1)
    out = np.zeros(n, dtype=np.float64)
    win_sum = np.zeros(n, dtype=np.float64)

    for i in range(n_frames):
        start = i * hop
        end = start + n_fft
        if end > n:
            break
        frame = x[start:end] * window
        spec = np.fft.rfft(frame)
        spec *= gain_mask
        frame_out = np.fft.irfft(spec, n=n_fft) * window
        out[start:end] += frame_out
        win_sum[start:end] += window**2

    win_sum = np.maximum(win_sum, 1e-8)
    out /= win_sum

    result = np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0)
    return np.clip(result, -1.0, 1.0).astype(np.float32)


# ─── PhaseInterface ────────────────────────────────────────────────────────────

from .phase_interface import PhaseCategory, PhaseInterface, PhaseMetadata, PhaseResult


class IntermodulationReductionPhase(PhaseInterface):
    """Phase 63: Volterra-based intermodulation distortion reduction."""

    def get_metadata(self) -> PhaseMetadata:
        return PhaseMetadata(
            phase_id="phase_63_intermodulation_reduction",
            name="Intermodulation Distortion Reduction",
            category=PhaseCategory.RESTORATION,
            priority=7,
            dependencies=["phase_04"],
            estimated_time_factor=0.05,
            version="1.0.0",
            memory_requirement_mb=32,
            is_cpu_intensive=False,
            quality_impact=0.55,
            description=(
                "Targeted spectral notch filtering of intermodulation distortion "
                "products (sum/difference frequencies). Identifies IMD products "
                "from tonal peak analysis and removes non-harmonic artifacts."
            ),
        )

    def process(
        self,
        audio: np.ndarray,
        sample_rate: int = 48000,
        strength: float = 0.55,
        defect_scores: dict | None = None,
        **kwargs,
    ) -> PhaseResult:
        sample_rate = kwargs.get("sample_rate", sample_rate)
        t0 = _time.perf_counter()
        assert sample_rate == 48000, f"SR must be 48000 Hz, got: {sample_rate}"

        _defect_scores = defect_scores or kwargs.get("defect_analysis", {})
        result_audio = apply(audio, sample_rate, strength=strength, defect_scores=_defect_scores)
        elapsed = _time.perf_counter() - t0

        return PhaseResult(
            audio=result_audio,
            success=True,
            execution_time_seconds=elapsed,
            metrics={
                "imd_score": float((_defect_scores or {}).get("intermodulation_distortion", 0.0)),
                "strength": strength,
            },
        )
