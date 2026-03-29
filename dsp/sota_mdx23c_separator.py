import os
import sys
from importlib.util import module_from_spec, spec_from_file_location
from types import ModuleType
from typing import Any

import numpy as np

"""
---
modul_name: SotaMDX23CSeparator
aufgabe: SOTA-Musik-Quellenseparation (MDX23C)
ein_ausgabe_typen:
    input: np.ndarray (Audio)
    output: dict (Stems)
staerken: Deep-Learning, SOTA, flexibel
schwaechen: Modellabhängig, benötigt Modelle/Weights
abhaengigkeiten: [numpy, torch, inference]
---
"""
MDX23C_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "../models/mdx23c"))
if MDX23C_PATH not in sys.path:
    sys.path.append(MDX23C_PATH)


def _load_inference_module() -> ModuleType:
    """Load MDX23C inference module from bundled model path."""
    inference_path = os.path.join(MDX23C_PATH, "inference.py")
    spec = spec_from_file_location("mdx23c_inference", inference_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"MDX23C inference module not loadable: {inference_path}")

    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_mdx23c_model_class() -> type[Any]:
    """Resolve EnsembleDemucsMDXMusicSeparationModel without static unresolved import."""
    inference_module = _load_inference_module()
    model_class = getattr(inference_module, "EnsembleDemucsMDXMusicSeparationModel", None)
    if model_class is None:
        raise ImportError("EnsembleDemucsMDXMusicSeparationModel not found in MDX23C inference module")
    return model_class


class SotaMDX23CSeparator:
    def __init__(self, device="cpu"):
        options = {
            "cpu": device == "cpu",
            "overlap_large": 0.75,
            "overlap_small": 0.75,
            "use_kim_model_1": False,
            "single_onnx": False,
        }
        model_class = _load_mdx23c_model_class()
        self.model = model_class(options)
        self.device = device

    def separate(self, audio: np.ndarray, sr: int) -> dict:
        # Erwartet: [2, N] für Stereo, ggf. expandieren
        if audio.ndim == 1:
            audio = np.stack([audio, audio], axis=0)
        elif audio.shape[0] != 2:
            raise ValueError("MDX23C erwartet Stereo-Input [2, N]")
        # Transponiere zu [N, 2] für die Methode
        audio_for_mdx = audio.T
        separated, _ = self.model.separate_music_file(audio_for_mdx, sr)
        vocals = separated.get("vocals")
        accompaniment = separated.get("other")
        # Rücktransponieren auf [N] falls mono, sonst [N] pro Kanal
        if vocals is not None and vocals.ndim > 1:
            vocals = vocals[:, 0] if vocals.shape[1] == 1 else vocals.mean(axis=1)
        if accompaniment is not None and accompaniment.ndim > 1:
            accompaniment = accompaniment[:, 0] if accompaniment.shape[1] == 1 else accompaniment.mean(axis=1)
        # Auf Input-Länge trimmen
        vocals = vocals[: audio.shape[1]] if vocals is not None else None
        accompaniment = accompaniment[: audio.shape[1]] if accompaniment is not None else None
        return {"vocals": vocals, "accompaniment": accompaniment}
