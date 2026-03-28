#!/usr/bin/env python3
"""Pre-commit hook: verify 14 Musical Goals are configured."""

import sys

sys.path.insert(0, ".")
from backend.core.musical_goals.musical_goals_metrics import MusicalGoalsChecker

c = MusicalGoalsChecker()
n = len(c.thresholds)
assert n == 14, f"Erwartet 14 Musical Goals, erhalten {n}"
print("OK: 14 Musical Goals konfiguriert")
