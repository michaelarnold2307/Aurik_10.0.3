"""
Aliasing Detector
=================

Detects fold-back aliasing artifacts near Nyquist.
"""

import numpy as np
from scipy.signal import find_peaks, welch

from backend.defect_detection.base import DefectDetector, DefectInstance, DefectType


class AliasingDetector(DefectDetector):
    """Detects spectral fold-back artifacts caused by anti-aliasing failures."""

    def __init__(self):
        super().__init__(name="aliasing_detector", defect_type=DefectType.ALIASING)

    def detect(self, audio: np.ndarray, sr: int, tolerance: float = 0.15, **kwargs) -> list[DefectInstance]:
        """Detect aliasing using upper-band energy and narrow-peak structure."""
        if audio.ndim == 2:
            audio = audio[:, 0]

        if len(audio) < 2048:
            return []

        freqs, psd = welch(audio, sr, nperseg=min(8192, len(audio) // 4))
        nyquist = float(sr) / 2.0

        # Mid-band reference where musical energy is expected.
        mid_mask = (freqs >= 2000.0) & (freqs <= min(8000.0, nyquist * 0.7))
        # Aliasing artifacts typically accumulate close to Nyquist.
        upper_mask = (freqs >= nyquist * 0.45) & (freqs <= nyquist * 0.99)

        if not np.any(mid_mask) or not np.any(upper_mask):
            return []

        mid_energy = float(np.mean(psd[mid_mask]) + 1e-20)
        upper_psd = psd[upper_mask]
        upper_freqs = freqs[upper_mask]
        upper_energy = float(np.mean(upper_psd) + 1e-20)
        total_energy = float(np.mean(psd) + 1e-20)

        # Guard against false positives on spectrally sparse clean material.
        # A low sinusoid can make the 2–8 kHz reference band nearly silent, which
        # would otherwise inflate the ratio despite negligible energy near Nyquist.
        upper_energy_fraction = upper_energy / total_energy
        if upper_energy_fraction < 1e-3:
            return []

        # Core indicator: unexpected HF energy close to Nyquist.
        foldback_ratio = upper_energy / mid_energy

        # Secondary indicator: narrow spectral lines in upper band.
        upper_db = 10.0 * np.log10(upper_psd + 1e-20)
        noise_floor_db = float(np.median(upper_db))
        peaks, props = find_peaks(upper_db, prominence=4.0)
        if len(peaks) > 0:
            prominences = props.get("prominences", np.array([], dtype=np.float64))
            mean_prominence = float(np.mean(prominences)) if len(prominences) > 0 else 0.0
        else:
            mean_prominence = 0.0

        # Severity blend: energy-dominant plus peak-structure support.
        sev_energy = float(np.clip((foldback_ratio - 0.06) / 0.24, 0.0, 1.0))
        sev_peaks = float(np.clip((mean_prominence - 4.0) / 10.0, 0.0, 1.0))
        severity = float(np.clip(0.75 * sev_energy + 0.25 * sev_peaks, 0.0, 1.0))

        if severity < tolerance:
            return []

        confidence = float(np.clip(0.55 + 0.30 * sev_energy + 0.15 * sev_peaks, 0.45, 0.9))
        metrics = {
            "foldback_ratio": foldback_ratio,
            "upper_energy_fraction": upper_energy_fraction,
            "upper_band_hz_low": float(upper_freqs[0]),
            "upper_band_hz_high": float(upper_freqs[-1]),
            "upper_noise_floor_db": noise_floor_db,
            "upper_peak_count": float(len(peaks)),
            "upper_mean_prominence_db": mean_prominence,
        }
        description = f"Aliasing suspected near Nyquist: foldback_ratio={foldback_ratio:.3f}, peak_count={len(peaks)}"
        return [
            self._create_instance(
                severity=severity,
                confidence=confidence,
                metrics=metrics,
                description=description,
            )
        ]
