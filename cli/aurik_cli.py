import logging
import os
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

# Ensure repository root is on sys.path when CLI is executed as a script.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from backend.api.bridge import get_aurik_denker_instance, get_load_audio_fn, run_pre_analysis

_TARGET_SR = 48_000
_VALID_MODES = {"Restoration", "Studio 2026"}


def _load_audio(path: str) -> tuple[np.ndarray, int]:
    """Load audio file via canonical bridge import cascade."""
    try:
        load_audio_file = get_load_audio_fn()
        loaded = load_audio_file(path, target_sr=None, mono=False, do_carrier_analysis=False)
        if not isinstance(loaded, dict) or loaded.get("audio") is None or loaded.get("sr") is None:
            raise RuntimeError(str((loaded or {}).get("error") or "Unbekannter Ladefehler"))
        audio = np.asarray(loaded["audio"], dtype=np.float32)
        if audio.ndim == 1:
            audio = audio[:, np.newaxis]
        elif audio.ndim == 2 and audio.shape[0] < audio.shape[1]:
            audio = audio.T
        return np.clip(np.nan_to_num(audio, nan=0.0, posinf=0.0, neginf=0.0), -1.0, 1.0), int(loaded["sr"])
    except Exception as exc:
        raise RuntimeError(f"Audio konnte nicht geladen werden: {exc}") from exc


def _normalize_mode(mode: str) -> str:
    raw = str(mode or "Restoration").strip().lower().replace("_", "").replace(" ", "")
    if raw in {"restoration", "quality"}:
        return "Restoration"
    if raw in {"studio2026", "studio"}:
        return "Studio 2026"
    return "Restoration"


