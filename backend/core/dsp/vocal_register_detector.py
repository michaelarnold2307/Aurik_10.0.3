"""
§2.35c [RELEASE_MUST] Vocal Register Detector — Aurik 9.12.0

Erkennt das Vokalregister (Kopfstimme / Bruststimme / Fry / Flüstern) aus dem
Audiosignal via FCPE-F0 + spektraler Flachheit. Gibt einen register-adaptiven
energy_bias_db-Wert zurück, der von NR-Algorithmen (DeepFilterNet, OMLSA, SGMSE+)
verwendet wird.

Mapping (§2.35c Spec normativ):
    Kopfstimme (head voice):  energy_bias = -3 dB  (hohe Harmonik-Dichte → konservativ)
    Bruststimme (chest voice): energy_bias = -6 dB  (Default; mittlere Harmonik-Energie)
    Fry / Flüstern:            energy_bias = -9 dB  (niedrige Harmonik-Kohärenz → aggressiver)

Singleton-Pattern (thread-safe double-checked locking).
"""

from __future__ import annotations

import logging
import threading

import numpy as np

# pylint: disable=import-outside-toplevel

logger = logging.getLogger(__name__)

# Vokalregister-Schwellen für F0-basierte Klassifikation
# Kopfstimme: F0 > 300 Hz (Sopran/Tenor-Kopfregister); Fry: F0 < 80 Hz oder stark inharmonisch
_HEAD_VOICE_F0_HZ = 300.0
_FRY_F0_HZ = 80.0
_FRY_FLATNESS_THRESHOLD = 0.60  # hohe spektrale Flachheit = wenig harmonische Struktur
_WHISPER_FLATNESS_THRESHOLD = 0.75  # sehr flach = Flüstern

# Energy-Bias-Werte pro Register (dB, negativ = Harmonik-Schutz)
_ENERGY_BIAS_HEAD = -3.0
_ENERGY_BIAS_CHEST = -6.0
_ENERGY_BIAS_FRY_WHISPER = -9.0


def _spectral_flatness(mono: np.ndarray, sr: int) -> float:
    """Mittlere spektrale Flachheit (Wiener-Entropie, [0,1])."""
    try:
        from scipy.signal import welch as _welch

        nperseg = min(2048, len(mono))
        if nperseg < 64:
            return 0.5
        _, psd = _welch(mono.astype(np.float64), fs=sr, nperseg=nperseg)
        psd = np.maximum(psd, 1e-12)
        geo_mean = float(np.exp(np.mean(np.log(psd))))
        arith_mean = float(np.mean(psd))
        return float(np.clip(geo_mean / (arith_mean + 1e-12), 0.0, 1.0))
    except Exception:
        return 0.5


def _estimate_f0_median(mono: np.ndarray, sr: int) -> float | None:
    """Schätzt medianen F0 via FCPE (Primär) → pYIN (Fallback) → None."""
    try:
        from plugins.fcpe_plugin import get_fcpe_plugin as _get_fcpe

        result = _get_fcpe().analyze(mono, sr)
        f0 = result.get("f0") if isinstance(result, dict) else None
        if f0 is not None and len(f0) > 0:
            voiced = np.asarray(f0)[np.asarray(f0) > 50.0]
            if len(voiced) >= 3:
                return float(np.median(voiced))
    except Exception:
        pass

    # pYIN-Fallback
    try:
        import librosa  # type: ignore[import]

        f0_pyin, voiced_flag, _ = librosa.pyin(
            mono.astype(np.float32),
            fmin=50.0,
            fmax=1000.0,
            sr=sr,
            frame_length=2048,
        )
        voiced_f0 = f0_pyin[voiced_flag & (f0_pyin > 0)]
        if len(voiced_f0) >= 3:
            return float(np.median(voiced_f0))
    except Exception:
        pass

    return None


