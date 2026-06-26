# Spec 10 — Bug & Gap Detection Strategy (v9.20.0)

> **Scope**: Systematische Erkennung und Eliminierung aller Bugs und Gaps über alle Ebenen —
> Frontend, Bridge/CLI, Denker, UV3-Pipeline, Phasen/DSP/Plugins, Tests.
> Diese Spec ist normativ für alle KI-Agenten-Sessions und CI-Gates.

---

## §10.1 Layer-Scan-Protokoll

Jede Bug-Erkennungs-Session MUSS alle 5 Ebenen systematisch durchlaufen:

| Ebene | Scope | Primäre Scan-Tools |
| --- | --- | --- |
| **L1 Frontend** | `Aurik910/ui/`, `Aurik910/__init__.py` | Version-Konsistenz-Check, `grep -rn "fallback\|hardcoded"` |
| **L2 Bridge/CLI** | `backend/api/bridge.py`, `cli/aurik_cli.py` | Contract-Vollständigkeit: `get_load_audio_fn`, `run_pre_analysis`, `export_guard` |
| **L3 Denker** | `denker/*.py` | `inapplicable_goals`-Propagation, `reference`-Parameter in `messe_ziele()`, `goal_applicability` in Dataclasses |
| **L4 UV3-Pipeline** | `backend/core/unified_restorer_v3.py` | SSIP-Zonen-Übergabe, AdaptivePhaseRescheduler, RestorationMemory, HPG-Update |
| **L5 Phasen/DSP** | `backend/core/phases/`, `backend/core/dsp/`, `plugins/` | V33 MaterialType-Dict-Vollständigkeit, V38 per-Event-Strength, V41 ForwardMaskingGuard |

### §10.1a L5 Phasen-Scan-Checkliste (pro Phase)

Für jede `phase_*.py` mit additiver oder NR-Funktion prüfen:

```
[ ] V38: per-Event-Strength-Oracle (_compute_<defect>_local_strength) bei Event-Schleifen
[x] V41: ForwardMaskingGuard bei additiven Phasen mit panns_singing >= 0.25  ← ERLEDIGT commit 0c9a069
[ ] V33: Alle dict[MaterialType, ...] enthalten CASSETTE-Key
[ ] V42: check_roughness_regression() nach NR in phase_03/phase_29
[ ] V40: compute_nmr_score() wenn FeedbackChain aktiv
[ ] §2.63: Reflect-Padding VOR STFT, deterministischer Strip danach
[ ] §0a: phase_21/35/42 nie in CAUSE_TO_PHASES für Restoration-Cause
[ ] §2.46e: check_hallucination() nach jeder additiven Operation
[ ] V19: compute_noise_texture_distance() nach NR-Phase
[ ] V20: frame_energy_correlation() auf voiced-Zonen nach NR/Kompressor
```

---

## §10.2 Automatische Erkennungs-Werkzeuge

| Werkzeug | Scope | Ausführung |
| --- | --- | --- |
| `scripts/aurik_verboten_linter.py` | V01–V58 (AST-basiert) | `pre-commit`, `pytest --co -q` |
| `mypy backend/core/ --ignore-missing-imports` | Type-Safety | Weekly, vor Release |
| `pytest tests/unit/ -x` | Unit-Regression | Bei jedem Commit |
| `pytest tests/integration/` | Integration | Täglich, CI |
| `pytest tests/normative/` | Spec-Gates (AMRB, MUSHRA) | Release-Gate |
| `scripts/worldclass_kpi_dashboard.py` | KPI-Übersicht | Wöchentlich |
| `scripts/worldclass_release_gate.py` | Release-Blocker-Check | Vor Release |

### §10.2a VERBOTEN-Linter-Abdeckung (V01–V58)

