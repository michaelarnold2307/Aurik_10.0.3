"""ML model readiness check — centralised pre-flight for all Aurik phases.

Each phase that uses an ML model MUST call `check_ml_model_ready()` before
invoking inference.  If the model cannot be loaded or is unavailable, a
WARNING is logged and the phase can fall back gracefully.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Registry of model checkers — each entry is (label, check_fn) where
# check_fn returns True if the model is ready, False otherwise.
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


# ── Pre-registered checks for phase-level ML models ──────────────────

def _register_phase_checks() -> None:
    """Register readiness checks for the ML models used directly in phases."""

    # DeepFilterNet v3
    try:
        from plugins.deepfilternet_v3_ii_plugin import get_dfnet_plugin as _get_dfnet

        def _dfnet_ready() -> bool:
            p = _get_dfnet()
            return p is not None and getattr(p, "_model_loaded", False)

        register_ml_check("DeepFilterNetV3", _dfnet_ready)
    except ImportError:
        register_ml_check("DeepFilterNetV3", lambda: False)

    # BANQUET (Vinyl Crackle Removal)
    def _banquet_ready() -> bool:
        try:
            from backend.core.phases.phase_09_crackle_removal import (
                _get_banquet_onnx_session,
            )

            return _get_banquet_onnx_session() is not None
        except ImportError:
            return False

    register_ml_check("BANQUET", _banquet_ready)

    # AudioSR
    try:
        from plugins.audiosr_plugin import _get_ml_model as _get_audiosr

        def _audiosr_ready() -> bool:
            return _get_audiosr() is not None

        register_ml_check("AudioSR", _audiosr_ready)
    except ImportError:
        register_ml_check("AudioSR", lambda: False)

    # BS-RoFormer
    try:
        from plugins.bs_roformer_plugin import get_bs_roformer_plugin as _get_bsr

        def _bsr_ready() -> bool:
            p = _get_bsr()
            return p is not None and getattr(p, "_model_loaded", False)

        register_ml_check("BS-RoFormer", _bsr_ready)
    except ImportError:
        register_ml_check("BS-RoFormer", lambda: False)

    # MIIPHER
    try:
        from plugins.miipher_plugin import get_miipher_plugin as _get_miipher

        def _miipher_ready() -> bool:
            p = _get_miipher()
            return p is not None and getattr(p, "_model_loaded", False)

        register_ml_check("MIIPHER", _miipher_ready)
    except ImportError:
        register_ml_check("MIIPHER", lambda: False)

    # Silero VAD
    try:
        from plugins.silero_vad_plugin import get_silero_vad_plugin as _get_vad

        def _vad_ready() -> bool:
            p = _get_vad()
            return p is not None and getattr(p, "_model_loaded", False)

        register_ml_check("SileroVAD", _vad_ready)
    except ImportError:
        register_ml_check("SileroVAD", lambda: False)

    # GACELA
    try:
        from plugins.gacela_plugin import get_gacela_plugin as _get_gacela

        def _gacela_ready() -> bool:
            p = _get_gacela()
            return p is not None and getattr(p, "_model_loaded", False)

        register_ml_check("GACELA", _gacela_ready)
    except ImportError:
        register_ml_check("GACELA", lambda: False)

    # AudioLDM2
    try:
        from plugins.audioldm2_plugin import get_audioldm2_plugin as _get_aldm2

        def _aldm2_ready() -> bool:
            p = _get_aldm2()
            return p is not None and getattr(p, "_model_loaded", False)

        register_ml_check("AudioLDM2", _aldm2_ready)
    except ImportError:
        register_ml_check("AudioLDM2", lambda: False)

    # BasicPitch
    try:
        from plugins.basicpitch_plugin import get_basicpitch_plugin as _get_bp

        def _bp_ready() -> bool:
            p = _get_bp()
            return p is not None and getattr(p, "_model_loaded", False)

        register_ml_check("BasicPitch", _bp_ready)
    except ImportError:
        register_ml_check("BasicPitch", lambda: False)

    # Whisper (via LGE)
    def _whisper_ready() -> bool:
        try:
            from backend.core.lyrics_guided_enhancement import (
                get_lyrics_guided_enhancement,
            )

            lge = get_lyrics_guided_enhancement()
            return lge.is_loaded() if hasattr(lge, "is_loaded") else False
        except ImportError:
            return False

    register_ml_check("Whisper", _whisper_ready)


# Register at import time
_register_phase_checks()