def detect_vocal_register(
    audio: np.ndarray,
    sr: int,
    panns_singing: float = 0.0,
) -> tuple[str, float]:
    """
    Erkennt Vokalregister und gibt (register_label, energy_bias_db) zurück.

    Args:
        audio:         Mono oder Stereo, float32, SR=48000
        sr:            Abtastrate (48000 erwartet)
        panns_singing: PANNs-Gesangskonfidenz [0,1] — bei < 0.25 wird Fallback genutzt

    Returns:
        (register, energy_bias_db) — register ∈ {"head", "chest", "fry_whisper", "unknown"}
        energy_bias_db ∈ {-3.0, -6.0, -9.0}
    """
    # Mono extrahieren
    mono: np.ndarray
    if audio.ndim == 2:
        mono = np.mean(audio, axis=1 if audio.shape[1] <= 8 else 0).astype(np.float64)
    else:
        mono = audio.astype(np.float64)

    # Bei fehlendem Gesangs-Evidenz: Chest-Default (−6 dB)
    if panns_singing < 0.25:
        return "chest", _ENERGY_BIAS_CHEST

    # Spektrale Flachheit — erkennt Fry/Flüstern
    flatness = _spectral_flatness(mono, sr)
    if flatness >= _WHISPER_FLATNESS_THRESHOLD:
        logger.debug(
            "§2.35c VocalRegister: flatness=%.3f → Flüstern (energy_bias=%.1f dB)",
            flatness,
            _ENERGY_BIAS_FRY_WHISPER,
        )
        return "fry_whisper", _ENERGY_BIAS_FRY_WHISPER

    # F0-Schätzung für Head/Chest-Unterscheidung
    f0_med = _estimate_f0_median(mono[: min(len(mono), int(60 * sr))], sr)

    if f0_med is None:
        # F0 nicht schätzbar: Flachheit als Tiebreaker
        if flatness >= _FRY_FLATNESS_THRESHOLD:
            return "fry_whisper", _ENERGY_BIAS_FRY_WHISPER
        return "chest", _ENERGY_BIAS_CHEST

    if f0_med < _FRY_F0_HZ:
        logger.debug(
            "§2.35c VocalRegister: f0_median=%.1f Hz < 80 Hz → Fry (energy_bias=%.1f dB)",
            f0_med,
            _ENERGY_BIAS_FRY_WHISPER,
        )
        return "fry_whisper", _ENERGY_BIAS_FRY_WHISPER

    if f0_med >= _HEAD_VOICE_F0_HZ:
        logger.debug(
            "§2.35c VocalRegister: f0_median=%.1f Hz ≥ 300 Hz → Kopfstimme (energy_bias=%.1f dB)",
            f0_med,
            _ENERGY_BIAS_HEAD,
        )
        return "head", _ENERGY_BIAS_HEAD

    logger.debug(
        "§2.35c VocalRegister: f0_median=%.1f Hz → Bruststimme (energy_bias=%.1f dB)",
        f0_med,
        _ENERGY_BIAS_CHEST,
    )
    return "chest", _ENERGY_BIAS_CHEST


# ---------------------------------------------------------------------------
# Thread-safe Singleton-Wrapper
# ---------------------------------------------------------------------------


class _VocalRegisterCache:
    """Leichtgewichtiger Cache: Ergebnis gilt für max. 120 s Audio (4 MB Mono)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: dict[int, tuple[str, float]] = {}  # id(audio) → result

    def get_or_compute(self, audio: np.ndarray, sr: int, panns_singing: float) -> tuple[str, float]:
        key = id(audio)
        with self._lock:
            if key in self._cache:
                return self._cache[key]
            result = detect_vocal_register(audio, sr, panns_singing)
            self._cache[key] = result
            if len(self._cache) > 16:
                # LRU-Annäherung: ältestes Element entfernen
                oldest = next(iter(self._cache))
                del self._cache[oldest]
            return result


_cache_instance: _VocalRegisterCache | None = None
_cache_lock = threading.Lock()


def get_vocal_register_cache() -> _VocalRegisterCache:
    """Singleton-Zugriff auf den Register-Cache."""
    global _cache_instance  # pylint: disable=global-statement
    if _cache_instance is None:
        with _cache_lock:
            if _cache_instance is None:
                _cache_instance = _VocalRegisterCache()
    return _cache_instance