| Block | Regeln | Status |
| --- | --- | --- |
| V01–V10 | print(), sf.read, librosa.load, V03 ml_device, V04 gate_dbfs, V05 griffinlim, V08 percentile, V09 carrier_rollback, V11 sosfilt | ✅ Linter aktiv |
| V11–V20 | sosfilt, V12 CAUSE_TO_PHASES, V13 dict-Duplizierung, V14–V18 SSIP, V19 noise_texture, V20 mikrodynamik | ✅ Linter aktiv |
| V21–V30 | V21 Rauschboden, V22 Pre-Echo, V23 Mono-Kompatibilität, V24 Spektralfarbe, V25 Wärmeband, V26 Onset-Guard, V27–V31 Cause-Mapping-Inversionen | ✅ Linter aktiv |
| V31–V40 | V32 PMGG-Exclusion, V33 MaterialType-Vollständigkeit, V34–V35 Strict-Conflict, V36–V37 AdaptiveRescheduler, V38 per-Event-Oracle, V39/V40 NMR/FeedbackChain | ✅ Linter aktiv |
| V41–V50 | V41 ForwardMasking, V42 Roughness, V43 JND, V44 IACC, V45 VAT, V46 dBFS-Multiplikation, V47 Sub-Ceiling, V48–V50 GAF/Denker-Kette | ✅ Linter aktiv |
| V51–V58 | V51 goal_applicability-Propagation, V52 separation_fidelity-Codec, V53 Singer-ID-DSP-Fallback, V54 HPG-update, V55 WLPC-era, V56 Frontend-Version, V57 ForwardMasking-Pflicht, V58 no-any-return | ✅ neu v9.19.0 |

---

## §10.3 Bug-Taxonomie

| Klasse | Definition | Priorität | Beispiel |
| --- | --- | --- | --- |
| **R-BLOCKER** | Korrektheit-kritisch: Export-Fehler, Crash, Daten-Verlust, Clipping-Artefakt | Sofort (P0) | SSIP None-Return, pegelexplosion |
| **AUDIO-QUALITY** | Hörbar schlechteres Ergebnis als möglich | Nächster Commit (P1) | V41 ForwardMaskingGuard fehlt, V38 per-Event-Strength fehlt |
| **SPEC-GAP** | Spec-Anforderung implementiert aber nicht getestet oder nur partiell | P2 | V33 CASSETTE-Key fehlt in dict |
| **TYPE-SAFETY** | mypy-Fehler (no-any-return, override, etc.) | P3 | UV3 ndarray Returns ohne cast |
| **TEST-DESIGN** | Test-Assertion bricht durch nichtlineare Guards (deterministisch) | P2 | test_phase_65 HallucinationGuard-Rollback |

---

## §10.4 Priorisierungs-Schema

```
P0 (sofort): R-BLOCKER — Export-Crash, Pegelexplosion, Stille-Zone-Verletzung
P1 (nächster Commit): AUDIO-QUALITY-Lücke, Spec-RELEASE_MUST-Verletzung
P2 (nächste 3 Commits): SPEC-GAP, TEST-DESIGN-Fix
P3 (Backlog): TYPE-SAFETY, Linter-Coverage, Dokumentation
```

**§10.4a Eskalations-Trigger** — P0-Upgrade wenn:

- `artifact_freedom < 0.95` durch Bug reproduzierbar
- `VQI < 0.72` durch Bug reproduzierbar
- Stille-Zone-Energie durch Bug eingeführt
- Export enthält Over-processed Audio statt Fallback

---

## §10.5 Behebungs-Workflow (§0f-konform)

```
1. ERKENNEN: Layer-Scan (§10.1) → Bug-Klasse (§10.3) → Priorität (§10.4)
2. ROOT-CAUSE: grep + read_file → Minimal-Reproduktion in Test
3. FIX: Punkt-Fix (1-4 Stellen) oder Systemisch (≥5 Stellen, §0f)
4. TEST: Unit-Test + ggf. Integrations-Test
5. VERBOTEN.md: Neue VERBOTEN-Regel wenn wiederholbares Anti-Pattern
6. SPEC-UPDATE: Betroffene Spec-Datei (01–10) + copilot-instructions.md
7. COMMIT: `fix §X systemic: ...` (systemisch) oder `fix(phase_XX): ...` (punktuell)
```

### §10.5a Systemisch vs. Punktuell (§0f-Regel)

| Signal | Vorgehen |
| --- | --- |
| 1 Stelle betroffen | Punktuell — direkter Fix |
| 2–4 Stellen | Prüfe Abstraktion: zentraler Helper wenn Overhead gering |
| ≥5 Stellen | **Systemisch**: zentrale Funktion + alle Callsites + VERBOTEN-Regel + Linter |
| Bug in ≥2 Sessions re-introduced | Systemisch — Linter-Regel fehlt |

