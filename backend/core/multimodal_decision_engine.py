"""
backend/core/multimodal_decision_engine.py — Multimodal decision engine
=======================================================================

Combines cover-image analysis, NLP prompt parsing, and audio metadata to
produce a restoration chain and parameter preset.
"""

from __future__ import annotations

import os
from typing import Any


class MultimodalDecisionEngine:
    """Combines image, text and audio signals to produce a processing chain.

    This is a rule-based stub that provides deterministic output for
    test cases. Image analysis is path-based heuristic; prompt parsing
    is keyword-based.
    """

    # ----------------------------------------------------------------
    # Genre/era knowledge base (path heuristics)
    # ----------------------------------------------------------------
    _COVER_RULES: dict[str, dict[str, Any]] = {
        "vinyl_rock": {
            "genre": "Rock",
            "era": "1970s",
            "chain": ["brilliance_enhancer", "denoiser"],
        },
        "jazz_album": {
            "genre": "Jazz",
            "era": "1950s",
            "chain": ["warmth_enhancer", "noise_reducer"],
        },
    }

    _PROMPT_RULES: list[tuple] = [
        (["brillanz", "bright", "brilliance"], "brilliance_enhancer"),
        (["rauschen", "noise", "denoising"], "denoiser"),
        (["wärmer", "warm", "warmth"], "warmth_enhancer"),
        (["bass", "tiefe"], "bass_enhancer"),
    ]

    def decide(
        self,
        image_path: str,
        prompt: str,
        audio_meta: dict[str, Any],
    ) -> dict[str, Any]:
        """Return a processing chain and metadata dict.

        Args:
            image_path: Path to cover image (or placeholder).
            prompt:     User text prompt (German/English).
            audio_meta: Dict with at least ``"material"`` key.

        Returns:
            Dict with keys ``"chain"`` (list) and ``"meta"`` (dict).
        """
        chain: list[str] = []
        meta: dict[str, Any] = {"genre": "Unknown", "era": "Unknown"}

        # Cover-based rules
        basename = os.path.splitext(os.path.basename(image_path))[0].lower()
        for key, rule in self._COVER_RULES.items():
            if key in basename:
                chain.extend(rule.get("chain", []))
                meta["genre"] = rule.get("genre", "Unknown")
                meta["era"] = rule.get("era", "Unknown")
                break

        # Prompt-based rules
        prompt_lower = (prompt or "").lower()
        for keywords, processor in self._PROMPT_RULES:
            if any(kw in prompt_lower for kw in keywords) and processor not in chain:
                chain.append(processor)

        # Prompt-specific parameter overrides
        if "wärmer" in prompt_lower or "warm" in prompt_lower:
            meta["eq_low"] = 1.1

        # Fallback chain
        if not chain:
            chain = ["noise_reducer"]

        return {"chain": chain, "meta": meta}


# ---------------------------------------------------------------------------
# Singleton accessor (thread-safe, double-checked locking)
# ---------------------------------------------------------------------------
import threading as _threading

_multimodal_decision_engine_instance = None
_multimodal_decision_engine_lock = _threading.Lock()


def get_multimodal_decision_engine() -> MultimodalDecisionEngine:
    """Return the process-wide singleton MultimodalDecisionEngine instance."""
    global _multimodal_decision_engine_instance
    if _multimodal_decision_engine_instance is None:
        with _multimodal_decision_engine_lock:
            if _multimodal_decision_engine_instance is None:
                _multimodal_decision_engine_instance = MultimodalDecisionEngine()
    return _multimodal_decision_engine_instance
