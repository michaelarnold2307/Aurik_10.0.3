#!/bin/bash
# Aurik 9 — Startskript mit venv-Python (.venv_aurik, Python 3.10.12)
# Verwendung: ./run_aurik.sh [Argumente]
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PYTHON="$SCRIPT_DIR/.venv_aurik/bin/python"

if [[ ! -x "$VENV_PYTHON" ]]; then
    echo "FEHLER: venv-Python nicht gefunden: $VENV_PYTHON" >&2
    echo "Bitte zuerst: python3 -m venv .venv_aurik && .venv_aurik/bin/pip install -r requirements/requirements.txt" >&2
    exit 1
fi

cd "$SCRIPT_DIR"
exec "$VENV_PYTHON" Aurik910/main.py "$@"
