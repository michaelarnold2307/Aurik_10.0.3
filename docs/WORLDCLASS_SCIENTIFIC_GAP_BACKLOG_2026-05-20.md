# Worldclass Scientific Gap Backlog (Stand 2026-05-20)

Ziel: Wissenschaftliche Luecken identifizieren, die den Weltspitzen-Anspruch in Aurik direkt beeinflussen, und fuer jede Luecke ein belastbares Recherche- und Umsetzungsprotokoll definieren.

## Kurzfazit

Es gibt relevante Luecken mit hohem Hebel. Besonders kritisch sind:

- musik-spezifische Validierung der Gate-Schwellen (HPI/AFG/VQI)
- wissenschaftliche Herleitung der derzeit kalibrierten Grenzwerte
- robuste Evaluationsprotokolle fuer Restoration (nicht nur Speech- oder Codec-Kontext)

## Priorisierte Luecken (P1 zuerst)

| Prioritaet | Bereich | Aktueller Zustand | Luecke | Risiko fuer Weltspitze |
| --- | --- | --- | --- | --- |
| P1 | HPI/AFG/VQI Schwellen | Teilweise normativ (BS.1770/R128), teilweise kalibriert | Exakte Grenzwerte nicht durchgaengig primaerquellenbasiert | Falsch-positive Rollbacks oder zu laxe Freigaben |
| P1 | Musik-Restoration-Metrikvaliditaet | Mix aus VERSA/MERT/DNSMOS/Proxy | Domain-Shift: viele Metriken nicht fuer historische Musikrestauration kalibriert | Qualitätssteuerung trifft evtl. falsche Entscheidungen |
| P1 | Vocal Formant/Vibrato Grenzwerte | Starke vokalakustische Basis vorhanden | Exakte toleranzen in der Pipeline brauchen mehr direkte perzeptuelle Evidenz | Vokalnatuerlichkeit kann trotz guter Scores leiden |
| P2 | Transfer-Chain-Oracle (`chain_factor`) | Systemisch implementiert und getestet | Direkte Literaturabdeckung fuer konkrete Faktorformel noch duenn | Under/Over-processing bei komplexen Traegerketten |
| P2 | Artefaktgrenzen (Musical Noise, Pre-Echo, Stereo-Cancellation) | Gute technische Regeln vorhanden | Musik-spezifische, reproduzierbare Grenzvalidierung fehlt teilweise | Instabile Gate-Reaktionen je Material |
| P3 | Hallucination-Guard fuer generative Audio-Pfade | Technisch abgesichert | Einheitliche wissenschaftliche Benchmark fuer Audio-Halluzinationsdetektion fehlt | Versteckte Artefakte oder zu harte Ruecknahmen |

## Lueckenstatus-Update (Stand 2026-05-21)

Folgende P1-Luecken sind als geschlossen in den Vorgaben/Specs verankert:

- P1 HPI/AFG/VQI Schwellen: geschlossen durch
  `policy/scientific_threshold_evidence_registry.yaml` +
  `.github/specs/07_quality_and_tests.md` §8.6f + UV3-`threshold_evidence`
  mit wissenschaftlichen Quellenachsen (DOI/Norm).
- P1 Musik-Restoration-Metrikvaliditaet: geschlossen auf Governance-Ebene durch
  verpflichtende Quellenklassifikation je Gate-Schwelle (A/B/C) und
  Registry-basierte Nachweispflicht inklusive Revalidierungsdatum fuer Klasse C.
- P1 Vocal Formant/Vibrato Grenzwerte: geschlossen auf Evidenzebene durch
  explizite Quellenachsen im Registry-Eintrag `vqi_gate`
  (Miller 1992, Prame 2004, Jones 2022 + vokalakustische Basisliteratur).

Hinweis: P2/P3 bleiben als wissenschaftliche Vertiefungsachsen aktiv, sind aber
nicht mehr Blocker fuer die P1-Governance-Luecken der Vorgaben/Specs.

### Psychoakustik-Integrationsstatus (Stand 2026-05-21)

Folgende psychoakustischen Kernmassnahmen sind umgesetzt und normativ verankert:

- End-Gate `psychoacoustic_naturalness_gate` (Anti-klinisch)
- Adaptive Recovery vor finaler Degradation via sichere Referenz-Blends
- Phasenweise Anti-Klinik-Strength-Scalar (rein daempfend)
- Laufender Runtime-Delta-Loop (`_psycho_runtime_state`) aus Per-Phase-Goal-Delten
- UI-Sichtbarkeit inkl. Ampel-Status und Evidenzfelder

Konsolidierte Erkenntnisse/DoD:

- `docs/PSYCHOACOUSTIC_ENGINEERING_INSIGHTS_2026-05-21.md`

## Bereits verifizierte starke Quellenachsen

