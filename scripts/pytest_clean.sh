#!/usr/bin/env bash
set -euo pipefail

# Startet pytest mit stabilem Warning-Filter fuer die bekannte Trio-Excepthook-Meldung.
# Alle Argumente werden unveraendert an pytest weitergereicht.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${ROOT_DIR}/.venv_aurik/bin/python"
SAFE_RUNNER_BIN="${ROOT_DIR}/run_tests_safe.sh"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "Fehler: Python-Interpreter nicht gefunden: ${PYTHON_BIN}" >&2
  exit 1
fi

# VS-Code-Crash-Schutz:
# In VS-Code-Terminals laufen Langtests standardmäßig isoliert in eigener cgroup,
# damit OOM/Signal den Editor nicht mitreißen.
_IN_VSCODE_TERMINAL=0
if [[ "${TERM_PROGRAM:-}" == "vscode" || -n "${VSCODE_PID:-}" || -n "${VSCODE_IPC_HOOK_CLI:-}" ]]; then
  _IN_VSCODE_TERMINAL=1
fi

_USE_SAFE_RUNNER="${AURIK_PYTEST_CLEAN_USE_SAFE:-1}"
if [[ "${_IN_VSCODE_TERMINAL}" -eq 1 && "${_USE_SAFE_RUNNER}" != "0" && -x "${SAFE_RUNNER_BIN}" ]]; then
  export PYTHONWARNINGS="ignore::RuntimeWarning:trio._core._multierror"
  exec "${SAFE_RUNNER_BIN}" "$@"
fi

exec "${PYTHON_BIN}" -W "ignore::RuntimeWarning:trio._core._multierror" -m pytest "$@"
