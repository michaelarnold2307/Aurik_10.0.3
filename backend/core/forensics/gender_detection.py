from typing import Any

import numpy as np

try:
    from resemblyzer import VoiceEncoder, preprocess_wav  # type: ignore[import]

    _RESEMBLYZER_AVAILABLE = True
except ImportError:
    VoiceEncoder = None  # type: ignore[assignment]
    preprocess_wav = None  # type: ignore[assignment]
    _RESEMBLYZER_AVAILABLE = False


class GenderDetector:
    def __init__(self, use_auth_token: Any = None) -> None:
        del use_auth_token
        self.encoder = VoiceEncoder() if _RESEMBLYZER_AVAILABLE and VoiceEncoder is not None else None

    def detect_gender(self, audio_file) -> str:
        """
        Gibt das dominante Geschlecht im Audioclip zurück: 'male', 'female' oder 'unknown'.
        Verwendet Resemblyzer für robuste, offlinefähige Stimmtyperkennung.
        """
        try:
            if not _RESEMBLYZER_AVAILABLE or preprocess_wav is None or self.encoder is None:
                return "unknown"
            wav = preprocess_wav(audio_file)
            self.encoder.embed_utterance(wav)
            # Placeholder: Nutze die mittlere Fundamental-Frequenz als grobe Gender-Schätzung
            # Für professionelle Nutzung sollte ein SVM/KNN auf Embeddings trainiert werden
            f0 = self._estimate_pitch(wav)
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
