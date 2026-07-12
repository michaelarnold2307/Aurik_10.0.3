"""ML model readiness check — centralised pre-flight for all Aurik phases.

Every phase that uses an ML model MUST call `check_ml_model_ready()` before
invoking inference.  If the model cannot be loaded or is unavailable, a
WARNING is logged and the phase can fall back gracefully.

Model registry is populated at import time via lazy probing — each registered
check function probes the actual plugin/module and returns True only if the
model is fully loaded and ready for inference.
"""

from __future__ import annotations

import logging
from typing import Callable

logger = logging.getLogger(__name__)

# Registry: model_id -> check_fn() -> bool
_MODEL_CHECKS: dict[str, Callable[[], bool]] = {}


def register_ml_check(model_id: str, check_fn: Callable[[], bool]) -> None:
    """Register a model readiness check function under a stable id."""
    _MODEL_CHECKS[model_id] = check_fn


def check_ml_model_ready(model_id: str, phase_name: str = "") -> bool:
    """Return True if the named ML model loaded successfully.

    If the check fails (model unavailable / not loaded), a WARNING is
    emitted with the model name and the calling phase.

    Args:
        model_id:  Stable id registered via register_ml_check().
        phase_name: Optional phase identifier for the log message.

    Returns:
        True if the model is ready, False otherwise.
    """
    check_fn = _MODEL_CHECKS.get(model_id)
    if check_fn is None:
        # Unregistered model — assume OK but warn about missing registration
        logger.debug("ML model '%s' has no registered readiness check", model_id)
        return True

    try:
        ready = check_fn()
    except Exception as exc:
        logger.warning(
            "ML-Modell '%s' konnte nicht geladen werden (%s)%s",
            model_id,
            exc,
            f" — Phase {phase_name}" if phase_name else "",
        )
        return False

    if not ready:
        logger.warning(
            "ML-Modell '%s' ist nicht verfügbar (nicht geladen / Budget erschöpft)%s",
            model_id,
            f" — Phase {phase_name}" if phase_name else "",
        )
        return False

    return True


# ── Generic plugin probe helpers ──────────────────────────────────────

def _probe_plugin(module_path: str, getter_name: str, attr: str | None = None) -> Callable[[], bool]:
    """Return a check function that probes a plugin's getter + optional attr."""
    def _check() -> bool:
        try:
            mod = __import__(module_path, fromlist=[getter_name])
            getter = getattr(mod, getter_name, None)
            if getter is None:
                return False
            instance = getter()
            if instance is None:
                return False
            if attr is not None:
                if isinstance(attr, str):
                    # Check attribute
                    val = getattr(instance, attr, None)
                    if callable(val):
                        return bool(val())
                    return bool(val)
            return True
        except ImportError:
            return False
        except Exception:
            return False

    return _check


def _probe_function(module_path: str, fn_name: str) -> Callable[[], bool]:
    """Return a check function that probes a module-level function."""
    def _check() -> bool:
        try:
            mod = __import__(module_path, fromlist=[fn_name])
            fn = getattr(mod, fn_name, None)
            if fn is None:
                return False
            result = fn()
            return result is not None and result is not False
        except ImportError:
            return False
        except Exception:
            return False

    return _check


# ── Register all known ML models ──────────────────────────────────────

def _register_all() -> None:
    """Probe and register all ML models used in Aurik phases."""

    # --- Denoising / Restoration ---
    register_ml_check(
        "DeepFilterNetV3",
        _probe_plugin("plugins.deepfilternet_v3_ii_plugin", "get_deepfilternet_plugin", "_model_loaded"),
    )
    register_ml_check(
        "BANQUET",
        _probe_function("backend.core.phases.phase_09_crackle_removal", "_get_banquet_onnx_session"),
    )

    # --- Bandwidth Extension / Inpainting ---
    register_ml_check(
        "AudioSR",
        _probe_function("plugins.audiosr_plugin", "_get_ml_model"),
    )
    register_ml_check(
        "GACELA",
        _probe_plugin("plugins.gacela_plugin", "get_gacela_plugin", "_model_loaded"),
    )
    register_ml_check(
        "AudioLDM2",
        _probe_plugin("plugins.audioldm2_plugin", "get_audioldm2_plugin", "_model_loaded"),
    )

    # --- Vocal / Stem ---
    register_ml_check(
        "BS-RoFormer",
        _probe_plugin("plugins.bs_roformer_plugin", "get_bs_roformer", "_model_loaded"),
    )
    register_ml_check(
        "MIIPHER",
        _probe_plugin("plugins.miipher_plugin", "get_miipher_plugin", "_model_loaded"),
    )
    register_ml_check(
        "Demucs",
        _probe_plugin("plugins.demucs_plugin", "get_demucs_plugin", "_model_loaded"),
    )

    # --- Voice Activity / Speech ---
    register_ml_check(
        "SileroVAD",
        _probe_plugin("plugins.silero_vad_plugin", "get_silero_vad_plugin", "_model_loaded"),
    )
    register_ml_check(
        "Whisper",
        _probe_plugin("backend.core.lyrics_guided_enhancement", "get_lyrics_guided_enhancement", "is_loaded"),
    )
    register_ml_check(
        "Wav2Vec2",
        _probe_plugin("backend.core.lyrics_guided_enhancement", "get_lyrics_guided_enhancement", "is_loaded"),
    )

    # --- Pitch / Frequency ---
    register_ml_check(
        "FCPE",
        _probe_plugin("plugins.fcpe_plugin", "get_fcpe_plugin", "_model_loaded"),
    )
    register_ml_check(
        "CREPE",
        _probe_plugin("plugins.crepe_plugin", "get_crepe_plugin", "_model_loaded"),
    )
    register_ml_check(
        "BasicPitch",
        _probe_plugin("plugins.basicpitch_plugin", "get_basicpitch_plugin", "_model_loaded"),
    )

    # --- Audio Tagging / Classification ---
    register_ml_check(
        "PANNs",
        _probe_plugin("plugins.panns_plugin", "get_panns_plugin", "_model_loaded"),
    )
    register_ml_check(
        "LAION-CLAP",
        _probe_plugin("plugins.laion_clap_plugin", "get_laion_clap", "_model_loaded"),
    )
    register_ml_check(
        "BEATs",
        _probe_plugin("plugins.beats_plugin", "get_beats_plugin", "_model_loaded"),
    )

    # --- Music Understanding ---
    register_ml_check(
        "MERT",
        _probe_plugin("plugins.mert_plugin", "get_mert_plugin", "_model_loaded"),
    )

    # --- Dereverberation ---
    register_ml_check(
        "WPE-Dereverb",
        _probe_plugin("plugins.wpe_plugin", "get_wpe_plugin", "_initialized"),
    )

    # --- Perceptual Quality ---
    def _ast_ready() -> bool:
        try:
            from backend.core.musical_goals.perceptual_validator import get_perceptual_validator

            pv = get_perceptual_validator()
            return pv is not None and getattr(pv, "_model_loaded", False)
        except ImportError:
            return False

    register_ml_check("AST-Perceptual-ONNX", _ast_ready)


_register_all()
