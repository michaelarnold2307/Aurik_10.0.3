#!/usr/bin/env python3
"""V01-V52 VERBOTEN-Linter v2 — Kontextsensitiv, weniger False Positives."""
from __future__ import annotations
import json, os, re, sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent

RULES = {
    "V01": {"p": r"from backend\.core import|import backend\.core\.", "d": "Bridge-Bypass", "skip": {"bridge","__init__","conftest","denker/","api/","policy/","Aurik10/"}},
    "V14": {"p": r"(?:^|\s)(?:PESQ|pesq|SI[.-]SDR|si_sdr|STOI|stoi|DNSMOS|NISQA|VISQOL.*Speech)\b", "d": "Speech-Metrik", "skip": {"test_","VERBOTEN","forbidden","benchmark","sota_eval","spec","docs"}},
    "V21": {"p": r"int\s*\(\s*audio.*\)\s*(?:#.*(?:ohne|without|kein).*(?:dither|noise.shape))", "d": "Truncation ohne Dither", "skip": {"exporter.py","test_","dither"}},
    "V44": {"p": r"IACC\s*[<>]\s*0\.[0-9]+", "d": "IACC ohne Stereo-Guard", "skip": {"stereo_guard","test_","musical_goals_metrics"}},
}

SKIP_DIRS = {".venv","__pycache__","node_modules",".git","models/","temp_repro/"}

def should_skip(fp, rid):
    r = str(fp)
    if any(s in r for s in SKIP_DIRS): return True
    for s in RULES.get(rid,{}).get("skip",set()):
        if s in r: return True
    return False

def scan(fp):
    if fp.suffix != ".py": return []
    try: lines = fp.read_text(encoding="utf-8",errors="replace").splitlines()
    except: return []
    code = []
    in_ds = False
    for l in lines:
        s = l.strip()
        if s.startswith('"""') or s.startswith("'''"): in_ds = not in_ds; continue
        if in_ds: continue
        if s.startswith("#"): continue
        code.append(l)
    ct = "\n".join(code)
    rel = fp.relative_to(_PROJECT_ROOT)
    issues = []
    for rid, ru in RULES.items():
        if should_skip(fp, rid): continue
        if re.search(ru["p"], ct, re.IGNORECASE|re.MULTILINE):
            issues.append(f"{rid}: {ru['d']} — {rel}")
    return issues

def main():
    import argparse
    a = argparse.ArgumentParser()
    a.add_argument("--ci", action="store_true"); a.add_argument("--json", action="store_true")
    args = a.parse_args()
    ai = {}
    for pf in _PROJECT_ROOT.rglob("*.py"):
        iss = scan(pf)
        if iss: ai[str(pf.relative_to(_PROJECT_ROOT))] = iss
    total = sum(len(v) for v in ai.values())
    if args.json:
        print(json.dumps({"clean": total==0, "issues": total, "files": len(list(_PROJECT_ROOT.rglob("*.py")))}))
    else:
        if total:
            print(f"\n{total} issues in {len(ai)} files:")
            for f, iss in sorted(ai.items()):
                for i in iss: print(f"  {i}")
            return 1
        else:
            print("VERBOTEN-Linter: clean")
    return 0

if __name__ == "__main__":
    sys.exit(main())
