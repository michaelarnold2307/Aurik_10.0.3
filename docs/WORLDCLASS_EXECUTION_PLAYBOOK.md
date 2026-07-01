# Worldclass Execution Playbook (One-Button, Psychoakustik-First)

Dieses Playbook operationalisiert die 30-60-90 Ziele in einem ausfuehrbaren Workflow.

## 1. Klasse-C-Revalidierung (Pflicht)

Plan erstellen:

```bash
./.venv_aurik/bin/python scripts/run_class_c_revalidation_plan.py \
  --manifest config/class_c_revalidation_manifest.example.json \
  --out-dir reports/revalidation
```

WP1 dry-run:

```bash
./.venv_aurik/bin/python scripts/run_wp1_material_vqi_revalidation.py \
  --run-dir reports/revalidation/<run_id>
```

WP1 execute (technischer Start):

```bash
./.venv_aurik/bin/python scripts/run_wp1_material_vqi_revalidation.py \
  --run-dir reports/revalidation/<run_id> \
  --execute \
  --max-cases 5 \
  --max-seconds 8 \
  --ml-runtime-budget-s 20
```

Summary erzeugen:

```bash
./.venv_aurik/bin/python scripts/summarize_class_c_revalidation_results.py \
  --input-csv reports/revalidation/<run_id>/result_template.csv
```

## 2. KPI-Dashboard (Weltspitze)

```bash
./.venv_aurik/bin/python scripts/worldclass_kpi_dashboard.py \
  --repo-root . \
  --threshold-config config/worldclass_kpi_thresholds.json \
  --out-dir reports/worldclass
```

Ausgabe:

- reports/worldclass/worldclass_kpi_dashboard.json
- reports/worldclass/worldclass_kpi_dashboard.md

## 3. Trusted Report + Release-Gate

Vor dem Release-Gate muss der professionelle Vertrauensreport erzeugt werden. Der Report bricht bei
fehlender Evidenz oder Hoerrisiko nicht hart ab, sondern dokumentiert den bestmoeglichen sicheren
Status (`PASS`, `RECOVERED`, `DEGRADED`) inklusive Recovery-Policy.

```bash
./.venv_aurik/bin/python scripts/trusted_vocal_restoration_report.py \
  --result-csv reports/revalidation/<run_id>/result_template.csv \
  --dashboard-json reports/worldclass/worldclass_kpi_dashboard.json \
  --threshold-config config/worldclass_kpi_thresholds.json \
  --out-dir reports/worldclass
```

Ausgabe:

- reports/worldclass/trusted_vocal_restoration_report.json
- reports/worldclass/trusted_vocal_restoration_report.md

Report-Status:

- `PASS`: Evidenz vollstaendig, kein Hoerschaden-/Safety-Risiko.
- `RECOVERED`: Evidenz-/Automationsluecke, aber bestmoeglicher Restaurierungsstatus dokumentiert.
- `DEGRADED`: Hoer-/Safety-Risiko; Export-Policy ist `input_or_best_safe_checkpoint`.

Der Report enthaelt zusaetzlich eine `user_confidence_summary`: eine nutzerlesbare Begruendung,
warum Aurik das Ergebnis freigibt, schuetzt oder als recovered dokumentiert. Diese Zusammenfassung
bleibt One-Button-konform: `manual_action_required=false`, erlaubte Nutzerentscheidung nur
`mode_selection`.

```bash
./.venv_aurik/bin/python scripts/worldclass_release_gate.py \
  --dashboard-json reports/worldclass/worldclass_kpi_dashboard.json
```

Exit-Code:

- 0: PASS
- 2: Release-Evidenz unvollstaendig oder KPI-Target verfehlt; Restaurationslauf bleibt bestmoeglich dokumentiert.

## 4. Normative Contract-Tests

```bash
./.venv_aurik/bin/python -m pytest \
  tests/normative/test_worldclass_kpi_release_gate_contract.py \
  -p no:xdist --override-ini="addopts=--strict-markers --import-mode=importlib" \
  --timeout=30 --tb=short -q --disable-warnings --no-header
```

## 4b. End-to-End Autopilot (ein Befehl)

```bash
./.venv_aurik/bin/python scripts/worldclass_autopilot_pipeline.py \
  --repo-root . \
  --create-plan \
  --execute-wp1 \
  --max-cases 5 \
  --max-seconds 8 \
  --ml-runtime-budget-s 20
```

## 5. Zielmetriken (aktuelle Targets)

Quelle: config/worldclass_kpi_thresholds.json

- artifact_freedom_pass_rate >= 0.99
- vqi_margin_pass_rate >= 0.95
- wcs_pass_rate >= 0.95
- false_reject_rate <= 0.08
- runtime_p95_seconds <= 720
- trusted_vocal_restoration.min_professional_cases >= 20
- trusted_vocal_restoration.target_cases >= 50
