"""
Adaptive Ephraim-Malah MMSE-LSA DSP-Modul für Aurik 6.0 (SOTA-Maximum)
Modular vorbereitet für spätere Erweiterung und Integration von SOTA-Algorithmen.
Implementiert eine Basisversion des MMSE-LSA-Algorithmus für Magnitude-Spektren.
"""

import logging

import numpy as np
from scipy.special import expn

logger = logging.getLogger(__name__)


class AdaptiveMMSELSA:
    def __init__(self, alpha=0.98, noise_floor=1e-8):
        self.alpha = alpha
        self.noise_floor = noise_floor

    def mmse_lsa(self, noisy_mag, noise_mag, **kwargs):
        """Berechnet das MMSE-LSA Gain für Magnitude-Spektren (Ephraim & Malah 1985)."""
        alpha = kwargs.get("alpha", self.alpha)
        noise_floor = kwargs.get("noise_floor", self.noise_floor)
        # A-priori SNR — guard against zero/negative noise
        noise_pow = noise_mag**2 + noise_floor
        noisy_pow = noisy_mag**2
        gamma = noisy_pow / noise_pow
        # Decision-directed estimator (Ephraim-Malah 1984)
        xi = alpha * noisy_pow / noise_pow + (1.0 - alpha) * np.maximum(gamma - 1.0, 0.0)
        xi = np.maximum(xi, 1e-10)  # xi strictly positive → v strictly positive
        # MMSE-LSA Gain
        v = xi * gamma / (1.0 + xi)
        v = np.maximum(v, 1e-8)  # Guard: expn(1, 0) → ∞, 0·∞ = NaN at silence
        gain = (xi / (1.0 + xi)) * np.exp(0.5 * expn(1, v))
        gain = np.nan_to_num(gain, nan=0.0, posinf=0.0, neginf=0.0)
        gain = np.clip(gain, 0.0, 1.0)  # no spectral amplification
        clean_mag = gain * noisy_mag
        return clean_mag

    def auto_optimize(self, noisy_mag, noise_mag):
        """Adaptiert alpha (a-priori-SNR-Gewichtung) anhand der Signal-Dynamik.

        Bei niedrigem SNR: kleineres alpha (schnellere Reaktion auf Rauschänderungen).
        Bei hohem SNR: höheres alpha (stabilerer Filter für musikartiges Signal).
        """
        mean_s = float(np.mean(noisy_mag**2)) + 1e-12
        mean_n = float(np.mean(noise_mag**2)) + 1e-12
        snr_db = float(10 * np.log10(mean_s / mean_n))
        # SNR 0 dB → alpha = 0.85; SNR 20 dB → alpha = 0.98
        self.alpha = float(np.clip(0.85 + 0.0065 * snr_db, 0.80, 0.99))
        logger.debug(
            "AdaptiveMMSELSA.auto_optimize: SNR=%.1f dB -> alpha=%.4f",
            snr_db,
            self.alpha,
        )