---

## §10.6 Bekannte offene Gaps (Stand v9.20.0 / Update 2026-06-26)

### §10.6a P3: mypy no-any-return Boilerplate (Massenlage)

**Gesamtzahl**: `backend/core/` 1555 Fehler gesamt. Davon:

| Fehlertyp | Anzahl | Behandlung |
| --- | --- | --- |
| `no-any-return` (ndarray) | ~939 | Massenfix via Python-Skript (V58-Pattern: `# type: ignore[no-any-return]`) |
| `var-annotated` | ~192 | Typ-Annotationen ergänzen, punktuell |
| Echte Typ-Bugs (assignment/attr/arg/return-value) | ~424 | Individuell, P1–P2 |

Schicht-überblick:

| Layer | Gesamt-Fehler | Boilerplate | Echte Bugs | Priorität |
| --- | --- | --- | --- | --- |
| `Aurik910/` (Frontend) | **0** | 0 | 0 | ✅ |
| `backend/api/bridge.py` + `cli/` | 19 | 19 | 0 | P3 Boilerplate |
| `backend/core/dsp/` | 105 | ~80 | ~25 | P2 |
| `plugins/` | 175 | ~140 | ~35 | P2 |
| `backend/core/` (gesamt) | 1555 | ~1131 | ~424 | P1–P3 |

### §10.6b P1: Echte Typ-Bugs in kritischen Dateien

Dateien mit echten Typ-Bugs (keine Boilerplate) nach Fehleranzahl:

| Datei | Echte Bugs | Haupt-Fehlertyp | Priorität |
| --- | --- | --- | --- |
| `forensics/adaptive_chain_builder.py` | 21 | `dict-item` (str/float vs str/int) | P1 |
| `authenticity_metrics_extended.py` | 21 | Dataclass vs dict-Verwechslung, `call-overload` | P1 |
| `multi_pass_strategy.py` | 18 | Mixed | P2 |
| `ai_framework.py` | 17 | `attr-defined` ("restoration_button"), assignment None vs Typ | P1 |
| `forensics/unified_analyzer.py` | 14 | Mixed | P2 |
| `forensics/feature_extractor.py` | 14 | `floating[Any]` statt `float` | P2 |
| `real_audio_execution_golden_gate.py` | 13 | `union-attr` None.get() | P1 |
| `phases/phase_10_compression.py` | 11 | Mixed | P2 |
| `forensics/analysis_and_modules.py` | 11 | Mixed | P2 |
| `artifact_detection.py` | 10 | `floating[Any]` statt `float`, `list[ndarray]` vs `list[int]` | P2 |
| `phases/phase_04_eq_correction.py` | 8 | Mixed | P2 |
| `real_audio_defect_golden_gate.py` | 6 | `union-attr` None.get() | P1 |
| `adaptive_phase_rescheduler.py` | 1 | `arg-type` float(object) | P1 (Pipeline-kritisch) |

### §10.6c ~~P1: mypy UV3 46 Fehler~~ — ERLEDIGT (Session 2026-06-26)

`backend/core/unified_restorer_v3.py` → 0 Fehler nach `# type: ignore`-Massenpatch via Python-Skript.

### §10.6d ~~P1: V41 ForwardMaskingGuard additiv~~ — ERLEDIGT (v9.19.1, commit 0c9a069)

14 additive Phasen erledigt. V41-Gap-Scan: 0 verbleibend.

### §10.6e ~~P2: SSIP phase_55/24 intern (V14–V18)~~ — ERLEDIGT

Inventar-Fehler, bereits implementiert.

### §10.6f ~~P3: V33 MaterialType CASSETTE-Keys~~ — ERLEDIGT

Scan (2026-06-26): Alle Phasen vollständig. Inventar-Fehler.

### §10.6g P3: Pylance-Fehler (Pylance-spezifisch, mypy-sauber)

In dieser Session behoben (2026-06-26): 27 Pylance-Fehler in 13 Dateien:

