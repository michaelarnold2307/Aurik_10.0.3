from typing import Any

import numpy as np


class GenderDetector:
    def __init__(self, use_auth_token: Any = None) -> None:
        del use_auth_token
        from plugins.resemblyzer_plugin import get_resemblyzer_plugin  # pylint: disable=import-outside-toplevel

        self._plugin = get_resemblyzer_plugin()

    def detect_gender(self, audio_file) -> str:
        """
        Gibt das dominante Geschlecht im Audioclip zurück: 'male', 'female' oder 'unknown'.
        Verwendet Resemblyzer für robuste, offlinefähige Stimmtyperkennung.
        """
        try:
            if not self._plugin.available:
                return "unknown"
            import soundfile as _sf  # pylint: disable=import-outside-toplevel

            wav, _sr = _sf.read(audio_file, dtype="float32", always_2d=False)
            emb = self._plugin.embed(wav, _sr)
            if emb is None:
                return "unknown"
            # Pitch-basierte Grobklassifikation auf 16 kHz-Mono
            import librosa as _librosa  # pylint: disable=import-outside-toplevel

            mono_16k = _librosa.resample(
                wav if wav.ndim == 1 else wav.mean(axis=-1),
                orig_sr=_sr,
                target_sr=16000,
            )
            f0 = self._estimate_pitch(mono_16k)
            if f0 < 170:
                return "male"
            elif f0 < 300:
                return "female"
            else:
                return "unknown"
        except Exception:
            return "unknown"

    def _estimate_pitch(self, wav, sr=16000) -> float:
        # Einfache Pitch-Schätzung (Median der Autokorrelationsmethode)
        from scipy.signal import correlate

        wav = wav.astype(np.float32)
        corr = correlate(wav, wav)
        corr = corr[len(corr) // 2 :]
        d = np.diff(corr)
        start = np.where(d > 0)[0][0]
        peak = np.argmax(corr[start:]) + start
        if peak == 0:
            return 0
        return sr / peak
