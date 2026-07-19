# Aurik 10 — VERBOTE (Normativer Katalog)

> **Status:** Normativ | **Version:** 10.0.8 | **Stand:** 13. Juli 2026
>
> Dieser Katalog definiert alle unverhandelbaren VERBOTE — Handlungen, die Aurik
> **niemals** ausführen darf. Jedes Verbot hat eine eindeutige ID (§V1, §V2 usw.).
>
> Ein Verstoß gegen ein VERBOT ist ein **Build-Fehler** und muss vom Code-Review
> als blocking abgelehnt werden.

---

## Kategorie A — Gesangsintegrität (§V1–§V4)

| ID | Verbot | Begründung / Spezifikation |
|----|--------|---------------------------|
| §V1 | **Gesangsverzerrung** | Kein Verzerren, Verschleifen, Robotisieren oder Vocoder-artiges Verfremden von Gesang. Phase 42 (Vocal Enhancement) arbeitet ausschließlich additiv. Formanten-Verschiebung > 5 % löst Rollback aus. |
| §V2 | **Ghost-Echo** | Kein hörbares Echo, Pre-Echo oder Phasing-Artefakt durch asymmetrische Fensterung, STFT-Überlappungsfehler oder L/R-Phasenverschiebung. STCG muss laufen. |
| §V3 | **Hard-Clamp auf Audio** | Kein `np.clip(audio, -1, 1)` ohne Soft-Knee-Übergang (6 dB). Harte Clips erzeugen hörbare Obertöne (Gibbs-Phänomen). |
| §V4 | **Truncation ohne Dither** | Integer-Quantisierung (16/24-bit) ohne vorheriges Dithering. Erzeugt Quantisierungsverzerrung → hörbar in leisen Passagen. |

---

## Kategorie B — CD-Rauschprofil (§V5, §V11–§V17)

| ID | Verbot | Begründung / Spezifikation |
|----|--------|---------------------------|
| §V5 | **Dither-Doppelung** | Zweimaliges Dithern ist verboten. Wenn das CD-Rauschprofil (§G8) bereits appliziert wurde, muss `apply_dither()` den bereits vorhandenen Rauschpegel erkennen und sich entsprechend anpassen. |
| §V11 | **Rauschprofil-Flächendeckung** | Das CD-Rauschprofil darf NICHT pauschal über den gesamten Song gelegt werden. Es wird nur dort appliziert, wo das menschliche Ohr es wahrnimmt (unterhalb der ERB-Maskierungsschwelle, §G15). |
| §V12 | **Stille-Verfälschung** | Digital black (absolute Stille) darf NICHT verrauscht werden. Nur Segmente mit Signalenergie erhalten das Profil (§G17). |
| §V13 | **Spektrale Verfärbung** | Das Rauschprofil darf den spektralen Charakter des Originals nicht verfärben. Es muss sich unterhalb der simultanen Maskierungsschwelle des Signals bewegen. |
| §V14 | **Modus-Ignoranz** | Das CD-Rauschprofil gilt für Restoration UND Studio 2026. Es ist verboten, es nur in einem Modus zu applizieren. |
| §V15 | **Nicht-deterministisches Rauschen** | Der Rauschgenerator MUSS reproduzierbar sein. Seed = SHA256 der ersten 4096 Samples des Signals. |
| §V16 | **Übersteuerndes Rauschen** | Der Rauschpegel darf −85 dBFS NIE überschreiten. CD-Noise-Floor ist −96 dBFS (16-bit theoretisch); mit Dither-Shaping maximal −90 dBFS in den höchsten Frequenzbändern. |
| §V17 | **Quellmaterial-Extraktion** | Es ist VERBOTEN, das Rauschen aus dem degradierten Quellmaterial zu extrahieren und wieder einzufügen. Das CD-Rauschprofil wird frisch generiert – Quellrauschen (Bandrauschen, Vinyl-Knistern, MP3-Artefakte) sind DEFEKTE und werden entfernt. |

---

## Kategorie C — Architektur-Integrität (§V6–§V10, §V18–§V20)

| ID | Verbot | Begründung / Spezifikation |
|----|--------|---------------------------|
| §V6 | **Silent-Failure** | ML→DSP-Fallbacks MÜSSEN mit `logger.warning()` protokolliert werden. Kein stilles Degradieren der Qualität. |
| §V7 | **Toter Guard-Code** | Ein deklarierter Guard-Counter, der nie inkrementiert wird, ist verboten. Der Guard greift nie → false safety. |
| §V8 | **Globaler Phasen-Zustand** | Phasen-Zustände (Circuit-Breaker, Caches, Session-Daten) dürfen NICHT zwischen verschiedenen Songs persistieren (§C3). |
| §V9 | **Workarounds** | Symptombehandlung statt Ursachenbehebung. Kein `if phase_id == "23": special_value` ohne zentrale Begründung. |
| §V10 | **Phasen-Individuelle Schwellwerte** | Schwellwerte pro Phase, die nicht von `global_scalar` oder der zentralen Decision Intelligence abgeleitet sind. |
| §V18 | **Bridge-Bypass** | UI-/Frontend-Code (Aurik10, CLI, GUI) darf `backend/core/` NICHT direkt importieren. Nur über `backend/api/bridge.py`. |
| §V19 | **Nicht-atomarer Export** | Direktes Überschreiben der Zieldatei ohne `.tmp → os.replace`. Bei Abbruch entsteht eine korrupte Datei. |
| §V20 | **True-Peak-Überschreitung** | Kein Export darf True-Peak > 0 dBTP enthalten. Auch nicht "nur 0.1 dB". ISP-Interpolation zählt. |

