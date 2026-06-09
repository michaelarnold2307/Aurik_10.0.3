# Weltspitze-Roadmap: Songadaptive Gesamtbalance (Restoration + Studio 2026)

Stand: 2026-06-05
Ziel: Für stark unterschiedliche Songs in beiden Modi robuste Weltspitzen-Balance mit minimierten Seiteneffekten.

## Leitprinzip

Kein "alles gleichzeitig maximal", sondern ein robustes Pareto-Optimum mit harten Schutzregeln:

- Keine Kernziel-Regression über Guard-Schwellen.
- Bei Gleichstand gewinnt niedrigere Defizitsumme (global + mode-core).
- Jeder aggressive Schritt ist rollback-fähig.

## Phase 1 (Quick Wins, 1-2 Wochen)

### 1.1 Core-Goal-Guard in Goal-Repair (implementiert)

- Status: erledigt
- Ort: `denker/exzellenz_denker.py`
- Wirkung:

  - Mode-Core-Ziele explizit geschützt.
  - Kandidatenwahl bei gleichem Passcount über Defizitsumme statt Zufall/Passcount-only.

### 1.2 Exzellenz-Optimizer Konfliktlogik angleichen

- Status: umgesetzt (2026-06-05)
- Ort: `backend/core/excellence_optimizer.py`
- Aufgaben:

  - Logging-only Pareto-Konflikte in Entscheidungslogik überführt.
  - Core-Regressionen > Schwelle lösen aktiven Rollback aus.
  - `applied_steps` + strukturierte Telemetrie (`core_guard_triggered`, `core_guard_regressions`, `pareto_conflicts`) ergänzt.

### 1.3 Realrun-Delta-Pipeline stabilisieren

- Status: in Arbeit
- Ort: `scripts/` + `analysis_results/`
- Aufgaben:

  - Canonical compare-script mit nested-goals Support (`final_musical_goals.scores`) umgesetzt: `scripts/compare_goal_metrics.py`.
  - Einheitliche Ausgabe `metric|baseline|postpatch|delta` umgesetzt.
  - Live-Realruns für Coreguard-Deltas laufen noch (ausstehende Abschlusswerte).

  ### 1.4 Kombinierte Weltspitzenintegration (geplant + ungeplant)

  - Status: umgesetzt (2026-06-05)
  - Ort: `backend/core/unified_restorer_v3.py`, `tests/unit/test_unified_restorer_v3.py`
  - Inhalt:

    - End-Gate-Candidate-Ranking um zusaetzlichen `spatial_depth`-Harddrop-Guard verschaerft.
    - Waerme-priorisierte Alpha-Suche fuer `original_audio` eingefuehrt (violations-aware).
    - Neuer `waerme_focus_rescue`-Kandidat als konservative Low-Mid-Reinjektion eingebunden.
    - Stereo-Sicherheitskappe im Rescue-Pfad: max. seitlicher Abfall (`spatial_drop_db`) wird begrenzt.
    - Material-Causal-Reconciliation im End-Gate aktiviert: source-penalties nutzen
      `material_confidence` + `material_defect_consistency_*` fuer robuste Kandidatenwahl.
    - Telemetrie erweitert: `waerme_focus_rescue`, `waerme_focus_rescue_applied`,
      `candidate_ranking_best`, `candidate_ranking_before/after`.

  - Unit-Absicherung:

    - `test_40dze_waerme_focus_rescue_candidate_raises_warm_band_energy`
    - `test_40dzf_waerme_focus_rescue_candidate_keeps_spatial_drop_below_cap`
    - bestehende Ranking-/Alpha-Tests bleiben aktiv.

Akzeptanzkriterien Phase 1:

- `spatial_depth`-Abstürze durch Goal-Repair in Regression-Songs reduziert.
- Keine neuen P1/P2-Regressionsfunde in fokussierten Unit-Tests.
- End-Gate-Waerme-Rescue bleibt no-harm: kein unkontrollierter `spatial_depth`-Einbruch.

## Phase 2 (Mid-Term, 3-6 Wochen)

### 2.1 Segmentweise Local-Intent-Optimierung

- Problem: Ein globales Setting behandelt Verse/Refrain/Bridge gleich.
- Lösung:

  - Song in Szenenfenster teilen (dichte Stellen, Frisson, Pausen, Vocal-dominant).
  - Pro Segment eigenes Defizitprofil und begrenzte lokale Intervention.
