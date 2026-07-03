"""Final human-hearing comfort guard for restored exports.

The guard is deliberately conservative:
- it attenuates only candidate peaks that overshoot the reference by a large margin;
- it restores small HF losses by boosting the candidate's own HF component only;
- it never copies reference samples and never synthesizes new material.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
from scipy import signal

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HumanHearingComfortResult:
    """Result of the final comfort guard."""

    audio: np.ndarray
    peak_overshoot_frames: int = 0
    max_peak_overshoot_db: float = 0.0
    hf_loss_db_before: float = 0.0
    hf_loss_db_after: float = 0.0
    hf_lift_db: float = 0.0
    applied: bool = False


def apply_human_hearing_comfort_guard(
    reference_audio: np.ndarray,
    candidate_audio: np.ndarray,
    sr: int,
    *,
    max_peak_overshoot_db: float = 3.0,
    max_hf_loss_db: float = 0.75,
    max_hf_lift_db: float = 1.2,
) -> HumanHearingComfortResult:
    """Apply a final reference-aware comfort guard.

    Args:
            reference_audio: Input/degraded reference, same layout as candidate.
            candidate_audio: Restored candidate audio.
            sr: Sample rate in Hz.
            max_peak_overshoot_db: Allowed per-frame candidate peak overshoot.
            max_hf_loss_db: Tolerated median 6-16 kHz loss vs reference.
            max_hf_lift_db: Hard cap for candidate-owned HF lift.

    Returns:
            HumanHearingComfortResult with clipped float32 audio.
    """
    ref = np.asarray(reference_audio, dtype=np.float32)
    cand = np.asarray(candidate_audio, dtype=np.float32)
    if ref.shape != cand.shape or cand.size < max(2048, int(sr * 0.25)):
        return HumanHearingComfortResult(audio=np.asarray(cand, dtype=np.float32))

    out = np.nan_to_num(cand.copy(), nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)
    ref = np.nan_to_num(ref, nan=0.0, posinf=0.0, neginf=0.0).astype(np.float32)

    out, overshoot_frames, max_overshoot = _attenuate_peak_overshoot(
        ref,
        out,
        sr,
        max_peak_overshoot_db=max_peak_overshoot_db,
    )

    hf_before = _median_band_delta_db(ref, out, sr, band=(6000.0, 16000.0), support_band=(500.0, 4000.0))
    hf_lift = 0.0
    if hf_before < -float(max_hf_loss_db):
        target_loss = -0.25
        hf_lift = float(np.clip(target_loss - hf_before, 0.0, max_hf_lift_db))
        if hf_lift > 0.05:
            boosted = _boost_candidate_hf(out, sr, hf_lift)
            hf_boosted = _median_band_delta_db(ref, boosted, sr, band=(6000.0, 16000.0), support_band=(500.0, 4000.0))
            if hf_boosted > hf_before:
                if hf_boosted > target_loss:
                    denom = max(hf_boosted - hf_before, 1e-6)
                    alpha = float(np.clip((target_loss - hf_before) / denom, 0.0, 1.0))
                    out = (alpha * boosted + (1.0 - alpha) * out).astype(np.float32)
                    hf_lift *= alpha
                else:
                    out = boosted

    out, residual_overshoot_frames, _ = _attenuate_peak_overshoot(
        ref,
        out,
        sr,
        max_peak_overshoot_db=max_peak_overshoot_db,
    )
    overshoot_frames = max(int(overshoot_frames), int(residual_overshoot_frames))

    out = np.clip(np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0), -1.0, 1.0).astype(np.float32)
    hf_after = _median_band_delta_db(ref, out, sr, band=(6000.0, 16000.0), support_band=(500.0, 4000.0))
    applied = bool(overshoot_frames > 0 or hf_lift > 0.05)
    if applied:
        logger.info(
            "HumanHearingComfortGuard: peak_frames=%d max_peak_overshoot=%.2fdB hf_before=%.2fdB hf_after=%.2fdB hf_lift=%.2fdB",
            overshoot_frames,
            max_overshoot,
            hf_before,
            hf_after,
            hf_lift,
        )
    return HumanHearingComfortResult(
        audio=out,
        peak_overshoot_frames=int(overshoot_frames),
        max_peak_overshoot_db=round(float(max_overshoot), 3),
        hf_loss_db_before=round(float(hf_before), 3),
        hf_loss_db_after=round(float(hf_after), 3),
        hf_lift_db=round(float(hf_lift), 3),
        applied=applied,
    )


def _to_mono_time(audio: np.ndarray) -> np.ndarray:
    arr = np.asarray(audio, dtype=np.float32)
    if arr.ndim <= 1:
        mono: np.ndarray = np.asarray(arr.reshape(-1), dtype=np.float32)
        return mono
    if arr.shape[0] <= 2 and arr.shape[1] > 2:
        mono = np.asarray(np.mean(arr, axis=0, dtype=np.float32), dtype=np.float32)
        return mono
    if arr.shape[1] <= 2 and arr.shape[0] > 2:
        mono = np.asarray(np.mean(arr, axis=1, dtype=np.float32), dtype=np.float32)
        return mono
    axis = 1 if arr.shape[0] >= arr.shape[1] else 0
    mono = np.asarray(np.mean(arr, axis=axis, dtype=np.float32), dtype=np.float32)
    return mono


def _apply_time_gain(audio: np.ndarray, gain: np.ndarray) -> np.ndarray:
    arr = np.asarray(audio, dtype=np.float32).copy()
    n = min(len(gain), arr.shape[-1] if arr.ndim <= 1 else max(arr.shape))
    if arr.ndim <= 1:
        arr[:n] *= gain[:n]
    elif arr.shape[0] <= 2 and arr.shape[1] >= n:
        arr[:, :n] *= gain[:n][None, :]
    elif (arr.shape[1] <= 2 and arr.shape[0] >= n) or arr.shape[0] >= arr.shape[1]:
        arr[:n, :] *= gain[:n][:, None]
    else:
        arr[:, :n] *= gain[:n][None, :]
    result: np.ndarray = np.asarray(arr, dtype=np.float32)
    return result


def _attenuate_peak_overshoot(
    reference: np.ndarray,
    candidate: np.ndarray,
    sr: int,
    *,
    max_peak_overshoot_db: float,
) -> tuple[np.ndarray, int, float]:
    ref_mono = _to_mono_time(reference)
    cand_mono = _to_mono_time(candidate)
    n = min(len(ref_mono), len(cand_mono))
    frame = max(1024, int(sr * 0.25))
    n_frames = n // frame
    if n_frames < 2:
        return candidate, 0, 0.0

    ref_frames = ref_mono[: n_frames * frame].reshape(n_frames, frame)
    cand_frames = cand_mono[: n_frames * frame].reshape(n_frames, frame)
    ref_peak = np.max(np.abs(ref_frames), axis=1)
    cand_peak = np.max(np.abs(cand_frames), axis=1)
    ref_rms = np.sqrt(np.mean(ref_frames**2, axis=1) + 1e-20)
    overshoot_db = 20.0 * np.log10((cand_peak + 1e-12) / (ref_peak + 1e-12))
    active = ref_rms > 10.0 ** (-55.0 / 20.0)
    needs = active & (overshoot_db > float(max_peak_overshoot_db))
    if not bool(np.any(needs)):
        return candidate, 0, float(np.max(overshoot_db))

    envelope_margin_db = 1.25
    gain_db_frames = np.zeros(n_frames, dtype=np.float32)
    gain_db_frames[needs] = np.asarray(
        max_peak_overshoot_db - envelope_margin_db - overshoot_db[needs],
        dtype=np.float32,
    )
    centers = np.arange(n_frames, dtype=np.float64) * frame + frame * 0.5
    gain_db = np.interp(np.arange(n, dtype=np.float64), centers, gain_db_frames).astype(np.float32)
    gain_db = np.minimum(gain_db, 0.0)
    gain_db = _smooth_gain_db(gain_db, sr)
    gain = np.power(10.0, gain_db / 20.0).astype(np.float32)
    out = _apply_time_gain(candidate, gain)
    return out, int(np.sum(needs)), float(np.max(overshoot_db[needs]))


def _smooth_gain_db(gain_db: np.ndarray, sr: int) -> np.ndarray:
    attack = max(1, int(0.010 * sr))
    release = max(1, int(0.080 * sr))
    attack_a = float(np.exp(-1.0 / attack))
    release_a = float(np.exp(-1.0 / release))
    smoothed = gain_db.astype(np.float32).copy()
    for idx in range(1, len(smoothed)):
        target = float(smoothed[idx])
        prev = float(smoothed[idx - 1])
        alpha = attack_a if target < prev else release_a
        smoothed[idx] = np.float32(alpha * prev + (1.0 - alpha) * target)
    result: np.ndarray = np.asarray(smoothed, dtype=np.float32)
    return result


def _median_band_delta_db(
    reference: np.ndarray,
    candidate: np.ndarray,
    sr: int,
    *,
    band: tuple[float, float],
    support_band: tuple[float, float],
) -> float:
    ref = _to_mono_time(reference)
    cand = _to_mono_time(candidate)
    n = min(len(ref), len(cand))
    if n < 2048:
        return 0.0
    ref = ref[:n]
    cand = cand[:n]
    freqs, _, ref_stft = signal.stft(ref, fs=sr, nperseg=2048, noverlap=1536, window="hann", boundary=None)
    _, _, cand_stft = signal.stft(cand, fs=sr, nperseg=2048, noverlap=1536, window="hann", boundary=None)
    t = min(ref_stft.shape[1], cand_stft.shape[1])
    if t < 1:
        return 0.0
    ref_pow = np.abs(ref_stft[:, :t]) ** 2 + 1e-20
    cand_pow = np.abs(cand_stft[:, :t]) ** 2 + 1e-20
    band_mask = (freqs >= band[0]) & (freqs <= band[1])
    support_mask = (freqs >= support_band[0]) & (freqs <= support_band[1])
    if not bool(np.any(band_mask)) or not bool(np.any(support_mask)):
        return 0.0
    support = np.sum(ref_pow[support_mask], axis=0)
    active = support > np.percentile(support, 35.0)
    if not bool(np.any(active)):
        active = np.ones(t, dtype=bool)
    ref_band = np.sum(ref_pow[band_mask], axis=0)[active]
    cand_band = np.sum(cand_pow[band_mask], axis=0)[active]
    delta = 10.0 * np.log10((cand_band + 1e-20) / (ref_band + 1e-20))
    return float(np.percentile(delta, 50.0))


def _boost_candidate_hf(candidate: np.ndarray, sr: int, gain_db: float) -> np.ndarray:
    gain = float(10.0 ** (float(gain_db) / 20.0))
    sos = signal.butter(2, 6000.0, btype="highpass", fs=sr, output="sos")
    arr = np.asarray(candidate, dtype=np.float32)
    if arr.ndim <= 1:
        hf = signal.sosfiltfilt(sos, arr).astype(np.float32)
        out = arr + (gain - 1.0) * hf
    elif arr.shape[0] <= 2 and arr.shape[1] > 2:
        hf = signal.sosfiltfilt(sos, arr, axis=1).astype(np.float32)
        out = arr + (gain - 1.0) * hf
    else:
        hf = signal.sosfiltfilt(sos, arr, axis=0).astype(np.float32)
        out = arr + (gain - 1.0) * hf
    result: np.ndarray = np.asarray(
        np.clip(np.nan_to_num(out, nan=0.0, posinf=0.0, neginf=0.0), -1.0, 1.0),
        dtype=np.float32,
    )
    return result
