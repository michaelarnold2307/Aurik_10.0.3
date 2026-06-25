"""§2.44 HPG Reference-Memory Bootstrap-Skript.

Seedet das HPG Reference-Memory (~/.aurik/hpg_reference_memory.json) mit
Embeddings aus den Golden-Samples in golden_samples/references/, damit das
5-Stufen-Fallback-System von _get_reference_vector() bereits beim ersten
echten Lauf funktionstüchtig ist (statt immer None zurückzugeben).

Aufruf:
    python scripts/bootstrap_hpg_reference_memory.py

Ausführung vor dem ersten Produktivlauf oder nach dem Löschen der Referenz-Memory-Datei.
Bereits vorhandene Einträge werden via EMA (α=0.15) geblended — kein Datenverlust.
"""

from __future__ import annotations

import logging
import pathlib
import sys

# Workspace-Root in sys.path aufnehmen
_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("bootstrap_hpg_ref_memory")

# Genre-Erkennung aus Dateiname (Präfix vor erstem Unterstrich)
_GENRE_FROM_PREFIX: dict[str, str] = {
    "vocal": "vocal",
    "classical": "classical",
    "jazz": "jazz",
    "instrumental": "instrumental",
    "pop": "pop",
    "rock": "rock",
    "blues": "blues",
    "folk": "folk",
}

# Alle Golden-Reference-Samples liegen als saubare digitale Referenzen vor
_DEFAULT_MATERIAL = "digital"
_DEFAULT_ERA_BIN = "post-1980"

# Bootstrap-HPI-Werte: Referenzdaten gelten als qualitativ hochwertig
_BOOTSTRAP_HPI = 0.92
_BOOTSTRAP_AF = 0.97
_BOOTSTRAP_P1P2 = True


def _detect_genre(filename: str) -> str:
    stem = pathlib.Path(filename).stem.lower()
    prefix = stem.split("_")[0]
    return _GENRE_FROM_PREFIX.get(prefix, "general")


def run_bootstrap(references_dir: pathlib.Path) -> int:
    """Verarbeitet alle Audiodateien in references_dir und seedet die Reference-Memory.

    Gibt die Anzahl erfolgreich geseedeter Einträge zurück.
    """
    try:
        from backend.core.holistic_perceptual_gate import get_holistic_gate
    except ImportError as exc:
        logger.error("HPG-Import fehlgeschlagen — PYTHONPATH korrekt? %s", exc)
        return 0

    try:
        from backend.file_import import load_audio_file
    except ImportError:
        try:
            import soundfile as sf

            def load_audio_file(path: str) -> tuple:  # type: ignore[misc]
                audio, sr = sf.read(path, always_2d=False)
                import numpy as np

                return np.asarray(audio, dtype=np.float32), int(sr)
        except ImportError:
            logger.error("Weder backend.file_import noch soundfile verfügbar.")
            return 0

    gate = get_holistic_gate()
    seeded = 0

    audio_files = sorted(references_dir.glob("*.wav")) + sorted(references_dir.glob("*.flac"))
    if not audio_files:
        logger.warning("Keine Audiodateien in %s gefunden.", references_dir)
        return 0

    for audio_path in audio_files:
        genre = _detect_genre(audio_path.name)
        try:
            _result = load_audio_file(str(audio_path))
            if not isinstance(_result, dict) or _result.get("error"):
                logger.warning("  ✗ %s: load_audio_file Fehler: %s", audio_path.name, (_result or {}).get("error"))
                continue
            import numpy as np

            audio = np.asarray(_result["audio"], dtype=np.float32)
            sr = int(_result["sr"])
            gate.update_reference_memory(
                restored=audio,
                sr=sr,
                hpi=_BOOTSTRAP_HPI,
                artifact_freedom=_BOOTSTRAP_AF,
                p1_p2_passed=_BOOTSTRAP_P1P2,
                genre=genre,
                material=_DEFAULT_MATERIAL,
                era_bin=_DEFAULT_ERA_BIN,
            )
            logger.info(
                "  ✓ %s → genre=%s material=%s era=%s", audio_path.name, genre, _DEFAULT_MATERIAL, _DEFAULT_ERA_BIN
            )
            seeded += 1
        except Exception as exc:
            logger.warning("  ✗ %s: %s", audio_path.name, exc)

    logger.info("Bootstrap abgeschlossen: %d Einträge geseedet.", seeded)
    return seeded


def main() -> None:
    references_dir = _REPO_ROOT / "golden_samples" / "references"
    if not references_dir.exists():
        logger.error("Golden-Samples-Verzeichnis nicht gefunden: %s", references_dir)
        sys.exit(1)

    logger.info("§2.44 HPG Reference-Memory Bootstrap")
    logger.info("Quellverzeichnis: %s", references_dir)

    count = run_bootstrap(references_dir)
    if count == 0:
        logger.error("Kein einziger Eintrag geseedet — Bootstrap fehlgeschlagen.")
        sys.exit(1)

    logger.info("Fertig. %d Embeddings persistiert in ~/.aurik/hpg_reference_memory.json", count)


if __name__ == "__main__":
    main()
