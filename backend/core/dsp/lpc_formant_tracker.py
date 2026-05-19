"""
§2.35c [RELEASE_MUST] LPC-Formant-Tracker für Shellac-Material — Aurik 9.12.0

Burg-LPC-basierte Formant-Schätzung für schmalbandiges Material (BW ≤ 8 kHz).
Wenn MelBandRoformer / MDX23C / NMF / HPSS fehlschlagen, ist dies der finale
DSP-Fallback für Formant-Enhancement auf Shellac/WaxCylinder.

Ziel: F1–F3 schätzen + leichter Formant-Boosting (max +3 dB) → Vokalklarheit
verbessern ohne Artefakte einzuführen.

§0 Primum non nocere: Kein Eingriff wenn Formant-Schätzung unsicher (< 3 stabile Frames).
"""

from __future__ import annotations

import logging
import threading
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# Maximaler Boost pro Formant (§2.35c — kein Over-Processing)
_MAX_FORMANT_BOOST_DB = 3.0
# LPC-Ordnung: §4.4 VERBOTEN: LPC < 12 as primary.
# Strategie: Downsampling auf 16 kHz → LPC Ordnung 16 (§4.4 "alternativ: Downsampling
# auf 16 kHz → LPC Ord. 16 → Upsampling"). Bei 16 kHz SR sind F1–F4 (< 8 kHz) sicher
# erfasst; bei 48 kHz nativ bräuchte man Ord. 30–40 — hier nutzen wir den sicheren
# Downsampling-Pfad, da Shellac BW ≤ 8 kHz und Ordnung 16 @ 16 kHz ausreicht.
_LPC_ANALYSIS_SR = 16_000  # Analyse-SR nach Downsampling
_LPC_ORDER = 16  # Ordnung 16 bei 16 kHz (entspricht ~30 bei 48 kHz)
# Analyse-Bandbreite für Shellac (BW ≤ 8 kHz Material-Ceiling)
_SHELLAC_BW_HZ = 7000.0


def _burg_lpc(x: np.ndarray, order: int) -> np.ndarray:
    """
    Burg-Algorithmus für LPC-Koeffizienten (schnell, numerisch stabil).

    Returns:
        a: LPC-Koeffizienten [1, a1, a2, ..., a_order]
    """
    n = len(x)
    f = x.copy().astype(np.float64)
    b = x.copy().astype(np.float64)

    a = np.zeros(order + 1, dtype=np.float64)
    a[0] = 1.0
    k_coeffs = np.zeros(order, dtype=np.float64)

    for m in range(1, order + 1):
        num = -2.0 * float(np.dot(f[m:], b[: n - m]))
        denom = float(np.dot(f[m:], f[m:]) + np.dot(b[: n - m], b[: n - m])) + 1e-10
        k = num / denom
        k_coeffs[m - 1] = k

        a_new = a.copy()
        for i in range(1, m + 1):
            a_new[i] = a[i] + k * a[m - i]
        a = a_new

        f_new = f[m:] + k * b[: n - m]
        b_new = b[: n - m] + k * f[m:]
        f = f_new
        b = b_new

    return a


def _lpc_to_formants(a: np.ndarray, sr: int, max_formants: int = 4) -> list[float]:
    """
    Extrahiert Formantfrequenzen aus LPC-Koeffizienten via Polstellen-Analyse.

    Returns:
        Sortierte Liste von Formantfrequenzen in Hz (nur stimmhafte, F0–max_formants)
    """
    roots = np.roots(a)
    # Nur Wurzeln mit positivem Imaginärteil (eine pro konjugiertem Paar)
    roots = roots[np.imag(roots) > 0.01]
    if len(roots) == 0:
        return []

    angles = np.angle(roots)
    formants_hz = sorted([float(ang * sr / (2.0 * np.pi)) for ang in angles if ang > 0])
    # Filter: nur sinnvolle Vokalformanten (50 Hz – 4500 Hz für Shellac)
    formants_hz = [f for f in formants_hz if 50.0 <= f <= 4500.0]
    return formants_hz[:max_formants]


