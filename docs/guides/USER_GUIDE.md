# Aurik 10.0.8 — Benutzerhandbuch

> **Version:** 10.0.8 | **Stand:** 13. Juli 2026 | **Sprache:** Deutsch

---

## 📑 Inhaltsverzeichnis

- [1. Was ist Aurik?](#1-was-ist-aurik)
- [2. Die zwei Modi](#2-die-zwei-modi)
  - [2.1 Restaurierung](#21-restaurierung)
  - [2.2 Studio 2026](#22-studio-2026)
- [3. Standard-Workflow](#3-standard-workflow)
  - [3.1 Datei importieren](#31-datei-importieren)
  - [3.2 Modus wählen](#32-modus-wählen)
  - [3.3 Verarbeitung starten](#33-verarbeitung-starten)
  - [3.4 Ergebnis prüfen](#34-ergebnis-prüfen)
- [4. Automatische Schutzmechanismen](#4-automatische-schutzmechanismen)
- [5. CD-Rauschprofil](#5-cd-rauschprofil)
- [6. Qualitätssicherung](#6-qualitätssicherung)
- [7. Export](#7-export)
- [8. Ergebnis und Transparenz](#8-ergebnis-und-transparenz)
- [9. Hinweise für Sonderfälle](#9-hinweise-für-sonderfälle)
- [10. FAQ](#10-faq)
- [11. Technische Referenz](#11-technische-referenz)

---

## 1. Was ist Aurik?

Aurik ist ein **intelligentes, vollautonomes Musik-Restaurierungssystem**.
Es erkennt selbstständig, welche Schäden eine alte Tonaufnahme hat,
und repariert sie — ohne dass der Benutzer Parameter einstellen muss.

Stell dir vor, du findest auf dem Dachboden eine alte Kiste mit Tonbändern.
Die Musik ist großartig, aber die Bänder rauschen, jaulen, haben Aussetzer
und dumpfe Höhen. Aurik hört sich den Song an, findet alle Probleme,
und repariert sie einzeln — so, dass die Musik am Ende klingt wie neu.

**Aurik arbeitet vollständig offline.** Kein Internet. Keine Cloud.
Nach der Installation läuft alles auf deinem Rechner.

---

## 2. Die zwei Modi

Aurik hat genau zwei Modi. Du wählst beim Import aus, was du erreichen willst:

### 2.1 Restaurierung

> *„So klingt das Original — nur ohne die Schäden."*

- **Bewahrt die Authentizität** der Aufnahme
- Entfernt Rauschen, Knistern, Knacksen, Gleichlauf-Schwankungen
- Stellt fehlende Frequenzen wieder her — aber nur, was physikalisch da war
- Erhält Atemgeräusche, Raumklang und den analogen Charakter
- **Original-Lautstärke bleibt erhalten**
- Fügt **CD-charakteristisches Rauschprofil** hinzu (nur wo hörbar)
- Geeignet für: **Tonbänder, Schallplatten, alte Kassetten, historische Aufnahmen**

### 2.2 Studio 2026

> *„Die Musik klingt, als wäre sie heute im Highend-Studio produziert."*

- **Moderner, brillanter Klang** mit kristallklaren Höhen
- Straffere Dynamik, wettbewerbsfähige Lautheit (−14 LUFS Streaming-Standard)
- **Breiteres Stereobild** für modernes Raumgefühl
- Sanfte Multiband-Kompression für druckvollen Sound
- Spektrale Reparatur für digitale Artefakte (MP3, Streaming)
- Entfernt störenden Raumhall für klare, direkte Stimmwiedergabe
- Ebenfalls mit **CD-charakteristischem Rauschprofil**
- Geeignet für: **Alles, was auf Spotify, YouTube oder Apple Music veröffentlicht werden soll**

---

## 3. Standard-Workflow

### 3.1 Datei importieren

1. Starte Aurik.
2. Klicke auf **„Datei öffnen"** oder ziehe eine Audiodatei in das Fenster.
3. Unterstützte Formate: **WAV, FLAC, MP3, AIFF, OGG, M4A**

### 3.2 Modus wählen

Nach dem Import erscheinen zwei große Buttons:

| Button | Modus | Wann? |
|--------|-------|-------|
| 🎵 **Restaurierung** | Authentizität bewahren | Alte Aufnahmen, Archivmaterial |
| 🎛 **Studio 2026** | Moderner Sound | Veröffentlichung auf Streaming-Plattformen |

Klicke auf den gewünschten Modus. **Das ist die einzige Entscheidung, die du treffen musst.**

### 3.3 Verarbeitung starten

Aurik beginnt sofort mit der Analyse und Verarbeitung:

```
🔍 Schritt 1/4: Fehleranalyse...
📋 Schritt 2/4: Phasen-Auswahl...
🔧 Schritt 3/4: Restaurierungspipeline...
📊 Schritt 4/4: Qualitätsbericht...
```

Die Verarbeitung läuft in **68 spezialisierten Phasen** — jede adressiert einen bestimmten
Defekttyp. Aurik entscheidet selbst, welche Phasen wie stark eingesetzt werden.

### 3.4 Ergebnis prüfen

Nach Abschluss siehst du das Ergebnis:

- ✅ **Verarbeitung abgeschlossen** — mit Qualitätsbewertung
- 💿 **CD-Rauschprofil** wurde angewendet
- 📊 **Qualitätsbericht** zeigt alle Scores (Harmonik, Transienten, Formanten, Artefakte)
- Die Datei liegt im `output/`-Ordner oder an dem von dir gewählten Speicherort

---

## 4. Automatische Schutzmechanismen

Aurik hat mehrere Schutzstufen, die **automatisch** eingreifen:

| Schutz | Was es tut |
|--------|-----------|
| **Artifact-Freedom-Gate** | Verhindert, dass die Restaurierung neue Störgeräusche erzeugt |
| **Vocal-No-Harm-Gate** | Schützt den Gesang vor Überbearbeitung |
| **Harmonic-Preservation-Guard** | Erhält die natürlichen Obertöne der Instrumente |
| **STCG (Stereo-Kohärenz)** | Verhindert Phasenverschiebungen zwischen linkem und rechtem Kanal |
| **Spectral-Tilt-Guard** | Stellt sicher, dass die Klangbalance (Bass/Mitten/Höhen) erhalten bleibt |
| **Passaggio-Schutz** | Reduziert Bearbeitung in den empfindlichen Übergangszonen der Stimme |

Wenn ein Schutz eingreift, wird das im Qualitätsbericht dokumentiert.
**Das ist kein Fehler — das ist Absicht.** Aurik opfert lieber ein bisschen Restaurierung,
als die Musik zu beschädigen.

---

## 5. CD-Rauschprofil

Ein besonderes Merkmal von Aurik: **Jede Restaurierung klingt am Ende wie eine CD.**

Nach der Reparatur aller Schäden fügt Aurik ein extrem leises, CD-charakteristisches
Rauschen hinzu. Dieses Rauschen ist so leise (−96 dB), dass du es nicht bewusst hörst —
aber dein Gehirn registriert es als „natürliche Stille".

Ohne dieses Rauschen würde die Musik in leisen Passagen „unheimlich still" klingen —
wie in einem schalldichten Raum. Mit dem CD-Rauschprofil klingt sie „richtig".

Das Rauschprofil wird **nur dort hinzugefügt, wo das Ohr es wahrnimmt** — in lauten
Passagen wird es von der Musik überdeckt und ist nicht vorhanden.

---

## 6. Qualitätssicherung

Nach jeder Restaurierung führt Aurik eine automatische Qualitätsprüfung durch:

| Metrik | Was sie misst |
|--------|--------------|
| **Harmonik-Erhaltung** | Sind die Obertöne der Instrumente noch intakt? |
| **Transienten-Erhaltung** | Sind die Anschläge (Schlagzeug, Klavier) noch knackig? |
| **Formanten-Erhaltung** | Klingt der Gesang noch wie der Sänger? |
| **Mikrodynamik** | Sind die feinen Lautstärkeschwankungen erhalten? |
| **Emotionaler Bogen** | Folgt die Spannungskurve noch dem Original? |
| **Artefakt-Freiheit** | Sind neue Störgeräusche entstanden? |

Jede Metrik liefert eine Note von 0–100. Der **Gesamtscore** fasst alles zusammen.
Aurik zeigt an, ob die Restaurierung **blindtest-tauglich** ist (Score ≥ 85).

---

## 7. Export

Nach der Verarbeitung wird die Datei automatisch exportiert:

- **Format:** WAV oder FLAC (verlustfrei)
- **Bittiefe:** 16 oder 24 Bit (konfigurierbar)
- **Abtastrate:** 48 kHz
- **Metadaten:** Enthalten Informationen über die durchgeführte Restaurierung

Der Export läuft über mehrere Stufen:

```
💿 CD-Rauschprofil → POW-r-Type-3-Dithering → Atomares Schreiben → Metadaten
```

---

## 8. Ergebnis und Transparenz

Die Verarbeitung liefert umfangreiche Informationen:

- Verwendeter Modus (Restaurierung / Studio 2026)
- Material-Typ (automatisch erkannt: Tonband, Vinyl, Kassette, etc.)
- Qualitäts-Scores (Harmonik, Transienten, Formanten, Artefakte)
- Ausgeführte Phasen (welche Reparaturen wurden durchgeführt)
- Gate-Entscheidungen (welche Schutzmechanismen haben eingegriffen)
- CD-Rauschprofil-Status

---

## 9. Hinweise für Sonderfälle

Wenn ein Ergebnis als `recovered` oder `degraded` markiert wird,
war ein Schutzgate aktiv. Das ist beabsichtigt und dient der
Vermeidung von Musikzerstörung.

- **Recovered:** Ein Schutz hat eingegriffen, die Restaurierung wurde
  mit reduzierter Intensität wiederholt. Das Ergebnis ist trotzdem gut.
- **Degraded:** Der ursprüngliche Zustand war zu schlecht für eine
  vollständige Restaurierung. Aurik hat das bestmögliche sichere
  Ergebnis exportiert.

---

## 10. FAQ

### Muss ich Parameter einstellen?

**Nein.** Aurik arbeitet vollautonom. Die einzige Entscheidung ist:
Restaurierung oder Studio 2026.

### Brauche ich Internet?

**Nein.** Nach der Installation arbeitet Aurik komplett offline.

### Kann ich mehr als zwei Kanäle verarbeiten?

Produktiv unterstützt sind **Mono und Stereo**. Surround-Formate
werden aktuell nicht unterstützt.

### Wie lange dauert eine Restaurierung?

Eine 5-Minuten-Aufnahme braucht etwa **3–5 Minuten** auf einem
modernen Rechner. Sehr lange Dateien (>10 Minuten) werden
speichereffizient in Blöcken verarbeitet.

### Kann ich das Ergebnis vor dem Export anhören?

**Ja.** Die Vorschau enthält bereits das CD-Rauschprofil —
sie klingt exakt wie der spätere Export.

### Werden meine Originaldateien verändert?

**Nein.** Aurik erstellt immer eine neue Datei. Das Original
bleibt unverändert.

---

## 11. Technische Referenz

| Kenngröße | Wert |
|-----------|------|
| Interne Abtastrate | 48.000 Hz |
| Pipeline-Phasen | 68 |
| Erkannte Defekttypen | 62 |
| Material-Typen | 16 |
| Qualitätsmetriken | 14 |
| CD-Rauschpegel (16-bit) | −96 dBFS |
| CD-Rauschpegel (24-bit) | −114 dBFS |
| Streaming-Lautheit (Studio 2026) | −14 LUFS |
| Archiv-Lautheit (Restaurierung) | −23 LUFS |

---

*Aurik 10.0.8 — Juli 2026*
