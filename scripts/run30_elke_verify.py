#!/usr/bin/env python3
"""Run30 — Optimierter Full-Pipeline-Run mit Pre-Analysis-Handover + no_rt_limit (v9.11.82)

Verbesserungen gegenüber run28/29:
- Pre-Analysis EINMALIG berechnet, direkt an AurikDenker weitergereicht (§2.47a)
- no_rt_limit=True → keine Qualitätsdegradation durch Runtime-Timeouts
- Vollständige Metriken-Ausgabe (alle 15 Musical Goals, timbral_detail, Experience)
"""
# pylint: disable=wrong-import-position

import logging
import os
import sys
import time

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
)
logger = logging.getLogger("run30")

import soundfile as sf

from backend.core.pre_analysis import run_pre_analysis
from backend.file_import import load_audio_file
from denker.aurik_denker import get_aurik_denker

SONG = "test_audio/Elke Best - Du wolltest nur ein Abenteuer, aber ich suchte einen Freund.mp3"
OUT = "output_audio/Elke_Best_restoration_v9_11_82_run30.wav"
TARGET_SR = 48000

# --- Load (native SR, kein Carrier-Analyse-Block im Import-Thread) ---
res = load_audio_file(SONG, do_carrier_analysis=False)
if res is None or "audio" not in res or "sr" not in res:
    logger.error("Audio-Import fehlgeschlagen oder unvollständiges Ergebnis für: %s", SONG)
    sys.exit(1)

audio_native = res["audio"]
sr_native = res["sr"]
logger.info("Loaded: shape=%s sr=%d", audio_native.shape, sr_native)

# --- Resample auf 48 kHz ---
if sr_native != TARGET_SR:
    try:
        import resampy

        axis = 0 if audio_native.ndim == 2 else -1
        audio_48k = resampy.resample(audio_native, sr_native, TARGET_SR, axis=axis)
        logger.info("Resampled to %d Hz, new shape=%s", TARGET_SR, audio_48k.shape)
    except Exception as e:
        logger.error("Resampling failed: %s", e)
        sys.exit(1)
else:
    audio_48k = audio_native.copy()

# --- Pre-Analysis EINMALIG (§2.47a: kein Doppel-Detect) ---
logger.info("Starte Pre-Analysis (Medium, Era, Genre, Defects, Restorability)…")
t_pre = time.time()
pre_result = run_pre_analysis(
    audio_native=audio_native,
    sr_native=sr_native,
    audio_48k=audio_48k,
    file_path=os.path.abspath(SONG),
    store_in_bridge_cache=True,
)
logger.info(
    "Pre-Analysis fertig in %.1fs | medium=%s era=%s restorability=%s",
    time.time() - t_pre,
    getattr(getattr(pre_result, "medium", None), "primary_material", "?"),
    getattr(getattr(pre_result, "era", None), "decade", "?"),
    getattr(getattr(pre_result, "restorability", None), "restorability_score", "?"),
)
if pre_result.errors:
    logger.warning("Pre-Analysis-Fehler: %s", pre_result.errors)

# --- AurikDenker: Restoration mit Pre-Analysis-Handover + no_rt_limit ---
denker = get_aurik_denker()
t0 = time.time()
result = denker.denke(
    audio_48k,
    TARGET_SR,
    mode="restoration",
    input_path=SONG,
    pre_analysis_result=pre_result,
    no_rt_limit=True,  # kein Runtime-Limit → maximale Qualität
)
elapsed = time.time() - t0

# --- Metriken ---
hpg = result.metadata.get("holistic_perceptual_gate", {})
mg = result.metadata.get("musical_goals", {})
exp = result.metadata.get("joy_runtime_index", {})
sc = result.metadata.get("song_calibration", {})
cca = result.metadata.get("carrier_chain_recovery_ratio", 0.0)

logger.info("=" * 60)
logger.info("DONE %.1fs (%.2f× RT)", elapsed, elapsed / max(1.0, len(audio_48k) / TARGET_SR))
logger.info(
    "HPI=%.4f  timbral=%.4f  mert=%.4f  artifact=%.4f",
    hpg.get("hpi", 0),
    hpg.get("timbral_fidelity", 0),
    hpg.get("mert_similarity", 0),
    hpg.get("artifact_freedom", 0),
)
logger.info(
    "carrier_chain_recovery_ratio=%.3f  VERSA-MOS=%s",
    cca,
    result.metadata.get("versa_mos", "?"),
)

# timbral detail
det = hpg.get("detail", {})
logger.info(
    "timbral_detail: input=%.3f ref=%.3f w_in=%.2f w_ref=%.2f",
    det.get("timbral_input", 0),
    det.get("timbral_ref", 0),
    det.get("input_weight", 0),
    det.get("ref_weight", 0),
)

# Musical Goals: alle 15
passed = mg.get("passed_count", mg.get("passed", "?"))
total = mg.get("total", 15)
violations = mg.get("violations", [])
logger.info("Musical Goals: %s/%s passed | violations=%s", passed, total, violations)

scores = mg.get("scores", {})
if scores:
    for g, v in sorted(scores.items()):
        marker = "✓" if g not in violations else "✗"
        logger.info("  %s %-30s = %.4f", marker, g, v)

# Experience / Joy
logger.info(
    "Joy=%.3f  Fatigue=%.3f  Frisson=%.3f",
    exp.get("joy_index", 0),
    exp.get("fatigue_index", 0),
    exp.get("components", {}).get("frisson_index", 0),
)

# SongCal-Cluster
logger.info("SongCal cluster=%s policy=%s", sc.get("cluster_key", "?"), sc.get("cluster_policy", "?"))

# OQS / MUSHRA
oqs = result.metadata.get("oqs", {})
logger.info(
    "OQS=%.1f  MUSHRA=%.1f  Anchor=%.1f",
    oqs.get("oqs", 0),
    oqs.get("mushra", 0),
    oqs.get("anchor", 0),
)

# --- Export ---
out_audio = result.audio
if out_audio.ndim == 2 and out_audio.shape[0] <= 2:
    out_audio = out_audio.T
sf.write(OUT, out_audio, TARGET_SR, subtype="PCM_24")
logger.info("Exported: %s", OUT)
logger.info("=" * 60)
