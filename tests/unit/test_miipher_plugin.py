"""Unit tests for the productive MIIPHER vocal SOTA adapter."""

import types

import numpy as np


def _patch_vocal_guards(monkeypatch) -> None:
    sys_modules = __import__("sys").modules
    monkeypatch.setitem(
        sys_modules,
        "backend.core.dsp.hnr_guard",
        types.SimpleNamespace(apply_hnr_blend=lambda pre, post, sr: (post, {"over_cleaned": False})),
    )
    monkeypatch.setitem(
        sys_modules,
        "backend.core.dsp.hallucination_guard",
        types.SimpleNamespace(
            check_hallucination=lambda pre, post, sr=48000, mode="restoration": types.SimpleNamespace(
                requires_rollback=False,
                spectral_novelty=0.0,
            )
        ),
    )


def test_miipher_adapter_uses_loaded_sgmse_plus(monkeypatch):
    import plugins
    from plugins.miipher_plugin import MiipherPlugin

    _patch_vocal_guards(monkeypatch)

    class _FakeSgmseResult:
        def __init__(self, audio: np.ndarray) -> None:
            self.audio = (audio * 0.4).astype(np.float32)
            self.model_used = "sgmse_plus_torchscript"

    class _FakeSgmsePlus:
        _model_loaded = True

        @staticmethod
        def enhance(audio: np.ndarray, sr: int, **kwargs):  # pylint: disable=unused-argument
            return _FakeSgmseResult(audio)

    fake_sgmse_mod = types.SimpleNamespace(get_sgmse_plus_plugin=lambda: _FakeSgmsePlus())
    monkeypatch.setitem(__import__("sys").modules, "plugins.sgmse_plugin", fake_sgmse_mod)
    monkeypatch.setattr(plugins, "sgmse_plugin", fake_sgmse_mod, raising=False)

    plugin = MiipherPlugin()
    audio = np.linspace(-0.2, 0.2, 4800, dtype=np.float32)
    result = plugin.enhance(audio, 48000, noise_snr_db=4.0)

    np.testing.assert_allclose(result, audio * 0.4, atol=1e-7)
    metadata = plugin.route_metadata
    assert metadata["model_used"] == "miipher_sgmse_plus"
    assert metadata["capability_status"] == "sota_fallback"
    assert metadata["native_miipher_loaded"] is False


def test_miipher_adapter_falls_back_to_dfn_when_sgmse_unloaded(monkeypatch):
    import plugins
    from plugins.miipher_plugin import MiipherPlugin

    _patch_vocal_guards(monkeypatch)

    class _FakeSgmsePlus:
        _model_loaded = False

        @staticmethod
        def enhance(audio: np.ndarray, sr: int):  # pylint: disable=unused-argument
            raise AssertionError("unloaded SGMSE+ must not run")

    class _FakeDfn:
        @staticmethod
        def enhance(audio: np.ndarray, sr: int, energy_bias_db: float = -6.0, **kwargs):  # pylint: disable=unused-argument
            return (audio * 0.7).astype(np.float32)

    fake_sgmse_mod = types.SimpleNamespace(get_sgmse_plus_plugin=lambda: _FakeSgmsePlus())
    fake_dfn_mod = types.SimpleNamespace(get_deepfilternet_plugin=lambda: _FakeDfn())
    sys_modules = __import__("sys").modules
    monkeypatch.setitem(sys_modules, "plugins.sgmse_plugin", fake_sgmse_mod)
    monkeypatch.setitem(sys_modules, "plugins.deepfilternet_v3_ii_plugin", fake_dfn_mod)
    monkeypatch.setattr(plugins, "sgmse_plugin", fake_sgmse_mod, raising=False)
    # OMLSA post-filter (compute_imcra_noise_estimate) im DFN-Fallback umgehen,
    # damit der rohe DFN-Ausgang (audio * 0.7) unverändert zurückkommt.

    def _raise_omlsa(*a, **k):
        raise ImportError("omlsa disabled in test")

    monkeypatch.setitem(
        sys_modules,
        "backend.core.dsp.noise_estimator",
        types.SimpleNamespace(compute_imcra_noise_estimate=_raise_omlsa),
    )

    plugin = MiipherPlugin()
    audio = np.linspace(-0.2, 0.2, 4800, dtype=np.float32)
    result = plugin.enhance(audio, 48000, noise_snr_db=4.0)

    np.testing.assert_allclose(result, audio * 0.7, atol=1e-7)
    metadata = plugin.route_metadata
    assert metadata["model_used"] == "miipher_deepfilternet_v3_ii"
    assert metadata["capability_status"] == "sota_fallback"
    fallback_chain = metadata.get("fallback_chain", [])
    assert isinstance(fallback_chain, list)
    assert any(str(item).startswith("sgmse_plus:") for item in fallback_chain)
