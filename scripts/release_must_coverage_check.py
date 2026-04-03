#!/usr/bin/env python3
"""Generate RELEASE_MUST coverage report for spec-to-test traceability.

This script links RELEASE_MUST clauses in .github/copilot-instructions.md
against normative CI gate tests in tests/normative/.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC_PATH = ROOT / ".github" / "copilot-instructions.md"
NORMATIVE_TESTS = ROOT / "tests" / "normative"
REPORT_PATH = ROOT / "reports" / "release_must_coverage.json"


@dataclass(frozen=True)
class CoverageItem:
    release_must: str
    matched_tests: list[str]
    covered: bool


def _extract_release_must_lines(text: str) -> list[str]:
    items: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if "[RELEASE_MUST]" not in line:
            continue
        if len(line) < 18:
            continue
        items.append(line)
    # Deduplicate while preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _keywords(line: str) -> set[str]:
    words = re.findall(r"[a-zA-Z0-9_\-]+", line.lower())
    stop = {
        "release_must",
        "der",
        "die",
        "das",
        "und",
        "mit",
        "für",
        "von",
        "auf",
        "in",
        "zu",
        "no",
        "mode",
    }
    return {w for w in words if len(w) >= 5 and w not in stop}


def _iter_normative_test_files() -> Iterable[Path]:
    if not NORMATIVE_TESTS.exists():
        return []
    return sorted(NORMATIVE_TESTS.glob("test_*.py"))


def _match_tests(release_line: str) -> list[str]:
    line_keys = _keywords(release_line)
    if not line_keys:
        return []

    matches: list[str] = []
    for path in _iter_normative_test_files():
        text = path.read_text(encoding="utf-8", errors="replace").lower()
        hit_count = sum(1 for key in line_keys if key in text)
        if hit_count >= 2:
            matches.append(str(path.relative_to(ROOT)))
    return matches


def build_report() -> dict:
    spec_text = SPEC_PATH.read_text(encoding="utf-8", errors="replace")
    release_must_items = _extract_release_must_lines(spec_text)

    coverage_items: list[CoverageItem] = []
    for item in release_must_items:
        tests = _match_tests(item)
        coverage_items.append(CoverageItem(release_must=item, matched_tests=tests, covered=bool(tests)))

    total = len(coverage_items)
    covered = sum(1 for item in coverage_items if item.covered)
    pct = (covered / total * 100.0) if total else 0.0

    return {
        "source": str(SPEC_PATH.relative_to(ROOT)),
        "normative_tests_dir": str(NORMATIVE_TESTS.relative_to(ROOT)),
        "total_release_must_items": total,
        "covered_items": covered,
        "coverage_percent": round(pct, 2),
        "items": [asdict(item) for item in coverage_items],
    }


def main() -> int:
    report = build_report()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Hard gate for CI: every RELEASE_MUST line should map to at least one normative test.
    uncovered = report["total_release_must_items"] - report["covered_items"]
    if uncovered > 0:
        print(
            f"RELEASE_MUST coverage incomplete: {report['covered_items']}/{report['total_release_must_items']} "
            f"({report['coverage_percent']}%)."
        )
        print(f"Report: {REPORT_PATH.relative_to(ROOT)}")
        return 2

    print(
        f"RELEASE_MUST coverage OK: {report['covered_items']}/{report['total_release_must_items']} "
        f"({report['coverage_percent']}%)."
    )
    print(f"Report: {REPORT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