- Umsetzungsschritt (2026-06-05, kleiner Scope):

  - Local-Intent-Guard für `authentizitaet` vs `spatial_depth` in `messe_und_repariere()` ergänzt.
  - Disproportionale Trade-offs werden verworfen (kleiner Auth-Gewinn rechtfertigt keinen größeren Raumtiefe-Verlust).
  - Unit-Test ergänzt: `test_local_intent_guard_rejects_unbalanced_auth_spatial_tradeoff`.
  - Lokaler End-Gate-Backoff für `spatial_depth`/`waerme` ergänzt: Akzeptanz nur wenn lokaler Defizitvektor sinkt und globale Guards erfüllt bleiben.
  - Unit-Test ergänzt: `test_local_rescue_improves_spatial_waerme_after_rejected_blends`.
- Seiteneffekt-Guard:

  - Segment-übergreifender Kontinuitätscheck (keine hörbaren Kanten).

### 2.2 Harmonic Budget Controller

- Problem: Brillanzgewinne können Wärme/Authentizität auffressen.
- Lösung:

  - Pro Song ein HF/Präsenz-Budget mit Zielbeitrag je Phase.
  - Budgetverbrauch in Telemetrie sichtbar.
- Seiteneffekt-Guard:

  - Budget-Hardcap + Auto-Backoff bei Core-Defizit-Anstieg.

### 2.3 Material-Causal Reconciliation

- Problem: Hybridfälle (digital Container + analoges Defektbild).
- Lösung:

  - Material-Posterior + Defekt-Kausalität zu gemeinsamem Prior zusammenführen.
  - Strategy-Chooser auf "Kette" statt Dateiendung.
- Seiteneffekt-Guard:

  - Unsicherheitsmodus: konservatives Profil erzwingen.

Akzeptanzkriterien Phase 2:

- In Hybridfällen weniger Fehlpfad-Aktivierungen.
- Brillanz/Wärme-Tradeoff im Median reduziert.

## Phase 3 (High Impact, 6-10 Wochen)

### 3.1 Dual-Reference Fidelity Controller

- Problem: Einzelreferenz führt in schweren Fällen zu Fehlsignalen.
- Lösung:

  - Input- und Best-Carrier-Checkpoint parallel bewerten.
  - Dynamische Gewichtung je Material/Restorability/Defektklasse.

### 3.2 Runtime-Adaptive Execution

- Problem: Hohe Laufzeiten trotz geringer Gewinnwahrscheinlichkeit.
- Lösung:

  - Cheap-first candidate ranking, teure Pfade nur bei erwartbarem Gain.
  - Früher Abbruch bei sinkendem Grenznutzen.

### 3.3 Global Policy Learner (safe)

- Problem: Pro-Song-Optimierung lernt zu wenig über Songfamilien.
- Lösung:

  - Nicht-invasive Policy-Memory über Cluster (`material/era/genre/defect-signature`).
  - Nur als Prior, nie als harter Override.

Akzeptanzkriterien Phase 3:

- Stabilere Gesamtbalance über heterogene Benchmark-Sets.
- Niedrigerer Rechenaufwand pro Qualitätsgewinn.

## Mess- und Sicherheitsrahmen (für alle Phasen)

Pflichtmetriken:

- Core: `natuerlichkeit`, `authentizitaet`, `timbre_authentizitaet`, `tonal_center`, `spatial_depth`, `transient_energie`
- Ergänzend: `brillanz`, `waerme`, `separation_fidelity`, `vqi`, `final_hpi`

Pflicht-Guards:

- Keine Core-Regression über festgelegte Drop-Schwellen.
- Bei Konflikt: Defizitsumme muss sinken oder Kandidat verwerfen.
- Rollback bei Artefakt-/Emotion-Arc-Verletzung.

## Nächstes Implementierungspaket (Start jetzt)

1. Waerme-Rescue von Blend-only auf zielgerichtete Defizitsteuerung je Segment erweitern (nur wenn Defizit nachweislich sinkt).
2. E2E-Realrun auf Referenzsong + Delta-Tabelle dokumentieren (Baseline vs letzter no-RT-Lauf).
3. Material-Causal-Reconciliation (digital container + analoges Defektbild) in den End-Gate-Prior integrieren.
