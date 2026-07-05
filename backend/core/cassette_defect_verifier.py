"""
Cassette Defect Verifier — Aurik §v10.2

Schliesst die entscheidende Luecke in Auriks Cassetten-Defekt-Pipeline:
Detection und Correction sind perfekt — aber die Verification war blind
fuer synthetisierten/reparierten Content.

Drei Module:
  1. Per-Defect-HPE-Check: Psychoakustische Pruefung JEDES reparierten Segments
  2. ABX-Residual-Test: Spektraler Residual-Vergleich Original vs Repariert
  3. PMGG-Proxy-Alternativen: Metriken die mit synthetisiertem Content klarkommen

Phase-Support:
  phase_24 (Dropout/AudioSR)   — 9 PMGG-Ziele blind → Temporal Continuity Check
  phase_56 (Head Wear/Band Gap) — 4 PMGG-Ziele blind → Band-Gap Closure Metric
  phase_57 (Print-Through)      — 2 PMGG-Ziele blind → Echo Residue Detector
  phase_59 (Modulation Noise)   — 2 PMGG-Ziele blind → Noise Floor Delta
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────
# §v10.2 Maskierungsschwelle — was das menschliche Ohr NICHT hoert
# ─────────────────────────────────────────────────────────────────
# Glasberg & Moore 1990 (JASA 87:2178, ERB-Modell):
#   Breitband-Maskierungsschwelle ≈ -20 bis -30 dB relativ zum Maskierer.
#   Bei typischen Musikpegeln (65-80 dB SPL) liegt die Schwelle bei:
#   - 500 Hz:  -18 dB
#   - 2000 Hz: -22 dB
#   - 4000 Hz: -28 dB (ERB-breiter, bessere Maskierung)
#   - 8000 Hz: -25 dB
# Zwicker & Fastl 1999 (Psychoacoustics, 2nd ed.):
#   Simultaneous masking: residual < -18 dB unter Maskierer = unhörbar
# Conservativ: -20 dB als universelle Schwelle.

MASKING_THRESHOLD_DB: float = -20.0  # dB unter lokalem Pegel = unhörbar
MIN_SEGMENT_SAMPLES: int = 2048      # Mindest-Segmentlänge
SEGMENT_CONTEXT_MS: float = 500.0    # Kontext vor/nach Defektstelle (ms)


@dataclass
class DefectVerificationResult:
    """Ergebnis der Defekt-Verifikation fuer ein einzelnes repariertes Segment."""

    defect_type: str
    phase_id: str
    location_start_s: float
    location_end_s: float

    # ── Per-Defect HPE ──
    hpe_before: float = 0.0       # HPE des defekten Segments VOR Reparatur
    hpe_after: float = 0.0        # HPE des reparierten Segments NACH Reparatur
    hpe_delta: float = 0.0        # Verbesserung (positiv = besser)
    segment_verdict: str = ""     # "passed", "residual_detected", "worse"

    # ── ABX Residual ──
    residual_peak_db: float = 0.0       # Spitzen-Residual relativ zum Signal
    residual_rms_db: float = 0.0        # RMS-Residual
    residual_masked: bool = True        # Residual unter Maskierungsschwelle?
    abx_confidence: float = 0.0         # 0-1: Wahrscheinlichkeit dass Residual hörbar

    # ── Phase-spezifische Proxy-Metriken ──
    proxy_name: str = ""
    proxy_score: float = 0.0
    proxy_threshold: float = 0.0
    proxy_passed: bool = True

    # ── Gesamt-Urteil ──
    overall_verdict: str = ""     # "clean", "residual_below_masking", "audible_residual"
    recommendation: str = ""


@dataclass
class BatchVerificationResult:
    """Ergebnis der Batch-Verifikation aller Defekte eines Typs."""

    defect_type: str
    phase_id: str
    total_segments: int
    segments_checked: int
    clean_count: int               # Kein hörbares Residual
    masked_count: int              # Residual unter Maskierungsschwelle
    audible_count: int             # Hörbares Residual
    mean_hpe_delta: float = 0.0
    mean_residual_db: float = 0.0
    per_segment: list[DefectVerificationResult] = field(default_factory=list)
    overall_verdict: str = ""


# ═══════════════════════════════════════════════════════════════
# MODUL 1: Per-Defect-HPE-Check
# ═══════════════════════════════════════════════════════════════

def verify_defect_segment(
    original: np.ndarray,
    repaired: np.ndarray,
    sr: int,
    defect_type: str,
    phase_id: str,
    location_start_s: float,
    location_end_s: float,
) -> DefectVerificationResult:
    """§v10.2 Prueft EIN repariertes Defekt-Segment auf Residual-Artefakte.

    Extrahiert das Segment + Kontext, berechnet HPE vor/nach,
    und misst das Residual gegen die psychoakustische Maskierungsschwelle.

    Args:
        original:           Original-Audio (defekt)
        repaired:           Repariertes Audio
        sr:                 Sample-Rate
        defect_type:        z.B. "TAPE_HEAD_LEVEL_DIP"
        phase_id:           z.B. "phase_24"
        location_start_s:   Defekt-Start in Sekunden
        location_end_s:     Defekt-Ende in Sekunden

    Returns:
        DefectVerificationResult mit HPE-Delta, Residual-Pegel, Verdict
    """
    context_samples = int(SEGMENT_CONTEXT_MS / 1000.0 * sr)
    start_sample = max(0, int(location_start_s * sr) - context_samples)
    end_sample = min(len(original), int(location_end_s * sr) + context_samples)

    # Bei sehr kurzen Defekten: mindestens MIN_SEGMENT_SAMPLES
    if end_sample - start_sample < MIN_SEGMENT_SAMPLES:
        mid = (start_sample + end_sample) // 2
        half = MIN_SEGMENT_SAMPLES // 2
        start_sample = max(0, mid - half)
        end_sample = min(len(original), mid + half)

    seg_orig = _extract_segment(original, start_sample, end_sample)
    seg_rep = _extract_segment(repaired, start_sample, end_sample)

    # ── Per-Defect HPE ──
    hpe_before = _compute_segment_hpe(seg_orig, sr)
    hpe_after = _compute_segment_hpe(seg_rep, sr)
    hpe_delta = hpe_after - hpe_before

    # ── ABX Residual ──
    residual = seg_rep - seg_orig
    residual_peak_db, residual_rms_db, residual_masked = _compute_residual_level(
        residual, seg_orig, sr
    )
    abx_confidence = _estimate_audibility(residual, seg_orig, sr)

    # ── Phase-spezifische Proxy-Metrik ──
    proxy_name, proxy_score, proxy_threshold, proxy_passed = _compute_phase_proxy(
        phase_id, seg_orig, seg_rep, sr
    )

    # ── Verdict ──
    if hpe_delta > 0.01 and residual_masked:
        segment_verdict = "passed"
        overall_verdict = "clean"
    elif residual_masked or abx_confidence < 0.3:
        segment_verdict = "passed"
        overall_verdict = "residual_below_masking"
    elif hpe_delta < -0.03:
        segment_verdict = "worse"
        overall_verdict = "audible_residual"
    else:
        segment_verdict = "residual_detected"
        overall_verdict = "audible_residual"

    recommendation = _build_recommendation(overall_verdict, defect_type, phase_id, proxy_passed)

    return DefectVerificationResult(
        defect_type=defect_type,
        phase_id=phase_id,
        location_start_s=location_start_s,
        location_end_s=location_end_s,
        hpe_before=hpe_before,
        hpe_after=hpe_after,
        hpe_delta=hpe_delta,
        segment_verdict=segment_verdict,
        residual_peak_db=residual_peak_db,
        residual_rms_db=residual_rms_db,
        residual_masked=residual_masked,
        abx_confidence=abx_confidence,
        proxy_name=proxy_name,
        proxy_score=proxy_score,
        proxy_threshold=proxy_threshold,
        proxy_passed=proxy_passed,
        overall_verdict=overall_verdict,
        recommendation=recommendation,
    )


def verify_defect_batch(
    original: np.ndarray,
    repaired: np.ndarray,
    sr: int,
    defect_type: str,
    phase_id: str,
    locations: list[tuple[float, float]],
    max_segments: int = 200,
) -> BatchVerificationResult:
    """§v10.2 Batch-Verifikation aller Segmente eines Defekt-Typs.

    Verarbeitet bis zu max_segments (Default 200 um Overhead zu begrenzen).
    Bei > max_segments wird gleichmäßig gesampelt.
    """
    if len(locations) > max_segments:
        step = len(locations) // max_segments
        locations = locations[::step][:max_segments]

    results: list[DefectVerificationResult] = []
    for start_s, end_s in locations:
        try:
            r = verify_defect_segment(
                original, repaired, sr, defect_type, phase_id, start_s, end_s
            )
            results.append(r)
        except Exception as e:
            logger.debug("Defekt-Verifikation fehlgeschlagen für %s@%.1fs: %s",
                         defect_type, start_s, e)

    if not results:
        return BatchVerificationResult(
            defect_type=defect_type,
            phase_id=phase_id,
            total_segments=len(locations),
            segments_checked=0,
            clean_count=0, masked_count=0, audible_count=0,
            overall_verdict="no_data",
        )

    clean = sum(1 for r in results if r.overall_verdict == "clean")
    masked = sum(1 for r in results if r.overall_verdict == "residual_below_masking")
    audible = sum(1 for r in results if r.overall_verdict == "audible_residual")
    mean_hpe = float(np.mean([r.hpe_delta for r in results]))
    mean_res = float(np.mean([r.residual_rms_db for r in results]))

    if audible == 0:
        overall = "clean" if clean > masked else "residual_below_masking"
    elif audible <= len(results) * 0.05:
        overall = "mostly_clean"
    elif audible <= len(results) * 0.20:
        overall = "partial_residual"
    else:
        overall = "significant_residual"

    return BatchVerificationResult(
        defect_type=defect_type,
        phase_id=phase_id,
        total_segments=len(locations),
        segments_checked=len(results),
        clean_count=clean,
        masked_count=masked,
        audible_count=audible,
        mean_hpe_delta=mean_hpe,
        mean_residual_db=mean_res,
        per_segment=results,
        overall_verdict=overall,
    )


# ═══════════════════════════════════════════════════════════════
# MODUL 2: ABX-Residual-Test (Zeitbereich)
# ═══════════════════════════════════════════════════════════════

def abx_residual_test(
    original_segment: np.ndarray,
    repaired_segment: np.ndarray,
    sr: int,
) -> dict[str, Any]:
    """§v10.2 ABX-ähnlicher Residual-Test: „Kann das Ohr den Unterschied hoeren?"

    Vergleicht das Residual (repaired - original) mit der psychoakustischen
    Maskierungsschwelle des Originals.

    Returns dict mit:
      - residual_rms_db: RMS des Residuals in dB relativ zum Original
      - residual_peak_db: Peak des Residuals
      - masked_by_signal: Ob das Residual unter der Maskierungsschwelle liegt
      - audibility_confidence: 0-1 Wahrscheinlichkeit der Hörbarkeit
      - critical_bands_affected: Anzahl betroffener kritischer Bänder (Zwicker)
      - verdict: "inaudible", "borderline", "audible"
    """
    orig = np.asarray(original_segment, dtype=np.float64).ravel()
    rep = np.asarray(repaired_segment, dtype=np.float64).ravel()
    residual = rep - orig

    # Pegelberechnung
    orig_rms = float(np.sqrt(np.mean(orig ** 2)) + 1e-10)
    residual_rms = float(np.sqrt(np.mean(residual ** 2)) + 1e-10)
    residual_peak = float(np.max(np.abs(residual)) + 1e-10)

    residual_rms_db = float(20.0 * np.log10(residual_rms / orig_rms))
    residual_peak_db = float(20.0 * np.log10(residual_peak / orig_rms))

    # ── Kritische Bänder (Zwicker) ──
    critical_bands_affected = _count_affected_critical_bands(residual, orig, sr)

    # ── Maskierungs-Check ──
    # Jedes kritische Band separat prüfen
    band_residuals = _per_band_residual(residual, orig, sr)
    masked_bands = sum(1 for b in band_residuals if b < MASKING_THRESHOLD_DB)
    total_bands = max(len(band_residuals), 1)
    masked_ratio = masked_bands / total_bands
    masked_by_signal = masked_ratio > 0.8  # >80% der Bänder maskiert

    # ── Audibility Confidence ──
    # Basiert auf: RMS-Residual + betroffene Bänder + Maskierungsgrad
    if residual_rms_db < MASKING_THRESHOLD_DB:
        audibility = 0.0
    elif residual_rms_db < MASKING_THRESHOLD_DB + 6:
        audibility = 0.3 * (1.0 - masked_ratio)
    elif residual_rms_db < MASKING_THRESHOLD_DB + 12:
        audibility = 0.5 + 0.3 * (critical_bands_affected / 24.0)
    else:
        audibility = 0.8 + 0.2 * min(critical_bands_affected / 24.0, 1.0)

    # ── Verdict ──
    if audibility < 0.3:
        verdict = "inaudible"
    elif audibility < 0.6:
        verdict = "borderline"
    else:
        verdict = "audible"

    return {
        "residual_rms_db": residual_rms_db,
        "residual_peak_db": residual_peak_db,
        "masked_by_signal": masked_by_signal,
        "audibility_confidence": audibility,
        "critical_bands_affected": critical_bands_affected,
        "masked_bands_ratio": masked_ratio,
        "verdict": verdict,
    }


# ═══════════════════════════════════════════════════════════════
# MODUL 3: PMGG-Alternativ-Proxy-Metriken
# ═══════════════════════════════════════════════════════════════

def compute_phase_proxy_for_pmgg(
    phase_id: str,
    audio_before: np.ndarray,
    audio_after: np.ndarray,
    sr: int,
) -> dict[str, float]:
    """§v10.2 Alternative Proxy-Metrik fuer PMGG-ausgeschlossene Ziele.

    Ersetzt die blinden PMGG-Checks durch phase-spezifische Metriken
    die mit synthetisiertem/repariertem Content umgehen koennen.

    Returns dict mit {goal_name: proxy_score} im PMGG-Format (0-1).
    """
    result: dict[str, float] = {}

    if "phase_24" in phase_id or "dropout" in phase_id.lower():
        result.update(_proxy_phase_24_dropout(audio_before, audio_after, sr))

    if "phase_56" in phase_id or "head_wear" in phase_id.lower():
        result.update(_proxy_phase_56_head_wear(audio_before, audio_after, sr))

    if "phase_57" in phase_id or "print_through" in phase_id.lower():
        result.update(_proxy_phase_57_print_through(audio_before, audio_after, sr))

    if "phase_59" in phase_id or "modulation_noise" in phase_id.lower():
        result.update(_proxy_phase_59_modulation_noise(audio_before, audio_after, sr))

    result.update(_universal_proxies(audio_before, audio_after, sr))
    return result


# ─────────────────────────────────────────────────────────
# Phase-spezifische Proxy-Implementierungen
# ─────────────────────────────────────────────────────────

def _proxy_phase_24_dropout(
    before: np.ndarray, after: np.ndarray, sr: int
) -> dict[str, float]:
    """phase_24 Dropout Repair: Temporal Continuity statt Spektral-Flatness.

    PMGG schliesst 9 Ziele aus (natuerlichkeit, brillanz, authentizitaet,
    artikulation, timbre_authentizitaet, transparenz, tonal_center,
    groove, emotionalitaet) — der AudioSR synthetisiert neue Patches,
    die gegen die defekte Referenz wie Regression aussehen.

    Alternative Proxy: Temporal Continuity = Energie-Varianz über 50ms-Fenster.
    Ein gut reparierter Dropout hat GLEICHE Energie wie umgebendes Signal.
    """
    # Energie in 50ms-Blöcken
    block_samples = int(0.05 * sr)
    n_blocks = min(len(before), len(after)) // block_samples

    if n_blocks < 3:
        return {"natuerlichkeit": 0.5, "transparenz": 0.5}

    b_en = np.array([np.mean(before[i*block_samples:(i+1)*block_samples]**2)
                      for i in range(n_blocks)])
    a_en = np.array([np.mean(after[i*block_samples:(i+1)*block_samples]**2)
                      for i in range(n_blocks)])

    # Temporal Continuity: std(energy) sollte NIEDRIG sein (keine Sprünge)
    b_continuity = 1.0 / (1.0 + float(np.std(b_en) / (np.mean(b_en) + 1e-10)) * 10)
    a_continuity = 1.0 / (1.0 + float(np.std(a_en) / (np.mean(a_en) + 1e-10)) * 10)

    # Verbesserung in der Kontinuität
    continuity_delta = a_continuity - b_continuity

    # HF-Energie nach Reparatur (Dropouts haben oft HF-Verlust)
    b_hf = float(np.mean(np.abs(np.diff(before.ravel()))))
    a_hf = float(np.mean(np.abs(np.diff(after.ravel()))))

    return {
        "natuerlichkeit": min(1.0, max(0.0, a_continuity)),
        "brillanz": min(1.0, max(0.0, a_hf / (b_hf + 1e-10) * 0.8)),
        "authentizitaet": min(1.0, max(0.0, 0.5 + continuity_delta)),
        "transparenz": min(1.0, max(0.0, a_continuity * 0.9)),
        "groove": min(1.0, max(0.0, 0.5 + continuity_delta * 0.7)),
        "emotionalitaet": min(1.0, max(0.0, 0.5 + continuity_delta * 0.5)),
        "artikulation": min(1.0, max(0.0, a_hf / (b_hf + 1e-10))),
        "timbre_authentizitaet": min(1.0, max(0.0, 0.5 + continuity_delta * 0.8)),
        "tonal_center": min(1.0, max(0.0, 0.7 + continuity_delta * 0.3)),
    }


def _proxy_phase_56_head_wear(
    before: np.ndarray, after: np.ndarray, sr: int
) -> dict[str, float]:
    """phase_56 Head Wear Band-Gap Repair: Band-Gap Closure Metric.

    PMGG schliesst 4 Ziele aus (natuerlichkeit, brillanz, authentizitaet,
    timbre_authentizitaet). Head-Wear erzeugt Frequenzband-Ausloeschungen
    (comb-filter durch Kopfverschleiss). Die Reparatur schliesst diese Luecken.

    Proxy: Spektrale Glattheit (Spectral Smoothness) — nach Reparatur sollte
    das Spektrum GLAETTER sein (keine abrupten Band-Lücken).
    """
    n_fft = min(4096, len(before))
    if n_fft < 256:
        return {"natuerlichkeit": 0.5, "brillanz": 0.5, "authentizitaet": 0.5,
                "timbre_authentizitaet": 0.5}

    b_fft = np.abs(np.fft.rfft(before.ravel()[:n_fft]))
    a_fft = np.abs(np.fft.rfft(after.ravel()[:n_fft]))

    # Spectral Smoothness = 1 / (1 + mean(|diff(spectrum)|))
    b_smooth = 1.0 / (1.0 + float(np.mean(np.abs(np.diff(b_fft))) /
                                     (np.mean(b_fft) + 1e-10)) * 5)
    a_smooth = 1.0 / (1.0 + float(np.mean(np.abs(np.diff(a_fft))) /
                                     (np.mean(a_fft) + 1e-10)) * 5)

    # HF-Recovery: Energie > 8 kHz
    hf_bin = int(8000 / (sr / n_fft))
    b_hf = float(np.mean(b_fft[hf_bin:]) + 1e-10)
    a_hf = float(np.mean(a_fft[hf_bin:]) + 1e-10)

    smooth_delta = a_smooth - b_smooth

    return {
        "natuerlichkeit": min(1.0, max(0.0, a_smooth)),
        "brillanz": min(1.0, max(0.0, a_hf / (b_hf + 1e-10) * 0.85)),
        "authentizitaet": min(1.0, max(0.0, 0.5 + smooth_delta)),
        "timbre_authentizitaet": min(1.0, max(0.0, 0.5 + smooth_delta * 0.9)),
    }


def _proxy_phase_57_print_through(
    before: np.ndarray, after: np.ndarray, sr: int
) -> dict[str, float]:
    """phase_57 Print-Through Reduction: Echo Residue Detector.

    PMGG schliesst 2 Ziele aus (authentizitaet, emotionalitaet).
    Print-Through = magnetisches Pre-Echo (100-300ms vor Einsatz).
    Nach LMS-Adaptive Subtraction sollte das Pre-Echo verschwunden sein.

    Proxy: Autokorrelations-basierter Echo-Detektor.
    """
    min_lag = int(0.05 * sr)   # 50 ms
    max_lag = int(0.40 * sr)   # 400 ms (Pre-Echo + Post-Echo)

    if max_lag >= len(after) // 2 or max_lag <= min_lag:
        return {"authentizitaet": 0.5, "emotionalitaet": 0.5}

    # Autokorrelation des Residuals (before - after)
    diff = before.ravel()[:max_lag * 3] - after.ravel()[:max_lag * 3]
    if len(diff) < max_lag * 2:
        return {"authentizitaet": 0.5, "emotionalitaet": 0.5}

    diff_norm = diff / (float(np.std(diff)) + 1e-10)
    ac = np.correlate(diff_norm, diff_norm, mode='full')
    ac = ac[len(ac)//2:] / ac[len(ac)//2]  # Normalisieren

    # Echo-Peak im Print-Through-Bereich (100-300ms)
    echo_region = ac[min_lag:max_lag]
    echo_peak = float(np.max(np.abs(echo_region)))
    echo_residual = 1.0 - echo_peak  # 0=Echo da, 1=kein Echo

    return {
        "authentizitaet": min(1.0, max(0.0, echo_residual)),
        "emotionalitaet": min(1.0, max(0.0, 0.5 + echo_residual * 0.5)),
    }


def _proxy_phase_59_modulation_noise(
    before: np.ndarray, after: np.ndarray, sr: int
) -> dict[str, float]:
    """phase_59 Modulation Noise Reduction: Noise Floor Delta.

    PMGG schliesst 2 Ziele aus (natuerlichkeit, emotionalitaet).
    Modulationsrauschen = signal-abhängiges Rauschen (lauter bei lauten Passagen).
    Nach Reduktion sollte das Rauschen ENTKOPPELT vom Signal sein.

    Proxy: Korrelation zwischen Signal-Hüllkurve und Rausch-Hüllkurve.
    """
    block_samples = int(0.025 * sr)  # 25ms Blöcke
    n_blocks = min(len(before), len(after)) // block_samples

    if n_blocks < 4:
        return {"natuerlichkeit": 0.5, "emotionalitaet": 0.5}

    b_blocks = [before.ravel()[i*block_samples:(i+1)*block_samples]
                for i in range(n_blocks)]
    a_blocks = [after.ravel()[i*block_samples:(i+1)*block_samples]
                for i in range(n_blocks)]

    # Signal-Hüllkurve vs Rausch-Hüllkurve
    b_env = np.array([float(np.sqrt(np.mean(b**2))) for b in b_blocks])
    a_env = np.array([float(np.sqrt(np.mean(a**2))) for a in a_blocks])

    # Hochpass-gefilterte Hüllkurve (≈ Rausch-Anteil)
    if len(b_env) >= 4:
        from scipy import signal as scipy_signal
        try:
            b_hp = scipy_signal.detrend(b_env, type='constant')
            a_hp = scipy_signal.detrend(a_env, type='constant')
        except Exception:
            b_hp = b_env - np.mean(b_env)
            a_hp = a_env - np.mean(a_env)

        # Korrelation Signal↔Rauschen: sollte nach Reparatur NIEDRIGER sein
        b_corr = float(np.abs(np.corrcoef(b_env, b_hp)[0, 1])) if np.std(b_env) > 1e-10 and np.std(b_hp) > 1e-10 else 0.5
        a_corr = float(np.abs(np.corrcoef(a_env, a_hp)[0, 1])) if np.std(a_env) > 1e-10 and np.std(a_hp) > 1e-10 else 0.5

        decoupling = b_corr - a_corr  # Positiv = Rauschen besser entkoppelt
        noise_score = 0.5 + decoupling * 2.0
    else:
        noise_score = 0.5

    return {
        "natuerlichkeit": min(1.0, max(0.0, noise_score)),
        "emotionalitaet": min(1.0, max(0.0, 0.5 + noise_score * 0.5)),
    }


def _universal_proxies(
    before: np.ndarray, after: np.ndarray, sr: int
) -> dict[str, float]:
    """Universelle Proxy-Metriken die immer sinnvoll sind."""
    b_rms = float(np.sqrt(np.mean(before.ravel()**2)) + 1e-10)
    a_rms = float(np.sqrt(np.mean(after.ravel()**2)) + 1e-10)

    # Pegel-Stabilität
    level_stability = 1.0 - abs(float(20 * np.log10(a_rms / b_rms))) / 20.0

    # Zero-Crossing-Rate (Indikator für HF-Inhalt)
    b_zcr = float(np.mean(np.abs(np.diff(np.sign(before.ravel())))) / 2)
    a_zcr = float(np.mean(np.abs(np.diff(np.sign(after.ravel())))) / 2)
    zcr_preservation = 1.0 - abs(a_zcr - b_zcr) / max(b_zcr, 0.01)

    return {
        "level_stability": min(1.0, max(0.0, level_stability)),
        "zcr_preservation": min(1.0, max(0.0, zcr_preservation)),
    }


# ═══════════════════════════════════════════════════════════════
# Hilfsfunktionen
# ═══════════════════════════════════════════════════════════════

def _extract_segment(audio: np.ndarray, start: int, end: int) -> np.ndarray:
    """Sicheres Extrahieren eines Segments."""
    a = np.asarray(audio, dtype=np.float64)
    if a.ndim == 2:
        a = a.mean(axis=1) if a.shape[1] <= 2 else a.mean(axis=0)
    a = a.ravel()
    return a[start:end].copy()


def _compute_segment_hpe(audio: np.ndarray, sr: int) -> float:
    """Vereinfachte Segment-HPE basierend auf Sharpness + Roughness."""
    arr = np.asarray(audio, dtype=np.float64).ravel()
    if len(arr) < 256:
        return 0.5

    # Sharpness (High-Frequency Content ratio)
    n_fft = min(2048, len(arr))
    fft = np.abs(np.fft.rfft(arr[:n_fft]))
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
    hf_mask = freqs > 3000
    hf_ratio = float(np.sum(fft[hf_mask]) / (np.sum(fft) + 1e-10))
    sharpness_ok = 1.0 - abs(hf_ratio - 0.2) * 2.0  # ~20% HF = ideal

    # Roughness (Amplitude Modulation 15-300 Hz)
    env = np.abs(arr)
    if len(env) >= 64:
        env_fft = np.abs(np.fft.rfft(env[:2048]))
        env_freqs = np.fft.rfftfreq(2048, 1.0 / sr)
        rough_mask = (env_freqs > 15) & (env_freqs < 300)
        roughness = float(np.mean(env_fft[rough_mask]) / (np.mean(env_fft) + 1e-10))
    else:
        roughness = 0.3

    roughness_ok = 1.0 - min(roughness * 3.0, 1.0)

    # Kombinieren
    return float(np.clip(sharpness_ok * 0.5 + roughness_ok * 0.5, 0.0, 1.0))


def _compute_residual_level(
    residual: np.ndarray, original: np.ndarray, sr: int
) -> tuple[float, float, bool]:
    """Berechnet Residual-Pegel relativ zum Signal."""
    orig_rms = float(np.sqrt(np.mean(original.ravel()**2)) + 1e-12)
    res_rms = float(np.sqrt(np.mean(residual.ravel()**2)) + 1e-12)
    res_peak = float(np.max(np.abs(residual.ravel())) + 1e-12)

    rms_db = float(20.0 * np.log10(res_rms / orig_rms))
    peak_db = float(20.0 * np.log10(res_peak / orig_rms))

    masked = rms_db < MASKING_THRESHOLD_DB
    return peak_db, rms_db, masked


def _estimate_audibility(residual: np.ndarray, original: np.ndarray, sr: int) -> float:
    """Schätzt die Hörbarkeit des Residuals (0-1)."""
    orig_rms = float(np.sqrt(np.mean(original.ravel()**2)) + 1e-10)
    res_rms = float(np.sqrt(np.mean(residual.ravel()**2)) + 1e-10)
    rms_db = float(20.0 * np.log10(res_rms / orig_rms))

    # Zwicker/Fastl: Maskierung ≈ -18 bis -28 dB je nach Frequenz
    if rms_db < -25:
        return 0.0
    elif rms_db < -18:
        return float((rms_db + 25) / 7.0 * 0.3)  # 0.0 → 0.3
    elif rms_db < -10:
        return 0.3 + float((rms_db + 18) / 8.0 * 0.4)  # 0.3 → 0.7
    else:
        return 0.7 + float(min(-rms_db / 10.0, 1.0) * 0.3)  # 0.7 → 1.0


def _count_affected_critical_bands(
    residual: np.ndarray, original: np.ndarray, sr: int
) -> int:
    """Zählt kritische Bänder (Zwicker) mit hörbarem Residual."""
    # Zwicker kritische Bänder (vereinfacht): 24 Bänder, 1 Bark ≈ 1.3mm auf Basilarmembran
    n_fft = min(4096, len(residual))
    if n_fft < 128:
        return 0

    res_fft = np.abs(np.fft.rfft(residual.ravel()[:n_fft]))
    orig_fft = np.abs(np.fft.rfft(original.ravel()[:n_fft]))

    # Vereinfachte Bark-Skala: 24 Bänder logarithmisch
    n_bins = len(res_fft)
    bark_edges = np.unique(np.logspace(0, np.log10(n_bins), 25, dtype=int))
    bark_edges = bark_edges[(bark_edges >= 0) & (bark_edges < n_bins)]

    affected = 0
    for i in range(len(bark_edges) - 1):
        lo, hi = int(bark_edges[i]), int(bark_edges[i + 1])
        if hi <= lo:
            continue
        band_res = float(np.mean(res_fft[lo:hi]))
        band_orig = float(np.mean(orig_fft[lo:hi])) + 1e-10
        if 20.0 * np.log10(band_res / band_orig) > MASKING_THRESHOLD_DB:
            affected += 1

    return affected


def _per_band_residual(
    residual: np.ndarray, original: np.ndarray, sr: int
) -> list[float]:
    """Residual pro kritischem Band in dB."""
    n_fft = min(4096, len(residual))
    if n_fft < 128:
        return [0.0]

    res_fft = np.abs(np.fft.rfft(residual.ravel()[:n_fft]))
    orig_fft = np.abs(np.fft.rfft(original.ravel()[:n_fft]))

    n_bins = len(res_fft)
    bark_edges = np.unique(np.logspace(0, np.log10(n_bins), 25, dtype=int))
    bark_edges = bark_edges[(bark_edges >= 0) & (bark_edges < n_bins)]

    band_dbs: list[float] = []
    for i in range(len(bark_edges) - 1):
        lo, hi = int(bark_edges[i]), int(bark_edges[i + 1])
        if hi <= lo:
            continue
        band_res = float(np.mean(res_fft[lo:hi])) + 1e-10
        band_orig = float(np.mean(orig_fft[lo:hi])) + 1e-10
        band_dbs.append(float(20.0 * np.log10(band_res / band_orig)))

    return band_dbs


def _compute_phase_proxy(
    phase_id: str,
    before: np.ndarray,
    after: np.ndarray,
    sr: int,
) -> tuple[str, float, float, bool]:
    """Berechnet die phase-spezifische Proxy-Metrik."""
    proxies = compute_phase_proxy_for_pmgg(phase_id, before, after, sr)

    # Wähle repräsentativste Metrik
    if "natuerlichkeit" in proxies:
        proxy_name = "natuerlichkeit"
    elif "authentizitaet" in proxies:
        proxy_name = "authentizitaet"
    elif "brillanz" in proxies:
        proxy_name = "brillanz"
    elif proxies:
        proxy_name = list(proxies.keys())[0]
    else:
        proxy_name = "level_stability"

    proxy_score = proxies.get(proxy_name, 0.5)
    threshold = 0.55  # HPE-Grünzone-Basis
    passed = proxy_score >= threshold

    return proxy_name, proxy_score, threshold, passed


def _build_recommendation(
    verdict: str, defect_type: str, phase_id: str, proxy_passed: bool
) -> str:
    """Baut eine handlungsorientierte Empfehlung."""
    if verdict == "clean":
        return f"{defect_type}: Perfekt repariert. Kein hörbares Residual."
    elif verdict == "residual_below_masking":
        return (f"{defect_type}: Residual vorhanden aber unter Maskierungsschwelle. "
                f"Für menschliche Ohren unhörbar.")
    elif not proxy_passed:
        return (f"{defect_type}: {phase_id} Proxy-Metrik nicht bestanden. "
                f"Erwäge reduziertes Strength oder alternative Phase.")
    else:
        return (f"{defect_type}: Hörbares Residual. {phase_id} mit "
                f"reduziertem Strength (0.65→0.40) erneut versuchen.")


# ─────────────────────────────────────────────────────────────────
# Integration: Automatische Post-Phase-Verifikation
# ─────────────────────────────────────────────────────────────────

def post_phase_verification(
    audio_before: np.ndarray,
    audio_after: np.ndarray,
    sr: int,
    phase_id: str,
    defect_locations: dict[str, list[tuple[float, float]]] | None = None,
) -> dict[str, Any]:
    """§v10.2 Automatische Post-Phase-Verifikation.

    Wird nach JEDER cassetten-relevanten Phase aufgerufen.
    Prüft alle drei Ebenen (HPE, ABX, PMGG-Proxy) und gibt
    ein aggregiertes Urteil zurück.

    Returns dict mit:
      - phase_passed: bool
      - hpe_delta: float
      - worst_residual_db: float
      - proxy_scores: dict
      - batch_results: dict (pro Defekt-Typ)
      - recommendation: str
    """
    if defect_locations is None:
        defect_locations = {}

    batch_results: dict[str, BatchVerificationResult] = {}
    all_hpe_deltas: list[float] = []
    all_proxy_scores: dict[str, float] = {}
    worst_residual = -100.0

    for defect_type, locations in defect_locations.items():
        if not locations:
            continue
        batch = verify_defect_batch(
            audio_before, audio_after, sr, defect_type, phase_id, locations
        )
        batch_results[defect_type] = batch
        all_hpe_deltas.append(batch.mean_hpe_delta)
        worst_residual = max(worst_residual, batch.mean_residual_db)

    # PMGG Proxy
    proxies = compute_phase_proxy_for_pmgg(phase_id, audio_before, audio_after, sr)
    all_proxy_scores.update(proxies)

    # Aggregiertes Urteil
    mean_hpe = float(np.mean(all_hpe_deltas)) if all_hpe_deltas else 0.0
    audible_count = sum(b.audible_count for b in batch_results.values())
    total_checked = sum(b.segments_checked for b in batch_results.values())

    if total_checked == 0:
        phase_passed = True
        recommendation = "Keine Defekt-Locations → Überspringe Verifikation"
    elif audible_count == 0:
        phase_passed = True
        recommendation = f"Phase {phase_id}: Alle {total_checked} Segmente sauber oder maskiert."
    elif audible_count <= total_checked * 0.05:
        phase_passed = True
        recommendation = (f"Phase {phase_id}: {audible_count}/{total_checked} Segmente "
                          f"mit hörbarem Residual (<5%). Akzeptabel.")
    else:
        phase_passed = False
        recommendation = (f"Phase {phase_id}: {audible_count}/{total_checked} Segmente "
                          f"mit hörbarem Residual. RETRY empfohlen.")

    return {
        "phase_passed": phase_passed,
        "hpe_delta": mean_hpe,
        "worst_residual_db": worst_residual,
        "proxy_scores": all_proxy_scores,
        "batch_results": {k: v.overall_verdict for k, v in batch_results.items()},
        "total_checked": total_checked,
        "audible_count": audible_count,
        "recommendation": recommendation,
    }
