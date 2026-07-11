"""Laufzeitumgebungs-Auswahl für Entwickler-Starts.

Chooses the ROCm virtual environment only when the interpreter can actually
provide both PyTorch ROCm and ONNX Runtime ROCm execution providers. Otherwise
falls back to the standard CPU environment.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_PROBE_CODE = r"""
import json
import sys

result = {
    "torch_import": False,
    "torch_cuda_available": False,
    "torch_hip": None,
    "onnxruntime_import": False,
    "ort_providers": [],
}

try:
    import torch

    result["torch_import"] = True
    result["torch_cuda_available"] = bool(torch.cuda.is_available())
    result["torch_hip"] = getattr(getattr(torch, "version", None), "hip", None)
except Exception as e:
    logger.warning("runtime_env_selector.py::unknown fallback: %s", e)
    pass

try:
    import onnxruntime as ort

    result["onnxruntime_import"] = True
    result["ort_providers"] = list(ort.get_available_providers())
except Exception as e:
    logger.warning("runtime_env_selector.py::unknown fallback: %s", e)
    pass

sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
"""


@dataclass(frozen=True)
class RuntimeProbe:
    python_path: Path
    torch_import: bool
    torch_cuda_available: bool
    torch_hip: str | None
    onnxruntime_import: bool
    ort_providers: tuple[str, ...]

    @property
    def has_rocm(self) -> bool:
        return (
            self.torch_import
            and self.torch_cuda_available
            and bool(self.torch_hip)
            and self.onnxruntime_import
            and "ROCMExecutionProvider" in self.ort_providers
        )


def _candidate_paths(repo_root: Path) -> list[Path]:
    # Cross-platform venv interpreter candidates (Linux/macOS + Windows).
    # Order matters: prefer ROCm environment when fully available.
    return [
        repo_root / ".venv_rocm" / "bin" / "python",
        repo_root / ".venv_rocm" / "Scripts" / "python.exe",
        repo_root / ".venv_aurik" / "bin" / "python",
        repo_root / ".venv_aurik" / "Scripts" / "python.exe",
    ]


def probe_python_runtime(python_path: Path) -> RuntimeProbe | None:
    if not python_path.exists() or not os.access(python_path, os.X_OK):
        return None

    try:
        proc = subprocess.run(
            [str(python_path), "-c", _PROBE_CODE],
            check=True,
            capture_output=True,
            text=True,
            timeout=12,
        )
    except Exception as e:
        logger.warning("runtime_env_selector.py::probe_python_runtime fallback: %s", e)
        return None

    try:
        payload = json.loads(proc.stdout.strip() or "{}")
    except json.JSONDecodeError:
        return None

    return RuntimeProbe(
        python_path=python_path,
        torch_import=bool(payload.get("torch_import")),
        torch_cuda_available=bool(payload.get("torch_cuda_available")),
        torch_hip=payload.get("torch_hip"),
        onnxruntime_import=bool(payload.get("onnxruntime_import")),
        ort_providers=tuple(str(provider) for provider in (payload.get("ort_providers") or [])),
    )


def select_runtime_python(repo_root: str | Path) -> Path:
    root = Path(repo_root).resolve()
    probes: list[RuntimeProbe] = []

    for candidate in _candidate_paths(root):
        probe = probe_python_runtime(candidate)
        if probe is not None:
            probes.append(probe)

    for probe in probes:
        if probe.has_rocm:
            return probe.python_path

    for probe in probes:
        if probe.python_path.parent.parent.name == ".venv_aurik":
            return probe.python_path

    current = Path(sys.executable).resolve()
    if current.exists():
        return current
    return root / ".venv_aurik" / "bin" / "python"


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    repo_root = Path(__file__).resolve().parents[2]
    selected = select_runtime_python(repo_root)
    if args == ["--print-python"]:
        sys.stdout.write(f"{selected}\n")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