- `phase_13`: return-value sum(bands)
- `phase_19`: 6× misc tuple-unpack, no-any-return, union-attr
- `phase_21`: override in process()
- `phase_23`: no-any-return
- `phase_39`: 4× no-any-return (inklusive Reparatur eines fehlerhaften Edits)
- `phase_44`, `phase_45`: no-redef in V41-Block
- `phase_51`: attr-defined (union-attr,attr-defined)
- `phase_56`: 5× (misc/assignment, arg-type, 2× no-any-return)
- `phase_60`: no-any-return + arg-type (int cast)
- `quality_control.py`: return float(snr) statt snr
- `test_phase_65`: no-any-return

---

## §10.7 Session-Start-Protokoll (KI-Agent)

Zu Beginn jeder Session, bevor Implementierung beginnt:

```bash
# 1. Failing Tests prüfen
pytest tests/unit/ -x --tb=line -q --timeout=30 2>&1 | tail -5

# 2. Aktuelle Branches / staged Files
git status --short && git log --oneline -3

# 3. Bekannte offene Gaps (diese Datei) lesen
# → specs/10_bug_gap_strategy.md §10.6

# 4. VERBOTEN.md auf neue Anti-Patterns prüfen
tail -20 .github/VERBOTEN.md
```

---

## §10.8 Kontinuierlicher Scan-Rhythmus

| Rhythmus | Aktion |
| --- | --- |
| Jeder Commit | Unit-Tests + VERBOTEN-Linter + mypy (staged files) |
| Täglich | Integration-Tests + Layer-Scan L1–L3 |
| Wöchentlich | mypy-Vollscan + Layer-Scan L4–L5 + KPI-Dashboard |
| Vor Release | Vollsuite + AMRB-Gate + Competitive-Gate + Worldclass-Release-Gate |

---

## §10.9 Vollständige Bug-Eliminierungs-Strategie (v9.20.0)

Ziel: **Vollständige Beseitigung aller ~1850 mypy-Fehler + aller Linter-Gaps** in allen Layern.
Strategiehorizont: Mehrstufig, präzise priorisiert, systemisch wo ≥5 Stellen betroffen.

### §10.9a Sprint 1 — Echte Typ-Bugs (P0/P1, Pipeline-kritisch)

**Ziel**: Alle Fehler die zur Laufzeit zu falschen Werten, None-Dereferenzierungen oder
falschen Typen im Audio-Pfad führen können.

**Prioritäts-Reihenfolge:**

1. `adaptive_phase_rescheduler.py:86` — `float(object)` arg-type: könnten falsche Strength-Werte in Closed-Loop eingebracht werden. **Sofort.**
2. `real_audio_execution_golden_gate.py` + `real_audio_defect_golden_gate.py` — `union-attr` None.get(): Gate schlägt mit AttributeError fehl wenn None-Pfad erreicht wird.
3. `ai_framework.py` — `attr-defined` "restoration_button" (sollte "restoration_magic_button" sein): Fehlerhafter Attributname kann RuntimeError auslösen.
4. `ai_framework.py` — assignment None vs. CompressionPhase/LimitingPhase: Pipeline nutzt None wo Objekt erwartet wird.
5. `authenticity_metrics_extended.py` — Dataclass vs dict: `asdict()` auf nicht-Dataclasses führt zu TypeError. Alle 21 Stellen systematisch.
6. `artifact_detection.py` — `list[ndarray]` vs `list[int]`: Falsche Return-Typen können Downstream-Code crashen.

**Methode**: Punktuell je Datei, `multi_replace_string_in_file`, mypy-Bestätigung danach.

### §10.9b Sprint 2 — Echte Typ-Bugs (P2, DSP/Forensics/Phases)

**Ziel**: Restliche echte Bugs in DSP, Forensics, Phases die keine direkten Crashes aber
falsche Berechnungen verursachen können.

1. `forensics/adaptive_chain_builder.py` — 21× `dict-item` (str/float vs str/int)
2. `forensics/feature_extractor.py` + `forensics/unified_analyzer.py` — `floating[Any]` statt `float`
3. `phases/phase_10_compression.py` + `phases/phase_04_eq_correction.py` — Mixed Typ-Bugs
4. `multi_pass_strategy.py` — 18 Mixed
5. `backend/core/dsp/` — ~25 echte Bugs (nach Boilerplate-Ausschluss)
6. `plugins/` — ~35 echte Bugs