def _rms_dbfs(audio: np.ndarray) -> float:
    arr = np.asarray(audio, dtype=np.float32)
    if arr.ndim == 2:
        # Normalize to (N, ch): channels-first (ch, N) → transpose
        if arr.shape[0] <= 2 and arr.shape[1] > 2:
            arr = arr.T
        arr = arr.mean(axis=1)  # downmix to mono

    # §2.45a-I: Gated RMS (frame-based, silence ignored).
    # Global RMS penalizes successful denoise/dereverb because removed noise floor
    # lowers average energy although musical loudness is preserved.
    arr64 = arr.astype(np.float64, copy=False)
    if arr64.size == 0:
        return -120.0

    frame = 2048
    n = int(arr64.shape[0])
    n_frames = max(1, n // frame)
    gated_chunks: list[np.ndarray] = []

    for i in range(n_frames):
        s = i * frame
        e = min(s + frame, n)
        ch = arr64[s:e]
        if ch.size == 0:
            continue
        ch_rms = float(np.sqrt(np.mean(ch * ch) + 1e-12))
        ch_db = 20.0 * np.log10(max(ch_rms, 1e-12))
        if ch_db > -50.0:
            gated_chunks.append(ch)

    # Tail frame
    tail_s = n_frames * frame
    if tail_s < n:
        ch = arr64[tail_s:]
        if ch.size > 0:
            ch_rms = float(np.sqrt(np.mean(ch * ch) + 1e-12))
            ch_db = 20.0 * np.log10(max(ch_rms, 1e-12))
            if ch_db > -50.0:
                gated_chunks.append(ch)

    if gated_chunks:
        gated = np.concatenate(gated_chunks)
        rms = float(np.sqrt(np.mean(gated * gated) + 1e-12))
    else:
        # Fallback for near-silent clips
        rms = float(np.sqrt(np.mean(arr64 * arr64) + 1e-12))

    return float(20.0 * np.log10(max(rms, 1e-12)))


def _resample_to_48k(audio: np.ndarray, sr: int) -> np.ndarray:
    """Resample to 48 kHz with frontend-parity path (soxr HQ, fallback scipy)."""
    if sr == _TARGET_SR:
        return audio
    try:
        import soxr as _soxr_rs

        # Frontend parity: soxr HQ for deterministic quality alignment.
        if audio.ndim == 2:
            out = _soxr_rs.resample(audio, sr, _TARGET_SR, quality="HQ")
        else:
            out = _soxr_rs.resample(audio, sr, _TARGET_SR, quality="HQ")
        return np.asarray(out, dtype=np.float32)
    except Exception:
        try:
            import scipy.signal as _sig

            int(round(audio.shape[0] * _TARGET_SR / sr))
            return _sig.resample_poly(audio, _TARGET_SR, sr, axis=0).astype(np.float32)
        except Exception as exc2:
            raise RuntimeError(
                "Interne 48-kHz-Normierung fehlgeschlagen. Ursache: Resampling konnte nicht ausgefuehrt werden. "
                "Loesung: soxr/scipy im Bundle sicherstellen oder Eingabedatei vorab auf 48 kHz konvertieren."
            ) from exc2


def process_audio(input_path: str, output_path: str, verbose: bool = True, mode: str = "Restoration") -> object:
    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING, format="%(levelname)s: %(message)s")
    logger = logging.getLogger("aurik_cli")

    mode = _normalize_mode(mode)
    if mode not in _VALID_MODES:
        logger.warning("Unbekannter Modus '%s' — verwende 'Restoration'.", mode)
        mode = "Restoration"

    if not os.path.exists(input_path):
        logger.error("Input-Datei nicht gefunden: %s", input_path)
        sys.exit(2)

    # ── 1. Audio laden ────────────────────────────────────────────────────────
    try:
        audio_raw, sr_raw = _load_audio(input_path)
    except RuntimeError as exc:
        logger.error("Fehler beim Laden der Datei: %s", exc)
        sys.exit(3)

    file_mb = os.path.getsize(input_path) / 1024 / 1024
    if verbose:
        logger.info("Datei: %s  (%.2f MB, %d Hz, %d Kanäle)", input_path, file_mb, sr_raw, audio_raw.shape[1])

    # ── 2. Auf 48 kHz resamplen (Aurik-kanonische SR) ─────────────────────────
    try:
        audio_48k = _resample_to_48k(audio_raw, sr_raw)
    except RuntimeError as exc:
        logger.error("Fehler bei der SR-Normierung: %s", exc)
        sys.exit(6)

    try:
        pre = run_pre_analysis(
            audio_native=audio_raw,
            sr_native=sr_raw,
            audio_48k=audio_48k,
            file_path=input_path,
            store_in_bridge_cache=True,
        )
    except Exception as exc:
        logger.error("Fehler in der Voranalyse: %s", exc)
        sys.exit(10)

    if verbose:
        logger.info("🔧 Starte AurikDenker — Modus: %s", mode)

    # ── 3. Kanonischer Einstiegspunkt: AurikDenker.denke() (Spec §2.2) ────────
    try:
        denker = get_aurik_denker_instance()
        # Quality-first policy: prefer full-quality execution over RT budget cuts.
        result = denker.denke(
            audio_48k,
            sr=_TARGET_SR,
            mode=mode,
            no_rt_limit=True,
            input_path=input_path,
            pre_analysis_result=pre,
        )
    except Exception as exc:
        logger.error("Fehler in der Restaurierungspipeline: %s", exc)
        sys.exit(4)

    if verbose:
        logger.info(
            "✅ Verarbeitung abgeschlossen  ·  Material: %s  ·  Qualität: %.3f  ·  RT-Faktor: %.2f×",
            result.material,
            result.quality_estimate,
            result.rt_factor,
        )
        if result.warnings:
            for w in result.warnings:
                logger.warning("⚠ %s", w)
        if result.processing_note:
            logger.info("ℹ %s", result.processing_note)
        logger.info(
            "🎯 Musical Goals: %d/14 bestanden  ·  Phasen: %d",
            result.goals_passed,
            len(result.phases_executed),
        )

    # ── 4. Export-Quality-Gate (§8.1 + §0c RELEASE_MUST) ───────────────────────
    # §0c: Bei fehlgeschlagenem End-Gate MUSS Aurik das bestmögliche sichere Ergebnis
    # exportieren. Hardstop ohne Ausgabedatei ist normativ unzulässig.
    # Status bleibt transparent (degraded). Kein stiller Abbruch.
    _export_degraded = False
    _export_degraded_reasons: list[str] = []

    # §2.54 Material-adaptive quality_estimate threshold: Physikalische Qualitätsdecke je
    # Material-Klasse — multi-generationale mp3_low-Ketten können strukturell keine CD-Qualität
    # erreichen. Hardcoded 0.55 erzeugt für legitime Restaurierungen immer 'degraded'-Export.
    _mat_str = str(getattr(result, "material", "") or "").lower()
    _mat_str = _mat_str.split(".")[-1]  # Enum-Value (.mp3_low → mp3_low)
    _QE_THRESHOLD: dict[str, float] = {
        "mp3_low": 0.33,
        "mp3_high": 0.40,
        "aac": 0.38,
        "streaming": 0.38,
        "shellac": 0.35,
        "wax_cylinder": 0.32,
        "wire_recording": 0.34,
        "cassette": 0.38,
        "tape": 0.42,
        "reel_tape": 0.42,
        "vinyl": 0.45,
        "lacquer_disc": 0.42,
        "minidisc": 0.45,
        "cd_digital": 0.55,
        "dat": 0.55,
        "lossless": 0.55,
    }
    _qe_threshold = _QE_THRESHOLD.get(_mat_str, 0.45)
    _qe = getattr(result, "quality_estimate", None)
    if _qe is not None and _qe < _qe_threshold:
        _export_degraded = True
        _export_degraded_reasons.append(f"quality_estimate={_qe:.3f}<{_qe_threshold:.2f} (§8.1)")
        logger.warning(
            "§0c: quality_estimate=%.3f < %.2f (%s-Schwelle) — Export mit Status 'degraded'.",
            _qe,
            _qe_threshold,
            _mat_str or "default",
        )

    # P1/P2 Musical Goals — normativ erstrebenswert, kein Hard-Export-Stop (§0c)
    _P1_P2_THRESHOLDS = {
        "natuerlichkeit": 0.90,
        "authentizitaet": 0.88,
        "tonal_center": 0.95,
        "timbre_authentizitaet": 0.87,
        "artikulation": 0.85,
    }
    _goals = getattr(result, "musical_goals_scores", None) or {}
    _failed_goals = [f"{g}={_goals[g]:.3f}<{t}" for g, t in _P1_P2_THRESHOLDS.items() if g in _goals and _goals[g] < t]
    if _failed_goals:
        _export_degraded = True
        _export_degraded_reasons.append(f"P1/P2-Goals: {', '.join(_failed_goals)}")
        logger.warning(
            "§0c: P1/P2-Goals verfehlt (%s) — Export mit Status 'degraded'.",
            ", ".join(_failed_goals),
        )

    # ── 5. Ergebnis speichern ─────────────────────────────────────────────────
    # Aurik-internes Format: (channels, samples) = (2, N). soundfile und
    # _rms_dbfs erwarten (samples, channels) = (N, 2). Hier normalisieren.
    restored = result.audio
    if isinstance(restored, np.ndarray):
        if restored.ndim == 2 and restored.shape[0] < restored.shape[1]:
            # (ch, N) → (N, ch) — Transport-Bump-Bug: falsche axis in mean/sf.write
            restored = np.ascontiguousarray(restored.T)
        restored = np.asarray(restored, dtype=np.float32)
    _in_db = _rms_dbfs(audio_48k)
    _out_db = _rms_dbfs(restored)
    _drop_db = _in_db - _out_db
    # §2.54 Material-adaptive Pegelabfall-Schwelle: Subtraktive Phasen (Denoise, Dereverb)
    # entfernen auf verlustbehafteten Trägern legitim mehr Rauschen als auf linearem Material.
    # Hardcoded 2.5 dB führt bei mp3_low/shellac immer zum False-Positive 'degraded'.
    _PEGEL_THRESHOLD: dict[str, float] = {
        "mp3_low": 5.0,
        "mp3_high": 4.0,
        "aac": 4.0,
        "streaming": 4.0,
        "shellac": 5.5,
        "wax_cylinder": 6.0,
        "wire_recording": 6.0,
        "cassette": 4.5,
        "tape": 4.5,
        "reel_tape": 4.0,
        "vinyl": 3.5,
        "lacquer_disc": 4.0,
        "cd_digital": 2.5,
        "dat": 2.5,
        "lossless": 2.5,
        "minidisc": 3.5,
    }
    _pegel_threshold = _PEGEL_THRESHOLD.get(_mat_str, 4.0)
    if _drop_db > _pegel_threshold:
        _export_degraded = True
        _export_degraded_reasons.append(f"Pegelabfall={_drop_db:.2f}dB>{_pegel_threshold:.1f}dB")
        logger.warning(
            "§0c: Pegelabfall %.2f dB > %.1f dB (%s-Schwelle) — Export mit Status 'degraded'.",
            _drop_db,
            _pegel_threshold,
            _mat_str or "default",
        )

    try:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        sf.write(output_path, restored, _TARGET_SR, subtype="PCM_24")
    except Exception as exc:
        logger.error("Fehler beim Speichern der Audiodatei: %s", exc)
        sys.exit(5)

    if verbose:
        logger.info("📈 Pegel-Drift: in=%.2f dBFS out=%.2f dBFS delta=%.2f dB", _in_db, _out_db, -_drop_db)
        if _export_degraded:
            logger.warning(
                "🟡 Export abgeschlossen (DEGRADED): %s — Grund: %s",
                output_path,
                " | ".join(_export_degraded_reasons),
            )
            logger.info("💾 Gespeichert (degraded): %s", output_path)
        else:
            logger.info("💾 Gespeichert: %s", output_path)

    return result