- Lautheit/True Peak: ITU-R BS.1770-5, EBU R128 (stark)
- Klassische NR-Theorie: Ephraim/Malah, IMCRA/OMLSA (stark)
- Formant/F0/Vokalphysik: Makhoul, Boersma, Titze, Sundberg (stark)

## Erste Recherche-Resultate (Live-Query, heute)

Die initialen API-Abfragen (Crossref) bestaetigen Kandidaten, zeigen aber auch: fuer mehrere Aurik-spezifische Fragen ist die Treffermenge verrauscht und erfordert kuratierte Nachrecherche.

### Relevante Treffer (Auszug)

- Pre-echo noise reduction in frequency-domain audio codecs (ICASSP 2017)
  DOI: 10.1109/ICASSP.2017.7952243
- Evaluation of short-time spectral attenuation techniques for the restoration of musical recordings (IEEE, 1995)
  DOI: 10.1109/89.365378
- The relationship between measured vibrato characteristics and perception in Western operatic singing (J Voice, 2004)
  DOI: 10.1016/j.jvoice.2003.09.003
- Perception of vibrato rate by professional singing voice teachers (JASA, 2022)
  DOI: 10.1121/10.0015518
- Formant frequency tuning in singing (1992)
  DOI: 10.1016/S0892-1997(05)80150-X

## Konkreter Forschungsplan (naechste 3 Arbeitspakete)

1. P1-Gates wissenschaftlich haerten

- Ziel: Fuer HPI/AFG/VQI-Schwellen eine Evidenzklasse vergeben (A=stark, B=mittel, C=kalibriert)
- Ergebnis: normativer Patch-Vorschlag mit Source-Tag je Schwellwert

2. Musik-Restoration-Evaluation konsolidieren

- Ziel: MUSHRA-/ABX-/Objective-Set fuer historische Musik mit Gesang als kanonisches Testprotokoll
- Ergebnis: neue Test-/Audit-Sektion inkl. Akzeptanzkriterien

3. Vocal-Grenzwerte (Formant/Vibrato) absichern

- Ziel: Perzeptuelle Toleranzbereiche spezifisch fuer Gesang im Restoration-Kontext
- Ergebnis: update-faehige Toleranzmatrix je Material/Era

## Umsetzungsregel fuer Quellenqualitaet

- Nur peer-reviewed, Normen oder AES/IEEE/JASA/J Voice-Quellen als Primaerbeleg
- Preprints nur als sekundaire Evidenz, bis peer-reviewte Bestaetigung vorliegt
- Jede neue Regel braucht: Quelle + Messprotokoll + Regressionstest

## Betroffene Aurik-Dokumente fuer den naechsten Patch

- .github/specs/02_pipeline_architecture.md
- .github/specs/09_global_calibration_matrix.md
- .github/instructions/pipeline.instructions.md
- docs/SCIENTIFIC_INVARIANT_TRACEABILITY_MATRIX.md

## Status

Freigabe fuer Recherche liegt vor. Naechster Schritt ist ein kuratierter, DOI-sauberer Source-Patch pro P1-Luecke mit konkretem Normtext-Delta.

Umsetzungsprotokoll fuer die naechste PR-Serie:

- `docs/WORLDCLASS_CLASS_C_REVALIDATION_PROTOCOL_2026-05-20.md`
- `docs/WORLDCLASS_SOTA_IMPLEMENTATION_MATRIX_2026-05-20.md`

## Aktivierungspaket 2026-05-21 (wissenschaftlich maximal, vokalfokussiert)

Normative Verankerung erfolgt in:

- `.github/specs/07_quality_and_tests.md` via `§8.6 Worldclass Hybrid-Engineer Protocol`

Damit wird der Weltspitzen-Anspruch von einer reinen Zielbeschreibung in ein
release-faehiges Mess- und Gate-System ueberfuehrt.

### AP-1: Human-Talent-Emulation-Vektor produktiv fuehren

- 12-dim Vektor (`hybrid_engineer_vector`) pro Run in Metadata persistieren
- Kontrakt: alle Schluessel vorhanden, normierte Werte, deterministische Berechnung
- Pflichtauswertung je Material/Era auf UAT-Matrix

### AP-2: WCS-Composite in Gates integrieren

- WCS als zusaetzliches End-Gate mit material-/modusbezogenen Minima
- Konfliktauflosung strikt nach Vocal-Supremacy-Hierarchie
- Kein Override fuer `artifact_freedom < 0.95`

### AP-3: Evidenzklassen A/B/C operationalisieren

- Jeder Gate-Schwellwert erhaelt `source_class`, `source_ref`, `validated_on`
- Klasse-C-Werte verpflichtend mit `revalidate_by`
- Build-Blocker fuer fehlende Evidenzmetadaten in neuen Schwellwerten

### AP-4: Weltspitzen-Testmatrix

