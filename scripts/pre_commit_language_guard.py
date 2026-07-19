#!/usr/bin/env python3
"""§v10.51 Pre-Commit Sprache-Guard — erzwingt deutsche Log-Meldungen.

Prüft vor jedem Commit:
  - logger.info/warning/error/debug Meldungen auf englische Wörter
  - Blockiert Commits mit englischen Log-Meldungen
  - Erzwingt einheitlich deutsche Terminal-Ausgabe während der Restaurierung

Exit 0 = sauber, Exit 1 = englische Log-Meldung gefunden.

Autor: Aurik 10 — 19. Juli 2026
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Deutsche Fachbegriffe, die in Logs OK sind (keine false positives)
_GERMAN_TECH_TERMS: set[str] = {
    "debug", "info", "warning", "error",  # logger method names
    "ok", "pass",  # status
}

# Englische Wörter, die in Log-Meldungen NICHT vorkommen dürfen
# (Groß-/Kleinschreibung wird ignoriert)
_ENGLISH_FORBIDDEN: list[str] = [
    "non-blocking", "non-critical", "fallback",
    "calibrated", "calibration",
    "threshold", "thresh",
    "session", "capture", "record",
    "failed", "failure",
    "skipped", "skip",
    "executed", "execute",
    "applied", "apply",
    "completed", "complete",
    "started", "finished",
    "error",  # in Log-Text, nicht als Logger-Methode
    "warning",  # in Log-Text
    "update", "updating",
    "recovery", "recover",
    "loaded", "loading", "load",
    "saved", "save", "saving",
    "created", "create",
    "initialized", "initialize",
    "detected", "detect",
    "processed", "process",
    "generated", "generate",
    "configured", "configure",
    "enabled", "disabled",
    "available", "unavailable",
    "successful", "successfully",
    "failed to",
    "unable to",
    "trying to",
    "attempt",
    "retry",
    "timeout",
    "cached", "cache",
    "cleared", "clear",
    "reset",
    "aborted", "abort",
    "terminated", "terminate",
    "shutdown",
    "startup",
    "initializing",
    "finalize",
    "validate", "validation",
    "verifying", "verify",
    "checking", "check",
    "computing", "compute",
    "analyzing", "analysis",
    "extracting", "extract",
    "importing", "export",
    "reading", "writing",
    "fetching", "fetch",
    "sending", "send",
    "receiving", "receive",
    "connecting", "connection",
    "disconnect",
    "pending",
    "running", "run",
    "stopping", "stopped",
    "restart",
    "stage",
    "phase",
    "mode",
    "profile", "profiling",
    "budget",
    "ratio",
    "score",
    "result",
    "output", "input",
    "reference",
    "original",
    "restored", "restore",
    "enhanced", "enhance",
    "optimized", "optimize",
    "adjusted", "adjust",
    "normalized", "normalize",
]

# Ausnahmen: Zeilen die trotz englischer Wörter OK sind
# (z.B. Code-Kommentare, Spec-Referenzen, technische IDs)
_EXEMPT_PATTERNS: list[str] = [
    r"#\s*§",           # Spec-Referenzen in Kommentaren
    r"#\s*noqa",         # noqa-Kommentare
    r"#\s*pylint:",      # pylint-Direktiven
    r"#\s*type:",        # type-Kommentare
    r"logger\.(debug|info|warning|error)\($",  # Logger-Aufruf ohne String
    r"exc_info=True",    # Logger-Parameter
    r"stack_info=True",  # Logger-Parameter
]


def get_changed_files() -> list[Path]:
    """Ermittelt git-staged .py-Dateien."""
    files: list[Path] = []
    for cmd in [
        ["git", "-C", str(_PROJECT_ROOT), "diff", "--cached", "--name-only"],
        ["git", "-C", str(_PROJECT_ROOT), "diff", "--name-only"],
    ]:
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            for line in result.stdout.strip().split("\n"):
                line = line.strip()
                if line.endswith(".py") and not line.startswith(("tests/", "benchmarks/")):
                    fp = _PROJECT_ROOT / line
                    if fp.exists():
                        files.append(fp)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
    return files


def _is_exempt(line: str) -> bool:
    """Prüft ob eine Zeile von der Sprach-Prüfung ausgenommen ist."""
    for pat in _EXEMPT_PATTERNS:
        if re.search(pat, line):
            return True
    return False


def _contains_english_word(text: str) -> tuple[bool, str]:
    """Prüft ob ein Text englische Wörter enthält. Gibt (True, wort) zurück."""
    words = re.findall(r"[a-zA-ZäöüÄÖÜß]{3,}", text.lower())
    for word in words:
        if word in _GERMAN_TECH_TERMS:
            continue
        if word in _ENGLISH_FORBIDDEN:
            return True, word
    return False, ""


class LogLanguageVisitor(ast.NodeVisitor):
    """AST-Visitor der englische Log-Meldungen findet."""

    def __init__(self, source_lines: list[str]) -> None:
        self.source_lines = source_lines
        self.violations: list[tuple[int, str, str]] = []

    def visit_Call(self, node: ast.Call) -> None:
        """Prüft logger.info/warning/error/debug Aufrufe auf englische Meldungen."""
        if isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name) and node.func.value.id == "logger":
                if node.func.attr in ("debug", "info", "warning", "error"):
                    if node.args:
                        first_arg = node.args[0]
                        if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                            msg = first_arg.value
                            line_no = node.lineno
                            source_line = self.source_lines[line_no - 1] if line_no <= len(self.source_lines) else ""
                            if _is_exempt(source_line):
                                self.generic_visit(node)
                                return
                            is_en, word = _contains_english_word(msg)
                            if is_en:
                                self.violations.append((
                                    line_no,
                                    "EN",
                                    f'"{msg[:60]}..." → enthält "{word}"',
                                ))
                        # Auch f-Strings prüfen
                        elif isinstance(first_arg, ast.JoinedStr):
                            # Extrahiere Text aus f-String
                            parts = []
                            for val in first_arg.values:
                                if isinstance(val, ast.Constant) and isinstance(val.value, str):
                                    parts.append(val.value)
                            msg = "".join(parts)
                            line_no = node.lineno
                            source_line = self.source_lines[line_no - 1] if line_no <= len(self.source_lines) else ""
                            if _is_exempt(source_line):
                                self.generic_visit(node)
                                return
                            is_en, word = _contains_english_word(msg)
                            if is_en:
                                self.violations.append((
                                    line_no,
                                    "EN",
                                    f'f"...{msg[:40]}..." → enthält "{word}"',
                                ))
        self.generic_visit(node)


def check_file(filepath: Path) -> list[tuple[int, str, str]]:
    """Prüft eine Datei auf englische Log-Meldungen."""
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(filepath))
    except SyntaxError:
        return []

    visitor = LogLanguageVisitor(source.split("\n"))
    visitor.visit(tree)
    return visitor.violations


def main() -> int:
    """Haupteinstiegspunkt."""
    files = get_changed_files()
    if not files:
        print("✅ Sprache-Guard: Keine .py-Dateien zum Prüfen")
        return 0

    total = 0
    for fp in sorted(set(files)):
        violations = check_file(fp)
        if violations:
            rel = fp.relative_to(_PROJECT_ROOT)
            print(f"\n─── {rel} ───")
            for line, rule, desc in violations:
                print(f"  L{line}: [{rule}] {desc}")
                total += 1

    print(f"\n{'='*60}")
    print(f"Geprüft: {len(set(files))} Dateien, {total} englische Log-Meldungen")

    if total == 0:
        print("✅ Alle Log-Meldungen auf Deutsch")
        return 0
    else:
        print(f"❌ {total} englische Log-Meldungen — Commit blockiert")
        print("   → Alle Log-Meldungen MÜSSEN auf Deutsch sein")
        print("   → logger.info('Processing...')  →  logger.info('Verarbeite...')")
        return 1


if __name__ == "__main__":
    sys.exit(main())
