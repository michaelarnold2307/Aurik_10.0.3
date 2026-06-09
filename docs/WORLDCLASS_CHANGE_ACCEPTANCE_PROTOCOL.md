# Worldclass Change Acceptance Protocol

Ziel: Nur Massnahmen mit nachweisbarem Hoergewinn, Spec-Konformitaet und
stabiler Testbarkeit duerfen in Aurik dauerhaft verbleiben.

## 1. Aufnahmefilter (hart)

Eine Aenderung wird nur aufgenommen, wenn alle vier Ebenen konsistent sind:

1. Vorgabe: klarer Zweck, betroffene musikalische Ziele, Nicht-Ziele.
2. Spec: normative Regel (oder neue Regel-ID) mit messbaren Akzeptanzkriterien.
3. Code: minimale, rueckverfolgbare Implementierung am kanonischen Pfad.
4. Tests: reproduzierbare Regressionstests + Gate-Abdeckung.

Fehlt eine Ebene, wird nicht gemerged.

## 2. Verbindlicher Ablauf pro Massnahme

1. Problemdefinition (hoerbar): Defektklasse, Hoerfolge, Risiko bei Nicht-Fix.
2. Spec-Abgleich: existierende Regel referenzieren oder neue Regel ergaenzen.
3. Implementierung: kleinste wirksame Aenderung, keine Parallelpfade.
4. Test-Haertung: mindestens
   - ein reproduzierender Bug-Test,
   - ein Drift-Guard (Kontrakt-Sync),
   - ein Integrations- oder Normative-Nachweis.
5. Gate-Sequenz (Pflicht): fokussierte Unit-Tests, Integration/Normative Core, Heavy-Gates (AMRB, Competitive) als gueltige, abgeschlossene Runs und Vollsuite stabil (chunked).
6. Retention-Entscheid: behalten nur bei durchgaengig gruener Gate-Kette.

### 2.1 Release-Pflicht fuer Heavy-Gates (neu)

Vor Release-Tagging sind folgende Nachweise verpflichtend:

1. `tests/normative/test_amrb_ci_gate.py` muss im aktuellen Release-Branch mit Exit-Code 0 abgeschlossen sein.
2. `tests/normative/test_competitive_ci_gate.py` muss im aktuellen Release-Branch mit Exit-Code 0 abgeschlossen sein.
3. Beide Läufe muessen als Artefakte protokolliert sein (Zeitstempel, Commit-SHA, Kernmetriken, Pass/Fail).
4. Fehlende/abgebrochene/gekillede Heavy-Runs (`137`, `143`, Timeout ohne Abschluss) gelten als **nicht bestanden**.

## 3. Bewertung: Klasse-A-Aufnahme

Eine Massnahme ist Klasse-A nur wenn:

1. kein zentraler Gate-Rueckschritt (AMRB/Competitive/Normative),
2. kein neuer Drift zwischen Schluesseln, Schwellwerten oder Regelbezeichnern,
3. keine Verschlechterung in P0/P1-Zielen bei vokalrelevantem Material,
4. Runtime/Memory bleiben innerhalb der freigegebenen Profile,
5. Rueckbau ist eindeutig moeglich (kleine, isolierte Commits).

## 4. Pflichtmatrix fuer wechselseitigen Abgleich

Pro Aenderung muss die folgende Matrix ausgefuellt werden:

| Ebene | Artefakt | Nachweis |
| --- | --- | --- |
| Vorgabe | Regeltext / Intent | Ticket/Notiz + Zieldefinition |
| Spec | Datei + Abschnitt | Regel-ID + Akzeptanzkriterium |
| Code | Datei + Funktion | Diff + Begruendung |
| Tests | Testdatei + Testname | Gruener Lauf + reproduzierbarer Fail vorher |

## 5. Fast-Validation vs. Fidelity-Pfad

Damit Tests keine Klangdrifts verdecken:

