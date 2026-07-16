import numpy as np

try:
    import librosa

    _HAS_LIBROSA = True
except ImportError:
    librosa = None  # type: ignore[assignment]
    _HAS_LIBROSA = False


def resample_to_48k(audio: np.ndarray, orig_sr: int) -> tuple[np.ndarray, int]:
    """
    Resample ein beliebiges Audiosignal auf 48 kHz (Mono oder Stereo).

    Verwendet librosa (konsistent mit dem Rest der Aurik-Codebase).
    Fallback: scipy.signal.resample.
    """
    target_sr = 48000
    if orig_sr == target_sr:
        return audio, orig_sr

    if _HAS_LIBROSA:
        resampled = librosa.resample(
            np.asarray(audio, dtype=np.float32),
            orig_sr=orig_sr,
            target_sr=target_sr,
        )
        return resampled, target_sr

    # Fallback: scipy (letzter Ausweg)
    from scipy.signal import resample as _scipy_resample

    if audio.ndim == 1:
        n_out = int(len(audio) * target_sr / orig_sr)
        return np.asarray(_scipy_resample(audio, n_out), dtype=np.float32), target_sr
    n_out = int(audio.shape[-1] * target_sr / orig_sr)
    return np.asarray(_scipy_resample(audio, n_out, axis=-1), dtype=np.float32), target_sr