def print_usage():
    print("\nVerwendung: aurik_cli [--input PATH] [--output PATH] [--mode MODUS] [-q] [-h]")
    print("\nOptionen:")
    print("  --input, --input_audio PATH  Eingabe-Audiodatei")
    print("  --output, --output_audio PATH Ausgabe-Audiodatei")
    print("  --mode MODUS                 Restaurierungsmodus: 'Restoration' (Standard) oder 'Studio 2026'")
    print("  -q, --quiet                  Keine Fortschritts-Ausgaben")
    print("  -h, --help                   Diese Hilfe anzeigen")
    print()


def main():
    args = sys.argv[1:]
    verbose = True
    if "-q" in args or "--quiet" in args:
        verbose = False
        args = [a for a in args if a not in ["-q", "--quiet"]]

    if "-h" in args or "--help" in args:
        print_usage()
        sys.exit(0)

    input_file = None
    output_file = None
    mode = "Restoration"
    skip_next = False
    for i, arg in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        if arg in ("--input_audio", "--input"):
            if i + 1 < len(args):
                input_file = args[i + 1]
                skip_next = True
        elif "=" in arg and arg.split("=", 1)[0] in ("--input_audio", "--input"):
            input_file = arg.split("=", 1)[1]
        elif arg in ("--output_audio", "--output"):
            if i + 1 < len(args):
                output_file = args[i + 1]
                skip_next = True
        elif "=" in arg and arg.split("=", 1)[0] in ("--output_audio", "--output"):
            output_file = arg.split("=", 1)[1]
        elif arg == "--mode":
            if i + 1 < len(args):
                mode = args[i + 1]
                skip_next = True
        elif "=" in arg and arg.split("=", 1)[0] == "--mode":
            mode = arg.split("=", 1)[1]

    # Positional Fallback: nur Nicht-Flag-Argumente verwenden
    positional = [a for a in args if not a.startswith("-")]
    if input_file is None and len(positional) >= 1:
        input_file = positional[0]
    if output_file is None and len(positional) >= 2:
        output_file = positional[1]

    if not input_file or not output_file:
        print("❌ Fehler: Zu wenig oder ungültige Argumente\n")
        print_usage()
        sys.exit(1)

    process_audio(input_file, output_file, verbose=verbose, mode=mode)


if __name__ == "__main__":
    main()
