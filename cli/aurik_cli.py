import logging
import os
import sys

import numpy as np
import soundfile as sf

# Canonical entrypoint: AurikDenker (spec §2.2 — no bypass via AdaptiveProcessingPipeline)
from denker.aurik_denker import get_aurik_denker

_TARGET_SR = 48_000
_VALID_MODES = {"Restoration", "Studio 2026"}


def _load_audio(path: str) -> tuple[np.ndarray, int]:
    """Load audio file using soundfile with pedalboard fallback."""
    try:
        audio, sr = sf.read(path, always_2d=True, dtype="float32")
        return audio, sr
    except Exception:
        pass
    try:
        import pedalboard.io as _pb_io  # type: ignore[import]

        with _pb_io.AudioFile(path) as f:
            audio = f.read(f.frames).T.astype(np.float32)
            sr = int(f.samplerate)
        return audio, sr
    except Exception:
        pass
    try:
        import librosa  # type: ignore[import]

        audio, sr = librosa.load(path, sr=None, mono=False)
        if audio.ndim == 1:
            audio = audio[np.newaxis, :]
        return audio.T.astype(np.float32), int(sr)
    except Exception as exc:
        raise RuntimeError(f"Audio konnte nicht geladen werden: {exc}") from exc


def _resample_to_48k(audio: np.ndarray, sr: int) -> np.ndarray:
    """Resample to 48 kHz if necessary (Lanczos via scipy)."""
    if sr == _TARGET_SR:
        return audio
    try:
        import scipy.signal as _sig

        int(round(audio.shape[0] * _TARGET_SR / sr))
        return _sig.resample_poly(audio, _TARGET_SR, sr, axis=0).astype(np.float32)
    except Exception as exc:
        raise RuntimeError(
            "Interne 48-kHz-Normierung fehlgeschlagen. Ursache: Resampling konnte nicht ausgefuehrt werden. "
            "Loesung: scipy/librosa im Bundle sicherstellen oder Eingabedatei vorab auf 48 kHz konvertieren."
        ) from exc


def process_audio(input_path: str, output_path: str, verbose: bool = True, mode: str = "Restoration") -> object:
    logging.basicConfig(level=logging.INFO if verbose else logging.WARNING, format="%(levelname)s: %(message)s")
    logger = logging.getLogger("aurik_cli")

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

    if verbose:
        logger.info("🔧 Starte AurikDenker — Modus: %s", mode)

    # ── 3. Kanonischer Einstiegspunkt: AurikDenker.denke() (Spec §2.2) ────────
    try:
        denker = get_aurik_denker()
        # Quality-first policy: prefer full-quality execution over RT budget cuts.
        result = denker.denke(audio_48k, sr=_TARGET_SR, mode=mode, no_rt_limit=True, input_path=input_path)
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

    # ── 4. Ergebnis speichern ─────────────────────────────────────────────────
    restored = result.audio
    try:
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        sf.write(output_path, restored, _TARGET_SR, subtype="PCM_24")
    except Exception as exc:
        logger.error("Fehler beim Speichern der Audiodatei: %s", exc)
        sys.exit(5)

    if verbose:
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