---

## Kategorie D — ML & Modellierung (§V21–§V24)

| ID | Verbot | Begründung / Spezifikation |
|----|--------|---------------------------|
| §V21 | **ML-Device-Fehlgriff** | `model.device` nach `.cpu()`/`.to()` auf Sub-Modulen ist unzuverlässig. Stattdessen: `next(model.parameters()).device`. |
| §V22 | **ML-Recovery-Signaturbruch** | Recovery-Pfad nach GPU-Fehler MUSS dieselbe API wie Hauptpfad verwenden (z.B. `model.generate_batch()`), nur mit reduzierten Steps. |
| §V23 | **Diffusionsmodell-Rauschen** | Diffusionsmodelle können charakteristisches Rauschen im Noise Floor hinterlassen. Dieses MUSS durch den Authenticity-Validator erkannt und als Artefakt markiert werden. |
| §V24 | **Falsche Test-Toleranzen** | `np.testing.assert_allclose` mit `rtol`, `atol`. NIE Toleranzen an NumPy-Mathefunktionen übergeben (`np.abs(x, rtol=1e-5)` ist FALSCH). |

---

## Zusammenfassung: Alle VERBOTE auf einen Blick

```
§V1   Gesangsverzerrung         §V13  Spektrale Verfärbung
§V2   Ghost-Echo                §V14  Modus-Ignoranz
§V3   Hard-Clamp                §V15  Nicht-deterministisches Rauschen
§V4   Truncation ohne Dither    §V16  Übersteuerndes Rauschen
§V5   Dither-Doppelung          §V17  Quellmaterial-Extraktion
§V6   Silent-Failure            §V18  Bridge-Bypass
§V7   Toter Guard-Code          §V19  Nicht-atomarer Export
§V8   Globaler Phasen-Zustand   §V20  True-Peak-Überschreitung
§V9   Workarounds               §V21  ML-Device-Fehlgriff
§V10  Phasen-Individuelle Werte §V22  ML-Recovery-Signaturbruch
§V11  Rauschprofil-Flächendeckung §V23 Diffusionsmodell-Rauschen
§V12  Stille-Verfälschung       §V24  Falsche Test-Toleranzen
§V13  Dither-Reduktion          §V25  Hartcodierte Schwellwerte
§V14  Unbegründeter Rauschfloor §V26  Diskrete Stützstellen
```

---

## Kategorie E — Kalibrierungs-Hoheit (§V25–§V28)

| ID | Verbot | Begründung / Spezifikation |
|----|--------|---------------------------|
| §V25 | **Hartcodierte Schwellwerte** | Es ist VERBOTEN, irgendeinen Schwellwert, Floor, Cap oder Blend-Faktor als numerische Konstante im Code zu hinterlegen, der nicht AUSSCHLIESSLICH aus Auriks Pre-Analysis-Messwerten (restorability_score, transfer_chain_depth, material_type, SNR, bandwidth, era_decade) abgeleitet ist. Jeder Schwellwert MUSS über die zentrale Kalibrierungs-Matrix bezogen werden. Ausnahme: Physikalische Konstanten (z.B. −60 dBFS für digital black). |
| §V26 | **Diskrete Stützstellen (Lookup-Tabellen)** | Es ist VERBOTEN, Kalibrierungswerte über diskrete `{key: value}`-Maps oder `if/elif`-Kaskaden mit festen Stützstellen (z.B. `{1:0.25, 2:0.35, 3:0.45}`) abzuleiten. Die Ableitung MUSS über eine kontinuierliche Funktion erfolgen, die jeden kontinuierlichen Eingabewert (z.B. restorability_score=73) auf einen kontinuierlichen Ausgabewert abbildet — ohne Sprünge an Bucket-Grenzen. |
| §V27 | **Kalibrierungs-Silo** | Es ist VERBOTEN, dass ein Modul (z.B. signal_flow_tracer, joint_calibrator, one_take_export) eigene, vom Rest der Pipeline isolierte Schwellwerte pflegt. ALLE Module MÜSSEN ihre Schwellwerte aus DEMSELBEN zentralen Kalibrierungs-Kontext beziehen. Ein `_NOVELTY_CRIT` im signal_flow_tracer, das nicht aus dem restoration_context stammt, ist ein Verstoß. |
| §V28 | **Unkalibrierter Default** | Es ist VERBOTEN, einen Default-Wert zu verwenden, der nicht als „letzte Rückfallebene nach fehlgeschlagener Kalibrierung" dokumentiert ist. Jeder Default MUSS mit einer `logger.warning("uncalibrated fallback: {name}={value}")`-Meldung versehen sein, damit unkalibrierte Pfade im Log sichtbar sind. |

---

## Änderungshistorie

| Version | Datum | Änderung |
|---------|-------|----------|
| 10.0.9 | 2026-07-19 | §V25–§V28: Kalibrierungs-Hoheit. Verbot hartcodierter Schwellwerte und diskreter Stützstellen. Kategorie E. |
| 10.0.4 | 2026-07-13 | Initiale Formalisierung §V1–§V15. |
