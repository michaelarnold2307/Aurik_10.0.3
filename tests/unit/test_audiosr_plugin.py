from __future__ import annotations

import numpy as np


def test_audiosr_hf_extend_uses_sbr_fallback(monkeypatch):
    from plugins.audiosr_plugin import AudioSRPlugin

    plugin = AudioSRPlugin()

    def _fail(_x, _sr):
        raise RuntimeError("exciter failed")

    monkeypatch.setattr(plugin, "_spectral_exciter", _fail)

    audio = np.random.randn(48_000).astype(np.float32) * 0.05
    out = plugin._hf_extend(audio, 48_000)

    assert out.shape == audio.shape
    assert np.all(np.isfinite(out))
    assert np.max(np.abs(out)) <= 1.0
