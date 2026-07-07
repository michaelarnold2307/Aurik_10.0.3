# Aurik 2026 Erkenntnisse (Pakete 2-10)

Stand: 2026-04-14

## Scope

- Umgesetzt: Pakete 2 bis 10
- Nicht im Scope: Punkt 1 (externe Hoer-Validierung), bewusst deaktiviert

## Ergebnislage

- Umsetzungsstatus: abgeschlossen fuer Pakete 2 bis 10
- Konsolidierter Release/Runtime-Status: final_ready=true, contradiction=false
- Daily Real-Audio-Gate: status=ready
- Letzter Daily-Snapshot: recommendation=GO, gates=7/7, R5-R12=8/8

## R11-Erkenntnisse

- Der urspruengliche Voll-Lauf zeigte einen isolierten R11-Befund bei sonst 29/30 Kriterien und 7/7 Gates.
- R11 prueft praktisch die P1/P2-Ziele natuerlichkeit, authentizitaet, tonal_center, timbre_authentizitaet und artikulation, nicht alle 14 Goals.
- Ein echter Codebefund im UV3-Umfeld wurde gefunden und korrigiert: Stereo-Audio wurde in spektralen Proxy-Helfern teilweise als erste Zeile statt als erster Kanal gelesen.
- Der Fix betraf zwei Stellen in backend/core/unified_restorer_v3.py: `_spectral_quality_score(...)` und den Tilt-Helferpfad; dort wurde `a[0]` bzw. `audio[0]` auf kanalorientiertes Slicing korrigiert.
- Ein spaeterer Re-Run mit 15/30 und NO-GO war fuer R11 nicht aussagekraeftig, weil die gemeinsame Restoration-Runtime-Fixture fuer R1-R15 insgesamt in einen ERROR-Zustand lief.
- Die reproduzierte Restore-Route zeigte massiven Swap-/ML-Druck, Fallback-Kaskaden und Performance-Ueberschreitungen; dadurch ist der letzte NO-GO-Lauf eher als Systemdruck-Artefakt denn als sauberer R11-Einzelbeweis zu werten.
- Separater Befund: G1 war im NO-GO-Report rot, lief isoliert jedoch gruen; das stuetzt die Einschaetzung, dass der problematische Voll-Lauf insgesamt kein sauberer Entscheidungs-Lauf war.
- Arbeitsstand: Der reale Codefehler ist behoben und lokal validiert; fuer die finale R11-Entscheidung braucht es einen frischen Lauf unter sauberem RAM-/Swap-Zustand.

## Kern-Erkenntnisse

1. Normative Konsistenz muss testbar erzwungen werden.
   Der Fix auf DefectScanner-Budget und der Sync-Test verhindern erneute Drift zwischen Slim-Core und Spec.

2. Release-Freigabe braucht eine einzige Wahrheitsquelle.
   Die Konsolidierung von release_report und runtime_spec_report beseitigt Ampel-Widersprueche.

3. Mode-Parsing darf nicht von einem einzigen Log-Format abhaengen.
   Robustes Pattern-Matching fuer restoration/studio2026/studio_2026 reduziert false negatives im Runtime-Check.

4. Material- und Transferkettenlogik braucht dedizierte Regressionstests.
   Der neue Gate-Testpfad fuer Mehrgenerationsketten schliesst die Luecke zwischen Spezifikation und CI-Abdeckung.

5. Fallback-Entscheidungen muessen deterministisch und transparent sein.
   Der Fallback-Quality-Floor ist jetzt separat deterministisch abgesichert.

6. UX-Propagation wird stabiler, wenn Gate-Daten standardisiert sind.
   Eine einheitliche quality_gate-Sicht in Bridge und UI reduziert Inkonsistenzen bei degraded/recovered-Darstellung.

7. Operativer Nutzen entsteht erst mit kontinuierlichem Trend-Reporting.
   Der Daily-Reporter liefert reproduzierbare Verlaufspunkte ueber UAT-Runs statt punktueller Einzelergebnisse.

## Technische Artefakte (neu/erweitert)

- docs/BEST_2026_EXECUTION_PLAN_30D.md
- docs/BEST_2026_ERKENNTNISSE.md
- audit/release_runtime_consistency.py
- audit/consolidated_release_status.json
- audit/daily_real_audio_gate.py
- audit/daily_real_audio_gate_status.json
- audit/daily_real_audio_gate_status.md
- backend/core/unified_restorer_v3.py
- backend/api/bridge.py
- Aurik10/ui/modern_window.py
- tests/normative/test_spec_performance_budget_sync.py
- tests/unit/test_runtime_spec_check.py
- tests/unit/test_release_runtime_consistency.py
- tests/normative/test_carrier_recovery_reference_model_contract.py
- tests/normative/test_stereo_no_regress_contract.py
- tests/normative/test_material_transfer_chain_gate_regression.py
- tests/unit/test_fallback_quality_floor_determinism.py
- tests/normative/test_experience_propagation.py
- tests/unit/test_daily_real_audio_gate.py

## Rest-Risiken (operativ)

- Daily-Gate ist vorhanden, aber seine Aussagequalitaet haengt von regelmaessig aktualisierten uat_results-Dateien ab.
- Punkt 1 (externe Hoer-Validierung) bleibt als bewusstes Restrisiko ausserhalb dieses Programms bestehen.
- R11 ist aktuell nur teilweise aufgeloest: der Achsenfehler ist gefixt, aber ein sauberer Voll-Lauf unter kontrolliertem Ressourcendruck steht noch aus.

## Empfohlener Betriebsrhythmus

1. Täglich oder pro relevanter Aenderung:
   - python audit/daily_real_audio_gate.py
2. Bei Governance-/Gate-Aenderungen:
   - konsolidierten Status pruefen in audit/consolidated_release_status.json
3. Vor Release-Entscheid:
   - latest recommendation + Gates + R5-R12 aus daily_real_audio_gate_status.json bestaetigen
