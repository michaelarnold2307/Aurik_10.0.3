# Aurik 9.x.x - Benutzerhandbuch (One-Button)

## Prinzip

Aurik arbeitet vollautonom. Es gibt genau eine Entscheidung pro Datei:

- `Restoration`
- `Studio 2026`

Keine manuellen Pflichtparameter, keine Nachkalibrierung, keine Mehrpass-Standardprozedur.

## Die zwei Modi

### Restoration

Ziel: Originalcharakter maximal erhalten, Defekte sicher reduzieren.

- Minimal-interventiv
- Material- und era-adaptiv
- Vokal-Schutz aktiv (u. a. VQI-Recovery-Logik)

### Studio 2026

Ziel: Moderne Zielaesthetik bei erhaltener musikalischer Integritaet.

- Erweiterte Enhancement-Kette
- Strenge Gates fuer Artefaktfreiheit und Musikalitaet

## Standard-Workflow

1. Audiodatei importieren.
2. Modus waehlen (`Restoration` oder `Studio 2026`).
3. Starten.
4. Ergebnisdatei in `output/` pruefen.

## Automatische Schutzmechanismen

- `artifact_freedom` als primaerer Veto-Faktor
- Material- und goal-adaptive Steuerung
- Export nur ueber `export_guard()` und Qualitaetspruefung
- Recovery-Kaskaden statt riskanter Ueberverarbeitung

## Was Aurik bewusst nicht verlangt

- Keine manuelle Defekt-Schwellenpflege als Standard
- Keine Pflicht zu Mehrfachdurchlaeufen
- Keine Cloud-Konten
- Keine Docker- oder Server-Bedienung fuer Endnutzer

## Ergebnis und Transparenz

Die Verarbeitung liefert technische und qualitative Metadaten, u. a.:

- verwendeter Modus
- relevante Gate-Entscheidungen
- Export-/Degradation-Status bei Grenzfaellen

## Hinweise fuer Sonderfaelle

Wenn ein Ergebnis als `recovered` oder `degraded` markiert wird, war ein Schutzgate aktiv.
Das ist beabsichtigt und dient der Vermeidung von Musikzerstoerung.

## FAQ

### Muss ich Parameter einstellen?

Nein. Der Releasepfad ist auf autonome Entscheidungen ausgelegt.

### Brauche ich Internet?

Nein. Nach Installation arbeitet Aurik offline.

### Kann ich mehr als zwei Kanaele verarbeiten?

Produktiv unterstuetzt sind Mono und Stereo.