def _formant_boost_eq(
    audio: np.ndarray,
    sr: int,
    formants_hz: list[float],
    boost_db: float = 2.0,
) -> np.ndarray:
    """
    Sanfter Formant-Boost via Biquad-Peaking-Filter (Bell-EQ) um F1–F3.

    §0 Primum non nocere: boost_db ≤ _MAX_FORMANT_BOOST_DB (3 dB).
    """
    from scipy.signal import sosfiltfilt  # pylint: disable=import-outside-toplevel

    boost_db = float(np.clip(boost_db, 0.0, _MAX_FORMANT_BOOST_DB))
    if boost_db < 0.1 or not formants_hz:
        return audio

    out = audio.copy().astype(np.float64)
    for f_hz in formants_hz[:4]:  # F1–F4 (inkl. Singer's Formant 3–4 kHz, §0p)
        if f_hz <= 0 or f_hz >= sr / 2.0:
            continue
        # Q-Wert: breit genug für Formant-Envelope, eng genug um Nachbar nicht zu berühren
        q = max(1.5, f_hz / 250.0)
        # Biquad Peaking EQ (cookbook: Robert Bristow-Johnson)
        A = 10.0 ** (boost_db / 40.0)
        w0 = 2.0 * np.pi * f_hz / sr
        alpha = np.sin(w0) / (2.0 * q)
        b0 = 1.0 + alpha * A
        b1 = -2.0 * np.cos(w0)
        b2 = 1.0 - alpha * A
        a0 = 1.0 + alpha / A
        a1 = -2.0 * np.cos(w0)
        a2 = 1.0 - alpha / A
        sos_eq = np.array([[b0 / a0, b1 / a0, b2 / a0, 1.0, a1 / a0, a2 / a0]])
        if out.ndim == 2:
            for ch in range(out.shape[1] if out.shape[0] > 2 else out.shape[0]):
                if out.shape[0] > 2:  # (N, 2)
                    out[:, ch] = sosfiltfilt(sos_eq, out[:, ch])
                else:  # (2, N)
                    out[ch, :] = sosfiltfilt(sos_eq, out[ch, :])
        else:
            out = sosfiltfilt(sos_eq, out)

    return np.clip(out, -1.0, 1.0).astype(np.float32)


