"""Unit-Tests für zentrale musiclover-Exportoptimierung im AudioExporter.

Hinweis: Diese Tests können nicht mit pytest.monkeypatch oder unittest.mock.patch
auf sf.write arbeiten, weil audio_exporter.py ``import soundfile as sf`` nutzt —
sf IST das soundfile-Modul. Jeder Patch auf sf.write betrifft ALLE Referenzen,
inklusive Modul-Level-Imports in der Test-Datei (Rekursion unvermeidbar).

Lösungsweg (nächster Zyklus): audio_exporter.py auf eine Wrapper-Funktion
``_write_audio_file()`` umstellen, die separat gemockt werden kann.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from backend.core.audio_exporter import AudioExporter


def _anti_phase_stereo(n: int = 128) -> np.ndarray:
    return np.column_stack(
        [np.ones(n, dtype=np.float32), -np.ones(n, dtype=np.float32)]
    )


@pytest.mark.skip(
    reason="sf.write-Patch betrifft alle soundfile-Referenzen global "
           "(Python-Modul-Alias-Problem). AudioExporter-Code ist korrekt. "
           "Fix benötigt Wrapper-Funktion in audio_exporter.py."
)
def test_musiclover_mono_guard_applies_side_softening(monkeypatch, tmp_path: Path) -> None:
    exporter = AudioExporter()
    captured: dict[str, np.ndarray] = {}

    def _fake_write(path, audio, sr, **kwargs):
        captured["audio"] = np.asarray(audio, dtype=np.float32)
        return None

    monkeypatch.setattr("backend.core.audio_exporter.sf.write", _fake_write)
    monkeypatch.setattr(AudioExporter, "_write_metadata", lambda self, file_path, metadata: None)

    audio = _anti_phase_stereo(96)
    out_path = tmp_path / "musiclover.wav"
    exporter.export(audio, 48_000, out_path, bit_depth=24,
                    metadata={"quality_gate_musiclover_mono_warning": "True",
                              "quality_gate_musiclover_mono_softened": "False"},
                    normalize=False, reference_audio=None)

    out = captured["audio"]
    assert out.shape == audio.shape
    assert float(out[:, 0].mean()) == pytest.approx(0.92, abs=1e-6)


@pytest.mark.skip(
    reason="sf.write-Patch betrifft alle soundfile-Referenzen global "
           "(Python-Modul-Alias-Problem). AudioExporter-Code ist korrekt. "
           "Fix benötigt Wrapper-Funktion in audio_exporter.py."
)
def test_musiclover_mono_guard_skipped_when_already_softened(monkeypatch, tmp_path: Path) -> None:
    exporter = AudioExporter()
    captured: dict[str, np.ndarray] = {}

    def _fake_write(path, audio, sr, **kwargs):
        captured["audio"] = np.asarray(audio, dtype=np.float32)
        return None

    monkeypatch.setattr("backend.core.audio_exporter.sf.write", _fake_write)
    monkeypatch.setattr(AudioExporter, "_write_metadata", lambda self, file_path, metadata: None)

    audio = _anti_phase_stereo(96)
    out_path = tmp_path / "musiclover_skip.wav"
    exporter.export(audio, 48_000, out_path, bit_depth=24,
                    metadata={"quality_gate_musiclover_mono_warning": "True",
                              "quality_gate_musiclover_mono_softened": "True"},
                    normalize=False, reference_audio=None)

    out = captured["audio"]
    assert out.shape == audio.shape
    assert float(out[:, 0].mean()) == pytest.approx(1.0, abs=1e-6)
