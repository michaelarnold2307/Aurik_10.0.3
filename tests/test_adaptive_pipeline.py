import os
import sys
from io import BytesIO
from types import SimpleNamespace
from typing import Any, cast

import numpy as np
import pytest
import soundfile as sf

# Third-party deprecations emitted by optional plugin/model imports during
# AdaptiveProcessingPipeline initialization (outside our code ownership).
pytestmark = [
    pytest.mark.filterwarnings(
        r"ignore:torch\.nn\.utils\.weight_norm is deprecated in favor of torch\.nn\.utils\.parametrizations\.weight_norm\.:UserWarning"
    ),
    pytest.mark.filterwarnings(r"ignore:pkg_resources is deprecated as an API\.:UserWarning"),
]

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from backend.adaptive_pipeline import AdaptiveProcessingPipeline


def test_pipeline_initialization():
    pipeline = AdaptiveProcessingPipeline()
    assert pipeline.context_analyzer is not None
    assert pipeline.goal_engine is not None
    assert pipeline.quality_control is not None
    assert isinstance(pipeline.log, list)
    assert pipeline.logger is not None


# Erweiterung: Teste Policy-Engine (im __init__ gesetzt)
def test_policy_engine_exists():
    pipeline = AdaptiveProcessingPipeline()
    assert hasattr(pipeline, "policy_engine")


def test_run_uses_authoritative_medium_transfer_chain(monkeypatch):
    pipeline = AdaptiveProcessingPipeline()

    medium_result = SimpleNamespace(
        transfer_chain=["vinyl", "cassette", "mp3_low"],
        medium_confidences=[0.82, 0.71, 0.66],
        primary_material="vinyl",
        confidence=0.82,
    )

    audio = np.zeros(4800, dtype=np.float32)
    buffer = BytesIO()
    sf.write(buffer, audio, 48000, format="WAV")

    captured: dict[str, object] = {}

    def _stop_after_medium_capture(audio_np, sr_audio, file_path=None, metadata=None):
        captured["metadata"] = metadata
        raise RuntimeError("stop-after-medium")

    monkeypatch.setattr(pipeline.audio_monitor, "capture_baseline", _stop_after_medium_capture)

    with pytest.raises(RuntimeError, match="stop-after-medium"):
        pipeline.run(buffer.getvalue(), {"medium_result": medium_result, "file_path": "demo.wav"})

    assert pipeline.log[0]["step"] == "media_chain_detection"
    assert pipeline.log[0]["media_chain"] == [
        {"medium": "vinyl", "confidence": 0.82},
        {"medium": "cassette", "confidence": 0.71},
        {"medium": "mp3_low", "confidence": 0.66},
    ]
    assert captured["metadata"] == {
        "detected_medium": {"type": "vinyl", "confidence": 0.82},
        "user_profile": None,
    }


def test_separate_vocals_v8_forces_safety_wrapper_even_when_disabled() -> None:
    pipeline = AdaptiveProcessingPipeline()

    audio = np.zeros(2048, dtype=np.float32)
    sr = 44100

    class _DummySeparator:
        def __init__(self):
            self.direct_calls = 0

        def separate(self, _audio, _sr, return_individual=False):
            self.direct_calls += 1
            return {"vocals": _audio, "instrumental": _audio}

        def get_metrics(self):
            return {"total_separations": 1, "fusion_strategy": "dummy"}

    class _DummySafety:
        def __init__(self):
            self.calls = 0

        def safe_separate(self, _audio, _sr, return_individual=False):
            self.calls += 1
            return {"vocals": _audio, "instrumental": _audio}

    sep = _DummySeparator()
    safety = _DummySafety()
    pipeline_test_double = cast(Any, pipeline)
    pipeline_test_double.vocal_separator_v8 = sep
    pipeline_test_double.vocal_safety_wrapper = safety
    pipeline_test_double.audio_monitor = SimpleNamespace(track_operation=lambda *_args, **_kwargs: None)

    stems = pipeline.separate_vocals_v8(audio, sr, use_safety_wrapper=False)

    assert safety.calls == 1
    assert sep.direct_calls == 0
    assert isinstance(stems, dict)
    assert "vocals" in stems
    assert "instrumental" in stems


def test_correct_pitch_v8_fails_closed_without_safety_wrapper() -> None:
    pipeline = AdaptiveProcessingPipeline()

    audio = np.zeros(1024, dtype=np.float32)
    pipeline_test_double = cast(Any, pipeline)
    pipeline_test_double.pitch_corrector_v8 = object()
    pipeline_test_double.pitch_corrector_safety = None

    corrected, metadata = pipeline.correct_pitch_v8(audio, 44100, use_safety_wrapper=False)

    assert np.array_equal(corrected, audio)
    assert metadata.get("corrected") is False
    assert metadata.get("reason") == "safety_wrapper_unavailable"
    assert metadata.get("error") == "unsafe_direct_processing_disabled"


def test_job_tracking_export_uses_bridge_export_guard() -> None:
    repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    src_path = os.path.join(repo_root, "backend", "adaptive_pipeline.py")
    with open(src_path, encoding="utf-8") as handle:
        src = handle.read()

    export_idx = src.index("from backend.api.bridge import export_guard as _export_guard")
    write_idx = src.index("sf.write(output_audio_path, _export_guard(current_audio), sr)")

    assert export_idx < write_idx