def lpc_formant_enhance(
    audio: np.ndarray,
    sr: int,
    max_boost_db: float = 2.5,
    frame_len_ms: float = 30.0,
    hop_len_ms: float = 10.0,
    min_voiced_frames: int = 3,
) -> np.ndarray[Any, Any]:
    """
    §2.35c LPC-Formant-Enhancement für Shellac (DSP-Fallback).

    Schätzt F1–F3 über mehrere Frames (Burg-LPC Ordnung 12), mittelt stabile
    Schätzungen, und boosted diese Frequenzbereiche sanft (max 3 dB).

    Args:
        audio:            Mono oder Stereo (float32)
        sr:               Abtastrate (48000 oder downsampled für Analyse)
        max_boost_db:     Maximaler Boost (Default: 2.5 dB, nie > 3.0 dB)
        frame_len_ms:     Framelänge für LPC-Analyse (Default: 30 ms)
        hop_len_ms:       Hop-Länge (Default: 10 ms)
        min_voiced_frames: Mindest-Frames für stabile Formant-Schätzung

    Returns:
        audio mit Formant-Enhancement (gleiche Form/Länge wie Input)
    """
    audio_in: np.ndarray[Any, Any] = np.asarray(audio, dtype=np.float32)
    if audio_in.ndim == 2:
        mono = np.mean(audio_in, axis=1 if audio_in.shape[0] <= 8 else 0).astype(np.float64)
    else:
        mono = audio_in.astype(np.float64)

    n = len(mono)
    if n < int(0.1 * sr):
        logger.debug("LPC-Formant-Tracker: zu kurz (%.1f s) — übersprungen", n / sr)
        return audio_in

    frame_len = int(frame_len_ms / 1000.0 * sr)
    # hop_len at native SR is not used after downsampling — analysis uses _hop_len_16k

    if frame_len < 64 or n < frame_len:
        return audio_in

    # §4.4 Downsampling auf 16 kHz für LPC-Analyse (Ordnung 16 bei 16 kHz).
    # Shellac BW ≤ 8 kHz → Nyquist bei 16 kHz reicht vollständig aus.
    # Rücktransformation nur für EQ-Anwendung, nicht für das Ausgangssignal.
    try:
        import resampy  # type: ignore[import]  # pylint: disable=import-outside-toplevel

        mono_16k: np.ndarray = resampy.resample(mono, sr, _LPC_ANALYSIS_SR).astype(np.float64)
        _analysis_sr = _LPC_ANALYSIS_SR
    except Exception:
        # Fallback: scipy resample wenn resampy nicht verfügbar
        try:
            from scipy.signal import resample_poly as _rspoly  # pylint: disable=import-outside-toplevel

            _ratio_num = _LPC_ANALYSIS_SR
            _ratio_den = sr
            from math import gcd as _gcd  # pylint: disable=import-outside-toplevel

            _g = _gcd(_ratio_num, _ratio_den)
            mono_16k = _rspoly(mono, _ratio_num // _g, _ratio_den // _g).astype(np.float64)
            _analysis_sr = _LPC_ANALYSIS_SR
        except Exception:
            mono_16k = mono.copy()
            _analysis_sr = sr

    # Frame-Parameter für Analyse-SR
    frame_len_16k = int(frame_len_ms / 1000.0 * _analysis_sr)
    _hop_len_16k = int(hop_len_ms / 1000.0 * _analysis_sr)
    n_16k = len(mono_16k)

    if frame_len_16k < 32 or n_16k < frame_len_16k:
        return audio_in

    # Analyse auf tiefpassgefiltertem Signal (Shellac-BW ≤ 8 kHz)
    try:
        from scipy.signal import butter, sosfilt  # pylint: disable=import-outside-toplevel

        nyq = min(_SHELLAC_BW_HZ, _analysis_sr / 2.0 - 100.0)
        if nyq > 100.0:
            sos_lp = butter(4, nyq, btype="low", fs=_analysis_sr, output="sos")
            mono_lp = sosfilt(sos_lp, mono_16k)
        else:
            mono_lp = mono_16k.copy()
    except Exception:
        mono_lp = mono_16k.copy()

    # Frame-weise LPC + Formant-Extraktion
    all_formants: list[list[float]] = []
    for fi in range(0, n_16k - frame_len_16k, _hop_len_16k):
        frame = mono_lp[fi : fi + frame_len_16k]
        # Voiced-Gate: Rahmen mit genug Energie
        rms = float(np.sqrt(np.mean(frame**2)))
        if rms < 1e-4:
            continue
        try:
            a = _burg_lpc(frame * np.hanning(len(frame)), _LPC_ORDER)
            frms = _lpc_to_formants(a, _analysis_sr)
            if len(frms) >= 2:
                all_formants.append(frms)
        except Exception:
            continue

    if len(all_formants) < min_voiced_frames:
        logger.debug(
            "LPC-Formant-Tracker: zu wenige stabile Frames (%d < %d) — kein Boost",
            len(all_formants),
            min_voiced_frames,
        )
        return audio_in

    # Robuste Mittelung (Median pro Formant-Index)
    max_n_formants = max(len(fs) for fs in all_formants)
    stable_formants: list[float] = []
    for k in range(min(3, max_n_formants)):
        vals = [fs[k] for fs in all_formants if len(fs) > k]
        if len(vals) >= min_voiced_frames:
            stable_formants.append(float(np.median(vals)))

    if not stable_formants:
        return audio_in

    logger.debug(
        "§2.35c LPC-Formant-Tracker: F1-F3 = %s (max_boost=%.1f dB)",
        [f"{f:.0f} Hz" for f in stable_formants],
        max_boost_db,
    )

    return _formant_boost_eq(audio_in, sr, stable_formants, boost_db=min(max_boost_db, _MAX_FORMANT_BOOST_DB))


# ---------------------------------------------------------------------------
# Thread-safe Singleton
# ---------------------------------------------------------------------------


def check_formant_shift_db(
    audio_pre: np.ndarray,
    audio_post: np.ndarray,
    sr: int,
    threshold_db: float = 2.0,
    max_formants: int = 4,
) -> tuple[bool, float]:
    """§G1/§G5 Formant ±2 dB Guard (§0p RELEASE_MUST).

    Compares spectral energy at F1–F4 formant frequencies between pre-NR and
    post-NR audio. Returns (rollback_needed, max_shift_db).

    Uses a ±semitone band (±5.9%) around each detected formant frequency to
    measure energy shift. G_floor for LPC analysis uses a 2 s mid-segment window.
    """
    try:
        # Mono conversion
        def _to_mono(a: np.ndarray) -> np.ndarray:
            a = np.asarray(a, dtype=np.float32)
            if a.ndim == 2:
                result = np.mean(a, axis=0) if a.shape[0] == 2 and a.shape[1] > 2 else np.mean(a, axis=1)
                return np.asarray(result, dtype=np.float32)
            return a

        pre_m = _to_mono(audio_pre)
        post_m = _to_mono(audio_post)
        n = min(len(pre_m), len(post_m))
        if n < int(0.1 * sr):
            return False, 0.0  # too short — skip

        # Use 2 s mid-segment for analysis
        win = min(int(2.0 * sr), n)
        mid = n // 2
        pre_seg = pre_m[mid - win // 2 : mid - win // 2 + win].astype(np.float64)
        post_seg = post_m[mid - win // 2 : mid - win // 2 + win].astype(np.float64)

        # Downsample to 16 kHz for LPC formant analysis
        ds = max(1, sr // 16000)
        pre_ds = pre_seg[::ds]
        sr_ds = sr // ds

        # Estimate LPC coefficients on the pre-segment and extract formants
        try:
            a = _burg_lpc(pre_ds * np.hanning(len(pre_ds)), _LPC_ORDER)
            formants_hz = _lpc_to_formants(a, sr_ds, max_formants=max_formants)
        except Exception:
            return False, 0.0
        if not formants_hz:
            return False, 0.0

        # FFT for spectral energy measurement (native sr, 4096 bins)
        n_fft = 4096
        freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)
        _pre_buf = pre_seg[:n_fft] if len(pre_seg) >= n_fft else np.pad(pre_seg, (0, n_fft - len(pre_seg)))
        spec_pre = np.abs(np.fft.rfft(_pre_buf)) + 1e-12
        _post_buf = post_seg[:n_fft] if len(post_seg) >= n_fft else np.pad(post_seg, (0, n_fft - len(post_seg)))
        spec_post = np.abs(np.fft.rfft(_post_buf)) + 1e-12

        # Measure energy at each formant band (±semitone ≈ ±5.9%)
        max_shift = 0.0
        for f_hz in formants_hz:
            if f_hz <= 0 or f_hz >= sr / 2.0:
                continue
            f_lo = f_hz * 0.941  # -1 semitone
            f_hi = f_hz * 1.059  # +1 semitone
            band_mask = (freqs >= f_lo) & (freqs <= f_hi)
            if not np.any(band_mask):
                continue
            e_pre = float(np.mean(spec_pre[band_mask] ** 2))
            e_post = float(np.mean(spec_post[band_mask] ** 2))
            if e_pre > 1e-20:
                shift_db = abs(10.0 * np.log10(max(e_post, 1e-20) / e_pre))
                max_shift = max(max_shift, shift_db)

        rollback = max_shift > threshold_db
        return rollback, max_shift
    except Exception:
        return False, 0.0


class _LPCFormantTracker:
    """Singleton-Wrapper für lpc_formant_enhance."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def enhance(self, audio: np.ndarray, sr: int, max_boost_db: float = 2.5) -> np.ndarray:
        """Wendet an: LPC formant enhancement to audio (thread-safe)."""
        with self._lock:
            return lpc_formant_enhance(audio, sr, max_boost_db=max_boost_db)

    def track(self, audio: np.ndarray, sr: int) -> dict:
        """Gibt formant frequencies from LPC analysis zurück.

        Returns dict with keys ``f1_mean``, ``f2_mean``, ``f3_mean``, ``f4_mean``
        (Hz, 0.0 if not detected). Used by phase_03/20/29 formant integrity checks.
        """
        try:
            mono = np.asarray(audio, dtype=np.float32)
            if mono.ndim == 2:
                mono = np.mean(mono, axis=0) if mono.shape[0] == 2 and mono.shape[1] > 2 else np.mean(mono, axis=1)
            if mono.size < 64:
                return {"f1_mean": 0.0, "f2_mean": 0.0, "f3_mean": 0.0, "f4_mean": 0.0}

            # Bound analysis cost: use a centered max-2s window before LPC estimation.
            max_win = min(mono.size, int(max(sr, 1) * 2.0))
            mid = mono.size // 2
            start = max(0, mid - max_win // 2)
            mono_win = mono[start : start + max_win]

            ds = max(1, sr // 16000)
            mono_ds = mono_win[::ds].astype(np.float64)
            sr_ds = max(1, sr // ds)
            if mono_ds.size <= (_LPC_ORDER + 1):
                return {"f1_mean": 0.0, "f2_mean": 0.0, "f3_mean": 0.0, "f4_mean": 0.0}

            windowed = mono_ds * np.hanning(len(mono_ds))
            lpc_a = _burg_lpc(windowed, _LPC_ORDER)
            formants = _lpc_to_formants(lpc_a, sr_ds, max_formants=4)
            keys = ["f1_mean", "f2_mean", "f3_mean", "f4_mean"]
            result = dict.fromkeys(keys, 0.0)
            for i, f in enumerate(formants[:4]):
                result[keys[i]] = float(f)
            return result
        except Exception:
            return {"f1_mean": 0.0, "f2_mean": 0.0, "f3_mean": 0.0, "f4_mean": 0.0}


_tracker_instance: _LPCFormantTracker | None = None
_tracker_lock = threading.Lock()


def get_lpc_formant_tracker() -> _LPCFormantTracker:
    """Singleton-Zugriff auf den LPC-Formant-Tracker."""
    global _tracker_instance  # pylint: disable=global-statement
    if _tracker_instance is None:
        with _tracker_lock:
            if _tracker_instance is None:
                _tracker_instance = _LPCFormantTracker()
    return _tracker_instance