1. Fidelity-relevante Tests muessen den echten Metrikpfad erzwingen.
2. Fast-Validation ist nur fuer breite CI-Durchlaeufe ohne Klang-Urteil erlaubt.
3. Referenzscore-/Delta-Tests duerfen nie ausschliesslich auf Proxy-Werten basieren.

## 6. Heavy-Gate-Betrieb (operativ)

1. AMRB/Competitive separat und seriell fahren.
2. Robustes Ressourcenprofil fuer Heavy-Gates verwenden.
3. Bei OOM/Timeout: erst isolieren, dann Ursache beheben, dann Gate erneut fahren.
4. Exit 143/137 zaehlt als ungueltiger Lauf, nicht als fachliches Ergebnis.

## 7. Merge-Checkliste (bindend)

Vor Merge muessen alle Punkte erfuellt sein:

1. Vierfach-Matrix vollstaendig.
2. Spec- und Code-Pfade konsistent, keine Alias-/Key-Drifts.
3. Alle neuen/angepassten Tests gruen.
4. Heavy-Gates mit gueltigem Ergebnis (kein Kill/kein abgebrochener Lauf).
5. Changelog-Eintrag mit Impact und Rollback-Hinweis.
6. Externes Head-to-Head-Evidence-Pack vorhanden (Blindtest + Statistik) fuer kernaendernde Audio-PRs.

## 7.1 Required Evidence Pack (neu)

Fuer kernaendernde Audio-Aenderungen (Defekterkennung, Defektbehebung, Gate-Logik,
Metrik-Gewichtung, Phase-Staerken) ist vor Merge verpflichtend:

1. Externes Blindtest-Artefakt (MUSHRA/ABX) mit dokumentiertem Protokoll.
2. Signifikanznachweis inkl. Effektstaerke und 95%-Konfidenzintervall.
3. Head-to-Head-Vergleich gegen mindestens eine externe Referenz.
4. Eindeutige Zuordnung zum Commit/PR (Artefaktpfad, SHA, Datum, verantwortliche Person).

## 8. Verbotene Muster

1. Testschwellen lockern ohne kausale Begruendung und Gegenbeweis.
2. Fast-Pfade als Argument fuer Klangqualitaet.
3. Parallelpfade neben den kanonischen Contracts.
4. Feature-Aufnahme ohne reproduzierenden Vorher/Nachher-Nachweis.

## 9. Empfohlene Gate-Kommandos (robust)

```bash
# Normative Core
"${workspaceFolder}/scripts/pytest_clean.sh" tests/integration tests/normative \
  -p no:xdist --run-heavy-tests --run-gui-tests \
  -m "not amrb and not competitive" \
  --override-ini="addopts=--strict-markers --import-mode=importlib" \
  --timeout=90 --tb=line -q --disable-warnings --no-header --maxfail=5

# AMRB
AURIK_MEM_GB=16 AURIK_SWAP_MB=4096 QT_QPA_PLATFORM=offscreen \
  "${workspaceFolder}/scripts/pytest_clean.sh" tests/normative/test_amrb_ci_gate.py \
  -p no:xdist --run-heavy-tests --run-gui-tests \
  --timeout=600 --tb=short -q --disable-warnings --no-header --maxfail=1

# Competitive
AURIK_MEM_GB=16 AURIK_SWAP_MB=4096 AURIK_COMPETITIVE_BENCHMARK_TIMEOUT_S=180 \
QT_QPA_PLATFORM=offscreen \
  "${workspaceFolder}/scripts/pytest_clean.sh" tests/normative/test_competitive_ci_gate.py \
  -p no:xdist --run-heavy-tests --run-gui-tests \
  --timeout=1200 --tb=short -q --disable-warnings --no-header --maxfail=1
```

Dieses Protokoll gilt als operative Ergaenzung zu den bestehenden Specs und
setzt den Release-Must-Anspruch auf Weltklasse-Niveau praktisch um.
