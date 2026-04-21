#!/bin/bash
# Aurik 9 — Startskript mit venv-Python (.venv_aurik, Python 3.10.12)
# GPU-Modus: wenn .venv_rocm und /dev/kfd vorhanden → ROCm-Beschleunigung (AMD GPU)
# Verwendung: ./run_aurik.sh [Argumente]
#   AURIK_FORCE_CPU=1  ./run_aurik.sh  — erzwingt CPU-only (deaktiviert ROCm)
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_CPU="$SCRIPT_DIR/.venv_aurik/bin/python"
VENV_ROCM="$SCRIPT_DIR/.venv_rocm/bin/python"
PID_FILE="$SCRIPT_DIR/temp_repro/aurik_gui.pid"
LOG_FILE="$SCRIPT_DIR/logs/aurik_frontend.out"

# GPU-Erkennung: ROCm-venv + KFD-Device vorhanden und nicht explizit deaktiviert
if [[ "${AURIK_FORCE_CPU:-0}" != "1" && -x "$VENV_ROCM" && -e "/dev/kfd" ]]; then
    VENV_PYTHON="$VENV_ROCM"
    _GPU_MODE="ROCm (AMD GPU)"
else
    VENV_PYTHON="$VENV_CPU"
    _GPU_MODE="CPU-only"
fi

if [[ ! -x "$VENV_PYTHON" ]]; then
    echo "FEHLER: venv-Python nicht gefunden: $VENV_PYTHON" >&2
    echo "Bitte zuerst: python3 -m venv .venv_aurik && .venv_aurik/bin/pip install -r requirements/requirements.txt" >&2
    exit 1
fi

mkdir -p "$SCRIPT_DIR/temp_repro" "$SCRIPT_DIR/logs"
cd "$SCRIPT_DIR"

echo "Aurik GPU-Modus: ${_GPU_MODE} (Python: ${VENV_PYTHON##*/../../})"

# Kein Doppelstart: verhindert UI-Konflikte und wiederholte Force-Quit-Dialoge.
if pgrep -f "$VENV_PYTHON Aurik910/main.py" >/dev/null 2>&1; then
    _pid="$(pgrep -f "$VENV_PYTHON Aurik910/main.py" | head -n 1)"
    echo "Aurik läuft bereits (PID ${_pid})."
    exit 0
fi

# In VS Code-Terminals detach starten, damit VS Code den GUI-Prozess nicht verwaltet.
if [[ "${TERM_PROGRAM:-}" == "vscode" ]]; then
    nohup "$VENV_PYTHON" Aurik910/main.py "$@" >>"$LOG_FILE" 2>&1 &
    _pid="$!"
    echo "$_pid" >"$PID_FILE"
    echo "Aurik detached gestartet (PID ${_pid}). Log: $LOG_FILE"
    exit 0
fi

exec "$VENV_PYTHON" Aurik910/main.py "$@"
