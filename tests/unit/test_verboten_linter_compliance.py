"""Compliance-Auto-Verifikation [RELEASE_MUST] — Aurik VERBOTEN-Linter V01–V12 im CI.

Stellt sicher, dass kein Anti-Pattern-Scan-Ergebnis veraltet ist:
der Linter wird bei jedem Pytest-Lauf direkt ausgeführt und validiert.

Abgedeckte Regeln (ERROR-Level):
    V01 np.corrcoef → guarded dot-product
    V03 boundary='reflect' → 'even'
    V04 apply_musical_gain_envelope ohne reference_for_gate
    V05 print() statt logger
    V06 map_location='cuda' ohne ml_device_manager
    V07 scipy.signal.wiener() direkt
    V08 np.correlate O(n²)
    V09 from Aurik910 in backend/
    V10 load_audio_file ohne do_carrier_analysis=False
    V12 CAUSE_TO_PHASES/CAUSES Bidirektional-Sync (§2.59)
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_LINTER = _ROOT / "scripts" / "aurik_verboten_linter.py"
_PYTHON = sys.executable


class TestVerbotenlLinterZeroViolations:
    """Stellt sicher, dass der VERBOTEN-Linter im gesamten backend/ und plugins/ Verzeichnis
    keine ERROR-Level-Verstöße findet.

    Dieser Test ist kein Unit-Test eines einzelnen Moduls — er ist der systemische
    Compliance-Gate der verhindert, dass Scan-Ergebnisse veralten (§0f §0g)."""

    def test_linter_script_exists(self) -> None:
        assert _LINTER.exists(), f"aurik_verboten_linter.py nicht gefunden: {_LINTER}"

    def test_backend_no_error_violations(self) -> None:
        """V01–V12 ERROR-Level-Regeln: 0 Verstöße in backend/."""
        result = subprocess.run(
            [_PYTHON, str(_LINTER), str(_ROOT / "backend")],
            capture_output=True,
            text=True,
            timeout=60,
        )
        output = result.stdout + result.stderr
        # Exit 0 = keine ERROR-Verstöße (Warnings sind erlaubt)
        assert result.returncode == 0, (
            f"VERBOTEN-Linter meldet ERROR-Verstöße in backend/:\n\n{output}"
        )

    def test_plugins_no_error_violations(self) -> None:
        """V01–V12 ERROR-Level-Regeln: 0 Verstöße in plugins/."""
        result = subprocess.run(
            [_PYTHON, str(_LINTER), str(_ROOT / "plugins")],
            capture_output=True,
            text=True,
            timeout=60,
        )
        output = result.stdout + result.stderr
        assert result.returncode == 0, (
            f"VERBOTEN-Linter meldet ERROR-Verstöße in plugins/:\n\n{output}"
        )

    def test_causal_reasoner_v12_sync(self) -> None:
        """V12 speziell: CAUSE_TO_PHASES/CAUSES Bidirektional-Sync in causal_defect_reasoner.py."""
        cdr = _ROOT / "backend" / "core" / "causal_defect_reasoner.py"
        result = subprocess.run(
            [_PYTHON, str(_LINTER), str(cdr)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        output = result.stdout + result.stderr
        assert result.returncode == 0, (
            f"V12 CAUSE_TO_PHASES/CAUSES Sync-Verletzung in causal_defect_reasoner.py:\n\n{output}"
        )

    def test_no_stash_drift_above_threshold(self) -> None:
        """Stash-Drift-Guard: Nicht mehr als 2 offene Stashes (Snapshot-Akkumulation).

        Mehr als 2 Stashes deuten auf Snapshot-Drift — ältere Fixes die nicht
        in HEAD gemergt wurden (§0g Autonomes-Entscheidungs-Doktrin).
        """
        result = subprocess.run(
            ["git", "stash", "list"],
            capture_output=True,
            text=True,
            cwd=str(_ROOT),
            timeout=10,
        )
        stash_count = len([l for l in result.stdout.strip().splitlines() if l.strip()])
        assert stash_count <= 2, (
            f"Stash-Drift: {stash_count} Stashes vorhanden (Limit: 2).\n"
            "Vor dem nächsten Commit auflösen:\n"
            "  git stash show --stat   → Inhalt prüfen\n"
            "  git stash drop          → Verwerfen wenn bereits in HEAD\n"
            "  git stash pop           → Integrieren (Konflikte manuell lösen)\n"
            "Hintergrund: Snapshot-Stashes auf alten Commit-Basen führen zu "
            "Regressions-Reintroduktion (§0c Universalitäts-Invariante)."
        )