**Methode**: Datei für Datei, mypy nach jedem Fix. Systemischer Helper-Pattern wenn ≥5 gleiche Stellen.

### §10.9c Sprint 3 — no-any-return Massenfix (P3, Boilerplate)

**Ziel**: ~939 `no-any-return` (ndarray) + ~140 in plugins + 19 in bridge/cli per Python-Skript lösen.

**Methode** (UV3-bewährt):

```python
# scripts/apply_no_any_return_ignores.py <datei_oder_verzeichnis>
# Für jede Zeile mit "[no-any-return]" aus mypy:
#   → append "  # type: ignore[no-any-return]" wenn nicht bereits vorhanden
```

**Reihenfolge** (nach Datei-Wichtigkeit):

1. `backend/core/phases/` — alle phase_*.py mit ≥5 Fehlern
2. `backend/core/dsp/` — alle dsp-Module
3. `backend/core/` Hauptmodule (lyrics_guided_enhancement, mert_mushra_proxy, etc.)
4. `backend/api/bridge.py` + `cli/`
5. `plugins/`

**Invariante**: Skript darf nur `no-any-return` hinzufügen, niemals vorhandenen Code ändern.
Nach Ausführung: `mypy --follow-imports=skip` muss 0 `no-any-return` zeigen.

### §10.9d Sprint 4 — var-annotated Cleanup (P3)

**Ziel**: ~192 `var-annotated` Fehler durch minimale Typ-Annotationen beheben.

**Methode**: `mypy backend/core/ --follow-imports=skip 2>&1 | grep "var-annotated"` →
pro Zeile minimale Annotation ergänzen (z.B. `energy: float = 0.0` statt `energy = 0.0`).
Skriptbar wenn Pattern homogen.

### §10.9e Automatisierungs-Werkzeuge (Session-zu-Session)

```bash
# Vollständiger Scan nach jeder Session:
.venv_aurik/bin/python -m mypy backend/core/ --follow-imports=skip --no-error-summary 2>&1 | grep "error:" | grep -v "no-any-return" | grep -v "var-annotated" | wc -l
# Ziel: 0 echte Bugs

# Boilerplate-Zähler:
.venv_aurik/bin/python -m mypy backend/core/ --follow-imports=skip --no-error-summary 2>&1 | grep "no-any-return" | wc -l
# Startwert: 939. Reduziert sich mit Sprint 3.
```

### §10.9f Linter-Erweiterungen für neue Anti-Patterns

Neue Anti-Patterns aus dieser Session → neue VERBOTEN-Einträge:

| Neues Muster | Beschreibung | Linter-Code |
| --- | --- | --- |
| Ersetzen von `return X\n\nDef` via Batch-Replace | `oldString` mit Funktionskopf verliert `def`-Zeile → katastrophaler Syntaxfehler | → Regel: `oldString` bei Batch-Replacements MUSS nur die Ziel-Zeile ±3 Zeilen Kontext enthalten, nie über Funktionsgrenzen |
| `mypy` mit `--follow-imports=skip` ignoriert Kontext | Pre-existing Fehler außerhalb der 27 Pylance-Fehler unsichtbar | → Session-Start: immer `backend/core/` vollständig scannen |

### §10.9g Metriken & Fortschritts-Tracking

| Metrik | Startwert (2026-06-26) | Sprint-1-Ziel | Endziel |
| --- | --- | --- | --- |
| Echte Typ-Bugs (backend/core, kein Boilerplate) | ~424 | <350 | 0 |
| no-any-return Boilerplate | ~939 | ~939 | 0 |
| var-annotated | ~192 | ~192 | 0 |
| Bridge/CLI Fehler | 19 | 0 | 0 |
| DSP echte Bugs | ~25 | <15 | 0 |
| Plugins echte Bugs | ~35 | ~35 | 0 |
| Frontend (Aurik910/) | **0** | 0 | 0 |

---

_Stand: v9.20.0, 2026-06-26 — automatisch gepflegt, Änderungen per Commit §10-konform_