- Normative Tests fuer HTEV-Contract, WCS-Gate, Evidence-Metadata
- Real-Audio-Gate auf Gesangsmaterial als Pflicht fuer Kernpatches
- Ergebnisaggregation je Materialklasse mit 5/95-Perzentil, nicht nur Mittelwert

### Definition of Ready fuer wissenschaftliche Patches

Ein Patch gilt erst dann als wissenschaftlich freigabefaehig, wenn alle Punkte vorliegen:

1. Quellenklassifikation A/B/C fuer jede neue Schwelle
2. Messprotokoll (Daten, Szenarien, Auswertung) reproduzierbar dokumentiert
3. Mindestens ein Regressionstest pro neue Invariante
4. Kein Konflikt mit Vocal-Supremacy und Artifact-Freedom-Veto

## Zuversichtsdämpfer fuer den Weltspitzen-Nachweis (Stand 2026-06-04)

Diese Punkte trueben die Zuversicht nicht wegen fehlender Architekturqualitaet,
sondern wegen noch unvollstaendiger externer Evidenz oder begrenzter Gate-Repraesentanz.

| Prioritaet | Zuversichtsdämpfer | Beobachtung im Repo | Warum das den Weltspitzen-Nachweis truebt | Schliesskriterium |
| --- | --- | --- | --- | --- |
| P1 | Kein vollstaendiger externer Head-to-Head-Nachweis als Dauer-Gate | Externe MUSHRA-/ABX-Protokolle sind vorbereitet, aber nicht als kontinuierlicher Pflicht-Release-Block fuer alle Kernaenderungen verankert | Aussage "qualitativ vor allen" bleibt ohne fortlaufende Vergleichsevidenz angreifbar | Jede Kernaenderung: externes Blindtest-Artefakt + Signifikanz + Effektstaerke als Pflicht-Gate |
| P1 | UAT-Gate G6 prueft nur einen Minimalfall | Umgestellt auf `tests/test_uat_acceptance_criteria.py::test_amrb_stratified_multi_scenario_gate` mit stratifiziertem Mehrszenario-Profil | Restrisiko sinkt deutlich; verbleibend ist die Laufzeit-/CI-Operabilitaet schwerer Gates | Heavy-Gate-Lauf regelmaessig gruener Nachweis fuer das neue Profil |
| P1 | Schwere Competitive-/AMRB-Gates laufen separat und teils manuell | Projekt- und Release-Dokumente weisen auf separate, langlaufende Gates hin | Risiko, dass lokale "gruen"-Laeufe die entscheidenden Konkurrenznachweise nicht enthalten | CI-Pflichtprofil mit verpflichtender Ausfuehrung beider Heavy-Gates vor Release-Tag |
| P2 | Proxy-Metrik-Domain-Shift bleibt trotz starker Guards ein Restrisiko | Backlog und Statusdokumente benennen weiterhin Metrikvaliditaet als sensible Achse | Gute interne Steuerung kann externe Hoerwahrnehmung in Randdomänen partiell verfehlen | Regelmaessige Re-Kalibrierung gegen neue Blindtest-Daten je Materialklasse |
| P2 | Langzeit-/Programmlaengen-Effekte sind in schnellen Gates unterreprasentiert | Mehrere Gate-Profile sind explizit runtime-begrenzt und deterministisch gehalten | Artefakte wie kumulative Ermuedung, Drift, Langform-Dynamik koennen spaet auftreten | Zusaetzliches Long-Form-Gate pro Release (mehrminuetige Real-Audio-Faelle) |
| P2 | Transfer-Chain-Randfaelle sind nicht durchgaengig als externe Vergleichsmatrix dokumentiert | Chain-Logik ist intern stark, externe Matrix mit Signifikanz ueber seltene Ketten bleibt ausbaufaehig | Weltspitzenanspruch braucht belastbare Aussagen gerade fuer seltene, schwierige Ketten | Externe Benchmark-Matrix inkl. seltener Ketten (z. B. shellac->tape->mp3) |
| P3 | Uneinheitliche Kommunikationslage in Alt-Reports | Historische Reports enthalten teils sehr starke Wettbewerbsbehauptungen ohne direkten Signifikanzblock | Erhoeht Reputationsrisiko und erschwert auditierbare Nachweisfuehrung | Alt-Reports mit Evidenzstatus taggen (`snapshot`, `claim-level`, `validated-by`) |

### Harte Priorisierung fuer den naechsten Weltspitzen-Schritt

1. P1-Luecken zuerst schliessen: externer Head-to-Head-Pflichtnachweis + G6-Ausbau + Heavy-Gate-Releasepflicht.
2. Danach P2: Long-Form- und Transfer-Chain-Randfall-Evidenz systematisch erweitern.
3. P3 parallel bereinigen: Claim-Hygiene in historischen Reports fuer klare Auditierbarkeit.
