"""
Phase 62 — Crosstalk Cancellation.

Channel crosstalk in early stereo recordings where channel separation was
limited (< 20 dB).  Uses BSS-inspired spectral subtraction to improve
channel separation while preserving the stereo image.

Algorithm:
1. Compute cross-spectral density between L and R
2. Estimate crosstalk transfer function H_LR(f) and H_RL(f)
3. Apply frequency-dependent crosstalk cancellation:
   L_clean = L - alpha * H_RL(f) * R
   R_clean = R - alpha * H_LR(f) * L
4. Constrain to preserve mono compatibility and stereo width

Scientific basis: Blauert (1997) "Spatial Hearing";
Avendano & Jot (2002) "Frequency-Domain BSS".
"""

from __future__ import annotations

import logging
import time as _time

import numpy as np
import scipy.signal as sps

logger = logging.getLogger(__name__)

_MIN_CROSSTALK_SCORE: float = 0.10


def apply(
    audio: np.ndarray,
    sample_rate: int,
    strength: float = 0.5,
    defect_scores: dict | None = None,
) -> np.ndarray:
    """Main entry point for Phase 62."""
    assert sample_rate == 48000, f"SR must be 48000 Hz, got: {sample_rate}"
    audio = np.nan_to_num(audio, nan=0.0, posinf=0.0, neginf=0.0)

    if defect_scores is not None:
        xt_score = float(defect_scores.get("crosstalk", 0.0))
        if xt_score < _MIN_CROSSTALK_SCORE:
            logger.debug("Phase 62: crosstalk score %.3f < %.3f — skipped", xt_score, _MIN_CROSSTALK_SCORE)
            return np.clip(audio, -1.0, 1.0)

    # Crosstalk cancellation only applies to stereo
    if audio.ndim != 2:
        logger.debug("Phase 62: mono input — skipped (no crosstalk possible)")
        return np.clip(audio, -1.0, 1.0)

    # Ensure [channels, samples] format
    if audio.shape[0] > 2:
        # Assume [samples, channels]
        left = audio[:, 0].astype(np.float64)
        right = audio[:, 1].astype(np.float64)
        was_transposed = True
    else:
        left = audio[0].astype(np.float64)
        right = audio[1].astype(np.float64)
        was_transposed = False

    n = len(left)
    n_fft = 4096
    hop = n_fft // 4
    window = sps.windows.hann(n_fft, sym=False)

    n_frames = max(1, (n - n_fft) // hop + 1)

    # Process in STFT domain
    left_out = np.zeros(n, dtype=np.float64)
    right_out = np.zeros(n, dtype=np.float64)
    win_sum = np.zeros(n, dtype=np.float64)

    for i in range(n_frames):
        start = i * hop
        end = start + n_fft
        if end > n:
            break

        frame_l = left[start:end] * window
        frame_r = right[start:end] * window

        spec_l = np.fft.rfft(frame_l)
        spec_r = np.fft.rfft(frame_r)

        # Estimate crosstalk transfer functions
        # H_RL = cross-spectral density / auto-spectral density (R bleeds into L)
        cross_lr = spec_l * np.conj(spec_r)
        auto_l = np.abs(spec_l) ** 2 + 1e-12
        auto_r = np.abs(spec_r) ** 2 + 1e-12

        # Coherence-based crosstalk estimation
        coherence = np.abs(cross_lr) ** 2 / (auto_l * auto_r)

        # Only cancel where coherence is very high (>0.8) — indicates bleed
        xt_mask = coherence > 0.8
        alpha = float(np.clip(strength * 0.4, 0.0, 0.35))  # Conservative to avoid artifacts

        # Frequency-dependent cancellation
        h_rl = np.zeros_like(spec_l)
        h_lr = np.zeros_like(spec_r)
        h_rl[xt_mask] = cross_lr[xt_mask] / (auto_r[xt_mask])
        h_lr[xt_mask] = np.conj(cross_lr[xt_mask]) / (auto_l[xt_mask])

        # Constrain to prevent over-cancellation
        h_rl = np.clip(np.abs(h_rl), 0, 0.5) * np.exp(1j * np.angle(h_rl))
        h_lr = np.clip(np.abs(h_lr), 0, 0.5) * np.exp(1j * np.angle(h_lr))

        spec_l_clean = spec_l - alpha * h_rl * spec_r
        spec_r_clean = spec_r - alpha * h_lr * spec_l

        frame_l_out = np.fft.irfft(spec_l_clean, n=n_fft) * window
        frame_r_out = np.fft.irfft(spec_r_clean, n=n_fft) * window

        left_out[start:end] += frame_l_out
        right_out[start:end] += frame_r_out
        win_sum[start:end] += window**2

    win_sum = np.maximum(win_sum, 1e-8)
    left_out /= win_sum
    right_out /= win_sum

    # Wet/dry blend
    left_result = left * (1.0 - strength) + left_out * strength
    right_result = right * (1.0 - strength) + right_out * strength

    left_result = np.nan_to_num(left_result, nan=0.0, posinf=0.0, neginf=0.0)
    right_result = np.nan_to_num(right_result, nan=0.0, posinf=0.0, neginf=0.0)

    if was_transposed:
        result = np.stack([left_result, right_result], axis=1)
    else:
        result = np.stack([left_result, right_result], axis=0)

    return np.clip(result, -1.0, 1.0).astype(np.float32)


# ─── PhaseInterface ────────────────────────────────────────────────────────────

from .phase_interface import PhaseCategory, PhaseInterface, PhaseMetadata, PhaseResult


class CrosstalkCancellationPhase(PhaseInterface):
    """Phase 62: BSS-based crosstalk cancellation for early stereo recordings."""

    def get_metadata(self) -> PhaseMetadata:
        return PhaseMetadata(
            phase_id="phase_62_crosstalk_cancellation",
            name="Crosstalk Cancellation",
            category=PhaseCategory.RESTORATION,
            priority=6,
            dependencies=["phase_14"],
            estimated_time_factor=0.05,
            version="1.0.0",
            memory_requirement_mb=32,
            is_cpu_intensive=False,
            quality_impact=0.55,
            description=(
                "BSS-inspired crosstalk cancellation for early stereo recordings "
                "with poor channel separation. Uses frequency-dependent coherence "
                "analysis to separate genuine stereo content from channel bleed."
            ),
        )

    def process(
        self,
        audio: np.ndarray,
        sample_rate: int = 48000,
        strength: float = 0.5,
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
            metrics={"crosstalk_score": float((_defect_scores or {}).get("crosstalk", 0.0)), "strength": strength},
        )
