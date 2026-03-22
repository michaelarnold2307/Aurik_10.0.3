"""
core/defect_phase_mapper.py
Defect-to-Phase Mapper (DPM)
==============================

Ordnet jeden der 20 DefectType-Werte den jeweils relevanten Phasen zu
und konfiguriert den ProcessingConfig-Parameter-Satz präzise für den
Primary-Defekt.

Aufgaben:
  A) Semantisch: Welche Phase(n) sind für diesen Defekt zuständig?
     → Gibt geordnete Liste von phase_id-Strings zurück
     → Priorität: primary > secondary (wichtig für zukünftige Phasen-Selektion)

  B) Aktionär: Wie soll ProcessingConfig für diesen Defekt gesetzt werden?
     → Gibt einen Dict mit Config-Delta zurück (nur geänderte Felder)
     → Wird von ARE._build_specialist_variant() verwendet

Bekannte Phase-IDs (aus core/phases/):
  phase_01_click_removal        — Multi-Scale Click-Detektion
  phase_02_hum_removal          — Netzbrumm-Entfernung (50/60 Hz + Harmonische)
  phase_03_denoise              — Breitband-Rauschunterdrückung
  phase_04_eq_correction        — Tonal-Korrektur / EQ
  phase_05_rumble_filter        — Tieffrequenz-Rumpel / Trittschall
  phase_06_frequency_restoration— Hochfrequenz-Restauration
  phase_07_harmonic_restoration — Harmonische Wiederherstellung
  phase_08_transient_preservation— Attack-Schutz / Transientenerhalt
  phase_09_crackle_removal      — Knistergeräusch-Entfernung
  phase_12_wow_flutter_fix      — Wow/Flutter-Korrektur (Bandschwankung)
  phase_13_stereo_enhancement   — Stereo-Verbesserung
  phase_14_phase_correction     — Phasenfehler-Korrektur
  phase_15_stereo_balance       — L/R-Balance-Ausgleich
  phase_18_noise_gate           — Rauschtor (Stille-Reinigung)
  phase_23_spectral_repair      — Spektrale Reparatur (Gaps, Dropouts)
  phase_24_dropout_repair       — Aussetzer-Reparatur via Interpolation
  phase_25_azimuth_correction   — Azimuth-/Phasen-Fehler (Bandmaschine)
  phase_26_dynamic_range_expansion— DRE (Compander, um Kompression rückgängig)
  phase_27_click_pop_removal    — Knacker/Pop-Entfernung (komplementär zu 01)
  phase_28_surface_noise_profiling— Vinyl/Shellac Oberflächen-Profiling
  phase_29_tape_hiss_reduction  — Bandrauschen-Reduktion
  phase_30_dc_offset_removal    — DC-Versatz-Entfernung
  phase_31_speed_pitch_correction— Tonhöhen/-geschwindigkeits-Korrektur
  phase_33_stereo_width_limiter — Stereobreiten-Begrenzung
  phase_34_mid_side_processing  — Mid/Side-Verarbeitung für Phasenfehler
  phase_50_spectral_repair      — Erweiterte spektrale Reparatur (Phase 2)

Author: Aurik Development Team
Version: 1.0.0
Date: 2026-02-17
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import threading

from backend.core.defect_scanner import DefectType

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Datenstruktur: PhaseAssignment
# ---------------------------------------------------------------------------


@dataclass
class PhaseAssignment:
    """Zuordnung eines DefectType zu Phase-IDs und Config-Parametern."""

    defect_type: DefectType
    """Defekt-Typ den diese Zuordnung abdeckt."""

    primary_phases: list[str]
    """Phase-IDs, die diesen Defekt direkt behandeln (höchste Priorität)."""

    secondary_phases: list[str]
    """Ergänzende Phasen (Nutzen wenn primary nicht ausreicht)."""

    description: str
    """Menschenlesbare Beschreibung der Strategie."""

    config_delta: dict[str, object]
    """
    ProcessingConfig-Felder die für diesen Defekt optimal gesetzt werden.
    Enthält NUR die Felder die vom Default abweichen.
    Stärke ist auf severity=1.0 kalibriert; wird beim Anwenden skaliert.
    """

    def apply_to_config(
        self,
        config: object,
        severity: float = 1.0,
        mode_factor: float = 1.0,
        material_factor: float = 1.0,
    ) -> None:
        """
        Wendet config_delta auf ein ProcessingConfig-Objekt an.

        Args:
            config: ProcessingConfig-Instanz (wird in-place modifiziert)
            severity: Defekt-Severity [0–1]; skaliert Stärke-Parameter
            mode_factor: Zusätzlicher Modus-Faktor (z.B. 0.8 für RESTORATION)
            material_factor: Material-Anpassungsfaktor aus _MATERIAL_PHASE_FACTORS
                (Werte < 1.0 = Charakter-Schutz, Werte > 1.0 werden auf 1.0 geklammert).
        """
        effective = max(0.0, min(1.0, severity * mode_factor * material_factor))
        for k, v in self.config_delta.items():
            if not hasattr(config, k):
                logger.warning("ProcessingConfig hat kein Feld %r — übersprungen.", k)
                continue
            if isinstance(v, float):
                # Float-Parameter: linear skalieren
                scaled = float(v) * effective
                # Klemmen auf [0.0, 1.0] für Stärke-Felder
                if k.endswith(("_strength", "_sensitivity", "_factor")):
                    scaled = max(0.0, min(1.0, scaled))
                setattr(config, k, scaled)
            elif isinstance(v, bool):
                # Bool-Flags: ab severity ≥ 0.3 aktivieren
                setattr(config, k, True if effective >= 0.3 else v)
            elif isinstance(v, int):
                setattr(config, k, v)
            else:
                setattr(config, k, v)


# ---------------------------------------------------------------------------
# Vollständige Mapping-Tabelle
# ---------------------------------------------------------------------------

_PHASE_MAP: dict[DefectType, PhaseAssignment] = {
    # ------------------------------------------------------------------
    # CLICKS — Vinyl/Shellac-Knackser, Klicks, Nadel-Impulse
    # ------------------------------------------------------------------
    DefectType.CLICKS: PhaseAssignment(
        defect_type=DefectType.CLICKS,
        primary_phases=[
            "phase_01_click_removal",  # Multi-Scale Adaptive Click Detection
            "phase_27_click_pop_removal",  # Click/Pop mit erweitertem Kontext
        ],
        secondary_phases=[
            "phase_08_transient_preservation",  # Schützt Musik-Transienten
            "phase_30_dc_offset_removal",  # Beseitigt DC von Klick-Resten
        ],
        description=(
            "Klickentfernung via statistischer Detektion + Interpolation. "
            "Bewahrt Musik-Transienten durch parallele Transientenanalyse."
        ),
        config_delta={
            "click_removal_sensitivity": 0.90,  # Hoch: viele Klicks treffen
            "denoise_strength": 0.0,  # Kein Rauschen entfernen (nur Klicks)
            "declip_strength": 0.30,  # Leicht: Klick-Spitzen kappen
            "preserve_analog_character": True,  # Oberflächen-Charakter bewahren
            "enable_spectral_repair": True,  # Lücken nach Click-Removal schließen
            "spectral_repair_strength": 0.60,
        },
    ),
    # ------------------------------------------------------------------
    # CRACKLE — kontinuierliches Knistern (Vinyl, Shellac)
    # ------------------------------------------------------------------
    DefectType.CRACKLE: PhaseAssignment(
        defect_type=DefectType.CRACKLE,
        primary_phases=[
            "phase_09_crackle_removal",  # Crackle-Klassifikation + Unterdrückung
            "phase_28_surface_noise_profiling",  # Oberflächen-Lärm-Profil
        ],
        secondary_phases=[
            "phase_18_noise_gate",  # Stille zwischen Knistern bereinigen
            "phase_03_denoise",  # Rest-Knisterpegel absenken
        ],
        description=(
            "Vinyl/Shellac-Knistern-Entfernung über Crackle-Klassifikator. "
            "Unterscheidet Crackle von Perkussions-Transienten."
        ),
        config_delta={
            "click_removal_sensitivity": 0.60,  # Mittel: Crackle-Events
            "denoise_strength": 0.25,  # Leichtes Rauschen nach Crackle-Profiling
            "declip_strength": 0.20,
            "preserve_analog_character": True,
        },
    ),
    # ------------------------------------------------------------------
    # HUM — Netzbrumm (50/60 Hz) + Harmonische
    # ------------------------------------------------------------------
    DefectType.HUM: PhaseAssignment(
        defect_type=DefectType.HUM,
        primary_phases=[
            "phase_02_hum_removal",  # Adaptive Notch-Filter 50/60 Hz + OK
        ],
        secondary_phases=[
            "phase_04_eq_correction",  # Breitband-EQ nach Brumm-Entfernung
            "phase_05_rumble_filter",  # Tieffrequenz-Begleitgeräusch
        ],
        description=(
            "Netzbrumm-Entfernung (50/60 Hz + Harmonische bis 1000 Hz) "
            "via adaptivem Notchfilter ohne Musiksignal zu beschädigen."
        ),
        config_delta={
            "denoise_strength": 0.40,
            "click_removal_sensitivity": 0.0,  # Klicks sind kein HUM-Problem
            "low_freq_rolloff_hz": 20,  # DC-Versatz / Sub-Hz-Rumpel mitentfernen
            "declip_strength": 0.0,
        },
    ),
    # ------------------------------------------------------------------
    # WOW/FLUTTER — Bandschwankung, Leierkassetten-Effekt
    # ------------------------------------------------------------------
    DefectType.WOW: PhaseAssignment(
        defect_type=DefectType.WOW,
        primary_phases=[
            "phase_12_wow_flutter_fix",  # Pitch-Detect + Time-Warp
            "phase_31_speed_pitch_correction",  # Grobe Geschwindigkeitsfehler
        ],
        secondary_phases=[
            "phase_25_azimuth_correction",  # Azimuth-Abweichung von Bandmaschinen
        ],
        description=(
            "Wow/Flutter-Korrektur via PSOLA- oder Phase-Vocoder-Time-Warping. "
            "Detektiert Tonhöhenschwankungen < 6 Hz (Wow) und 6–100 Hz (Flutter)."
        ),
        config_delta={
            "denoise_strength": 0.15,  # Minimal: Rauschen ist Sekundärproblem
            "click_removal_sensitivity": 0.20,
            "declip_strength": 0.0,
            "preserve_analog_character": True,
        },
    ),
    DefectType.FLUTTER: PhaseAssignment(
        defect_type=DefectType.FLUTTER,
        primary_phases=[
            "phase_12_wow_flutter_fix",  # Pitch-Detect + Time-Warp
            "phase_31_speed_pitch_correction",  # Grobe Geschwindigkeitsfehler
        ],
        secondary_phases=[
            "phase_25_azimuth_correction",  # Bandmaschinen-Nebeneffekte
        ],
        description=(
            "Flutter-Korrektur via Wow/Flutter-Spezialpfad mit Fokus auf schnellere "
            "Tonhöhenschwankungen und mechanische Laufwerksinstabilität."
        ),
        config_delta={
            "denoise_strength": 0.10,
            "click_removal_sensitivity": 0.15,
            "declip_strength": 0.0,
            "preserve_analog_character": True,
        },
    ),
    # ------------------------------------------------------------------
    # STEREO_IMBALANCE — L/R-Pegel, Kanaldefekte, Mono-Probleme
    # ------------------------------------------------------------------
    DefectType.STEREO_IMBALANCE: PhaseAssignment(
        defect_type=DefectType.STEREO_IMBALANCE,
        primary_phases=[
            "phase_15_stereo_balance",  # L/R-Balance-Korrektur
            "phase_33_stereo_width_limiter",  # Kanal-Extrema begrenzen
        ],
        secondary_phases=[
            "phase_14_phase_correction",  # Phasenfehler können Balance imitieren
            "phase_34_mid_side_processing",  # M/S für präzise Balance-Kontrolle
        ],
        description=(
            "L/R-Kanalbalance-Ausgleich und Stereobreiten-Normierung. "
            "Behandelt auch Mono-Summen-Probleme und Phasen-Differenzen."
        ),
        config_delta={
            "stereo_width_factor": 1.0,  # Korrigiert auf neutrale Breite
            "denoise_strength": 0.10,
            "click_removal_sensitivity": 0.20,
            "declip_strength": 0.0,
        },
    ),
    # ------------------------------------------------------------------
    # DIGITAL_ARTIFACTS — MP3/AAC-Blockartefakte, Codec-Rauschen
    # ------------------------------------------------------------------
    DefectType.DIGITAL_ARTIFACTS: PhaseAssignment(
        defect_type=DefectType.DIGITAL_ARTIFACTS,
        primary_phases=[
            "phase_23_spectral_repair",  # Spektrale Lücken füllen
            "phase_50_spectral_repair",  # Erweiterte Reparatur (Phase 2)
        ],
        secondary_phases=[
            "phase_07_harmonic_restoration",  # Verlorene Obertöne wiederherstellen
            "phase_06_frequency_restoration",  # Hochfrequenz-Ausdünnung korrigieren
        ],
        description=(
            "MP3/AAC/Streaming-Codec-Artefakt-Entfernung via spektraler Interpolation "
            "und harmonischer Rekonstruktion. Preibischner-Algorithmus-basiert."
        ),
        config_delta={
            "enable_spectral_repair": True,
            "spectral_repair_strength": 0.85,
            "spectral_repair_hole_threshold_db": -45.0,
            "denoise_strength": 0.20,
            "click_removal_sensitivity": 0.10,
            "declip_strength": 0.0,
            "high_freq_boost_db": 1.5,  # Leicht: Codec schneidet HF ab
        },
    ),
    # ------------------------------------------------------------------
    # LOW_FREQ_RUMBLE — Trittschall, HVAC, Motorschleifen < 80 Hz
    # ------------------------------------------------------------------
    DefectType.LOW_FREQ_RUMBLE: PhaseAssignment(
        defect_type=DefectType.LOW_FREQ_RUMBLE,
        primary_phases=[
            "phase_05_rumble_filter",  # High-Pass + Resonanz-Dämpfung
        ],
        secondary_phases=[
            "phase_02_hum_removal",  # Begleitet oft Rumpel
            "phase_30_dc_offset_removal",  # DC-Komponente mitentfernen
        ],
        description=(
            "Sub-Bass-Rumpel-Entfernung via Butterworth High-Pass + adaptive "
            "Resonanz-Dämpfung ohne Bassinteresse zu beschädigen."
        ),
        config_delta={
            "low_freq_rolloff_hz": 40,  # Aggressiver HP-Filter
            "denoise_strength": 0.20,
            "click_removal_sensitivity": 0.10,
            "declip_strength": 0.0,
        },
    ),
    # ------------------------------------------------------------------
    # HIGH_FREQ_NOISE — Bandrauschen, weißes Rauschen, Vinyl-Hiss
    # ------------------------------------------------------------------
    DefectType.HIGH_FREQ_NOISE: PhaseAssignment(
        defect_type=DefectType.HIGH_FREQ_NOISE,
        primary_phases=[
            "phase_03_denoise",  # Breitband-NR (Spectral Subtraction / MMSE)
            "phase_29_tape_hiss_reduction",  # Tape-spezifisches HF-Rauschen
        ],
        secondary_phases=[
            "phase_18_noise_gate",  # Tiefe Rauschpegel in Pausen beseitigen
            "phase_16_final_eq",  # HF-Shaping nach Denoising
        ],
        description=(
            "Hochfrequenz-Rauschreduktion via spektraler Subtraktion + Wiener-Filter. "
            "Tape-Hiss-Profiling für bandmaterialspezifische Filtercharakteristik."
        ),
        config_delta={
            "denoise_strength": 0.80,
            "click_removal_sensitivity": 0.10,
            "declip_strength": 0.0,
            "preserve_analog_character": True,  # Charakter trotz NR bewahren
        },
    ),
    # ------------------------------------------------------------------
    # COMPRESSION_ARTIFACTS — Überkomprimierung, Pumpen, Ducking
    # ------------------------------------------------------------------
    DefectType.COMPRESSION_ARTIFACTS: PhaseAssignment(
        defect_type=DefectType.COMPRESSION_ARTIFACTS,
        primary_phases=[
            "phase_26_dynamic_range_expansion",  # Compander (inverse Kompression)
            "phase_23_spectral_repair",  # Spektrale Codec-Artefakte
        ],
        secondary_phases=[
            "phase_54_transparent_dynamics",  # Transparente Dynamik-Restauration
            "phase_35_multiband_compression",  # Ausgewogenes Multiband-Reamping
        ],
        description=(
            "Umkehrung von Dynamik-Überkompression via Upward Expansion. "
            "Behandelt Pumpen, Ducking und Ozone-Klang ohne Wasserfall-Effekt."
        ),
        config_delta={
            "enable_spectral_repair": True,
            "spectral_repair_strength": 0.65,
            "compression_ratio": 1.0,  # Keine weitere Kompression!
            "enable_multiband_compression": False,
            "denoise_strength": 0.10,
            "declip_strength": 0.0,
        },
    ),
    # ------------------------------------------------------------------
    # PHASE_ISSUES — Kanalümkehrung, Azimuth-Fehler, Phasendrift
    # ------------------------------------------------------------------
    DefectType.PHASE_ISSUES: PhaseAssignment(
        defect_type=DefectType.PHASE_ISSUES,
        primary_phases=[
            "phase_14_phase_correction",  # Phase-Inversion-Detektion
            "phase_25_azimuth_correction",  # Azimuth-Fehler bei Bandmaschinen
        ],
        secondary_phases=[
            "phase_34_mid_side_processing",  # M/S für Phasenfehler-Analyse
            "phase_15_stereo_balance",  # Begleitende Balance-Korrektur
        ],
        description=(
            "Phasenfehler-Korrektur: Kanal-Inversion-Detektion, Azimuth-Korrektur "
            "und Mid/Side-basierte Phasen-Ausrichtung."
        ),
        config_delta={
            "denoise_strength": 0.10,
            "click_removal_sensitivity": 0.15,
            "declip_strength": 0.0,
            "stereo_width_factor": 1.0,  # Neutrale Breite sicherstellen
        },
    ),
    # ------------------------------------------------------------------
    # DROPOUTS — Tonaussetzer, magnetische Löschstellen auf Band
    # ------------------------------------------------------------------
    DefectType.DROPOUTS: PhaseAssignment(
        defect_type=DefectType.DROPOUTS,
        primary_phases=[
            "phase_24_dropout_repair",  # Interpolation über Aussetzer
            "phase_50_spectral_repair",  # Spektrale Lücken in Dropout-Zonen
        ],
        secondary_phases=[
            "phase_23_spectral_repair",  # Ergänzende spektrale Reparatur
            "phase_07_harmonic_restoration",  # Teilweise verlorene Harmonische
        ],
        description=(
            "Dropout-Reparatur via adaptiver Interpolation (AR-Modell) + "
            "spektraler Auffüllung verlorener Energie-Regionen."
        ),
        config_delta={
            "enable_spectral_repair": True,
            "spectral_repair_strength": 0.90,  # Hoch: Dropouts = große Löcher
            "spectral_repair_hole_threshold_db": -30.0,  # Aggressivere Detektion
            "denoise_strength": 0.20,
            "click_removal_sensitivity": 0.30,  # Dropout-Grenzen sind klickartig
            "declip_strength": 0.10,
        },
    ),
    # ------------------------------------------------------------------
    # CLIPPING — Amplituden-Übersteuerung (Hard Clipping / Tape Saturation)
    # ------------------------------------------------------------------
    DefectType.CLIPPING: PhaseAssignment(
        defect_type=DefectType.CLIPPING,
        primary_phases=[
            "phase_23_spectral_repair",  # Spektrale Rekonstruktion clipper Obertöne
            "phase_26_dynamic_range_expansion",  # Dynamikbereich nach Clipping wiederherstellen
        ],
        secondary_phases=[
            "phase_07_harmonic_restoration",  # Verlorene Obertöne aus Clipping rekonstruieren
            "phase_08_transient_preservation",  # Transienten-Schutz während Declipping
        ],
        description=(
            "Amplituden-Übersteuerungs-Korrektur via spektraler Interpolation und "
            "adaptiver Declipping-Algorithmen. Rekonstruiert abgeschnittene Wellenformspitzen "
            "und stellt harmonische Obertöne wieder her."
        ),
        config_delta={
            "declip_strength": 0.85,  # Primäraktion: Clipping entfernen
            "enable_spectral_repair": True,
            "spectral_repair_strength": 0.70,  # Spektrale Lücken nach Declipping
            "denoise_strength": 0.10,  # Minimal: Rauschen ist Sekundärproblem
            "click_removal_sensitivity": 0.15,  # Clip-Grenzen können klickartig sein
            "compression_ratio": 1.0,  # Keine weitere Kompression!
        },
    ),
    # ------------------------------------------------------------------
    # DC_OFFSET — Gleichspannungsversatz (Nulllinien-Verschiebung)
    # ------------------------------------------------------------------
    DefectType.DC_OFFSET: PhaseAssignment(
        defect_type=DefectType.DC_OFFSET,
        primary_phases=[
            "phase_30_dc_offset_removal",  # Direkte DC-Entfernung via Hochpass-Filter
        ],
        secondary_phases=[
            "phase_05_rumble_filter",  # Sub-Bass kann DC-bedingte Rumpelkomponenten enthalten
            "phase_02_hum_removal",  # DC-begleitende Netzbrumm-Anteile
        ],
        description=(
            "DC-Gleichspannungsversatz-Entfernung via Hochpass-Filter (< 5 Hz). "
            "Beseitigt Nulllinien-Verschiebung die Headroom reduziert, "
            "Verzerrungen verursacht und Lautsprecher beschädigen kann."
        ),
        config_delta={
            "low_freq_rolloff_hz": 5,  # Sehr tiefer HP-Filter: nur DC entfernen
            "denoise_strength": 0.05,  # Minimal: DC-Removal ist kein Rauschproblem
            "click_removal_sensitivity": 0.10,
            "declip_strength": 0.0,
        },
    ),
    # ------------------------------------------------------------------
    # BANDWIDTH_LOSS — HF-Rolloff / Bandbreitenbegrenzung
    # ------------------------------------------------------------------
    DefectType.BANDWIDTH_LOSS: PhaseAssignment(
        defect_type=DefectType.BANDWIDTH_LOSS,
        primary_phases=[
            "phase_06_frequency_restoration",  # HF-Rekonstruktion (Spectral Extension)
            "phase_07_harmonic_restoration",  # Harmonische über Bandgrenze hinaus rekonstruieren
        ],
        secondary_phases=[
            "phase_04_eq_correction",  # Tonal-Shaping nach HF-Restore
        ],
        description=(
            "Hochfrequenz-Restauration für bandbreitenbegrenzte Quellen: "
            "Shellac (< 7 kHz), Kassette (< 14 kHz), MP3-Low (HF-Abschnitt). "
            "Rekonstruiert fehlende Obertöne via spektraler Extrapolation."
        ),
        config_delta={
            "high_freq_boost_db": 3.0,  # HF-Anhebung nach Restauration
            "enable_spectral_repair": True,
            "spectral_repair_strength": 0.60,  # Moderate: Vorsicht bei spektraler Erfindung
            "denoise_strength": 0.15,  # Leicht: HF-Rauschen nicht mit Restauration mischen
            "declip_strength": 0.0,
            "preserve_analog_character": True,  # Charakter bewahren, nicht übertreiben
        },
    ),
    # ------------------------------------------------------------------
    # PITCH_DRIFT — Konstanter Geschwindigkeitsfehler (Tape-Stretch, Motorabweichung)
    # ------------------------------------------------------------------
    DefectType.PITCH_DRIFT: PhaseAssignment(
        defect_type=DefectType.PITCH_DRIFT,
        primary_phases=[
            "phase_31_speed_pitch_correction",  # Konstante Pitch-Korrektur via Time-Stretch
        ],
        secondary_phases=[
            "phase_12_wow_flutter_fix",  # Begleitende Pitch-Instabilitäten mitkorrigieren
        ],
        description=(
            "Korrektur konstanter Tonhöhen-/Geschwindigkeitsfehler: "
            "Tape läuft zu schnell/langsam (z.B. 78rpm→77rpm, Tape-Stretch). "
            "Unterschied zu WOW/FLUTTER: kein periodisches Modulationsmuster, "
            "sondern monotone Frequenzabweichung über die gesamte Aufnahme."
        ),
        config_delta={
            "denoise_strength": 0.10,  # Minimal: Pitch-Fix ist keine Rauschaufgabe
            "click_removal_sensitivity": 0.10,
            "declip_strength": 0.0,
            "preserve_analog_character": True,
        },
    ),
    # ------------------------------------------------------------------
    # REVERB_EXCESS — Übermäßiger / unerwünschter Raumhall
    # ------------------------------------------------------------------
    DefectType.REVERB_EXCESS: PhaseAssignment(
        defect_type=DefectType.REVERB_EXCESS,
        primary_phases=[
            "phase_49_advanced_dereverb",  # WPE-basierte Dereverberation (vollst. DSP)
            "phase_20_reverb_reduction",  # Spektral-Gating + Transientenerhalt
        ],
        secondary_phases=[
            "phase_08_transient_preservation",  # Direkt-Sound-Transienten bewahren
            "phase_18_noise_gate",  # Reverb-Schwanz in Pausen unterdrücken
        ],
        description=(
            "Entfernung unerwünschten Raumhalls aus schlecht bedämpften Aufnahmeräumen. "
            "Phase 49 (WPE DSP): Weighted Prediction Error — schätzt Nachhall-Anteil "
            "und subtrahiert ihn spektral. Phase 20: Spektrales Gating für längere Nachhall-Schwänze. "
            "Bewahrt Direkt-Sound und Transienten durch parallele Transientenanalyse."
        ),
        config_delta={
            "denoise_strength": 0.20,
            "click_removal_sensitivity": 0.10,
            "declip_strength": 0.0,
            "enable_spectral_repair": False,  # Kein Lochfüllen — Reverb kein Loch
            "preserve_analog_character": True,
        },
    ),
    # ------------------------------------------------------------------
    # PRINT_THROUGH — Magnetisches Übersprechen auf Tonband (Pre-Echo)
    # ------------------------------------------------------------------
    DefectType.PRINT_THROUGH: PhaseAssignment(
        defect_type=DefectType.PRINT_THROUGH,
        primary_phases=[
            "phase_01_click_removal",  # Pre-Echo als kurzer Impuls vor Einsatz behandeln
            "phase_23_spectral_repair",  # Spektrale Unterdrückung des Geist-Signals
        ],
        secondary_phases=[
            "phase_18_noise_gate",  # Abklingphase des Pre-Echos per Gate unterdrücken
            "phase_08_transient_preservation",  # Echter Einsatz darf nicht angetastet werden
        ],
        description=(
            "Unterdrückung magnetischen Übersprechens (Print-Through) bei Reel-to-Reel- und "
            "Kassetten-Aufnahmen: Leises Vor-Echo (100–400 ms vor dem Einsatz, 20–45 dB unter "
            "dem Hauptsignal). Spektrale Subtraktion + adaptive Gating des Ghost-Signals. "
            "Nur relevant bei TAPE und REEL_TAPE (Threshold=1.0 für alle anderen Materialien)."
        ),
        config_delta={
            "click_removal_sensitivity": 0.50,  # Pre-Echo ist klickartig kurz
            "denoise_strength": 0.15,
            "declip_strength": 0.0,
            "enable_spectral_repair": True,
            "spectral_repair_strength": 0.55,
            "preserve_analog_character": True,
        },
    ),
    # ------------------------------------------------------------------
    # QUANTIZATION_NOISE — Quantisierungsrauschen (8-Bit, ATRAC, aggressive Kodierung)
    # ------------------------------------------------------------------
    DefectType.QUANTIZATION_NOISE: PhaseAssignment(
        defect_type=DefectType.QUANTIZATION_NOISE,
        primary_phases=[
            "phase_03_denoise",  # Breitband-Rauschreduktion reduziert Granulationsrauschen
            "phase_23_spectral_repair",  # Spektrale Glättung der Quantisierungsstufen
        ],
        secondary_phases=[
            "phase_18_noise_gate",  # Gate verhindert Rauschen in Stille-Phasen
            "phase_04_eq",  # Equalizer zur Kompensation der Spektralform
        ],
        description=(
            "Reduktion von Quantisierungsrauschen durch spektrale Glättung und "
            "Rauschreduktion. Typisch bei 8-Bit-Konvertierungen, ATRAC (MiniDisc), "
            "aggressivem MP3 Low-Bitrate. Granulationsrauschen in leisen Passagen "
            "wird durch adaptives Denoising + sanftes Noise-Gate eliminiert."
        ),
        config_delta={
            "denoise_strength": 0.40,
            "declip_strength": 0.0,
            "click_removal_sensitivity": 0.0,
            "enable_spectral_repair": True,
            "spectral_repair_strength": 0.35,
            "preserve_analog_character": False,  # Digitales Artefakt — kein Analog-Charakter nötig
        },
    ),
    # ------------------------------------------------------------------
    # JITTER_ARTIFACTS — D/A-Wandler-Jitter (CD-Laufwerk, DAT, Netzwerk-Jitter)
    # ------------------------------------------------------------------
    DefectType.JITTER_ARTIFACTS: PhaseAssignment(
        defect_type=DefectType.JITTER_ARTIFACTS,
        primary_phases=[
            "phase_23_spectral_repair",  # FM-Seitenbänder im HF-Band spektral unterdrücken
            "phase_03_denoise",  # HF-Rauschreduktion eliminiert Jitter-Noise-Floor-Erhöhung
        ],
        secondary_phases=[
            "phase_04_eq",  # HF-Frequenzgangkorrektur nach Jitter-Unterdrückung
            "phase_08_transient_preservation",  # Transienten bleiben unangetastet
        ],
        description=(
            "Reduktion von D/A-Wandler-Jitter-Artefakten: FM-Seitenbänder um Sinustöne, "
            "zeitlich inkonsistente HF-Energie > 8 kHz. Typisch bei schlechten CD-Laufwerken, "
            "DAT-Recordern und Streaming-Puffer-Underruns. Spektrale Glättung der "
            "HF-Seitenband-Energie + adaptives HF-Denoising."
        ),
        config_delta={
            "denoise_strength": 0.35,
            "declip_strength": 0.0,
            "click_removal_sensitivity": 0.0,
            "enable_spectral_repair": True,
            "spectral_repair_strength": 0.45,
            "preserve_analog_character": False,
        },
    ),
    # ------------------------------------------------------------------
    # DYNAMIC_COMPRESSION_EXCESS — Loudness War / übermäßige Dynamikkompression
    # ------------------------------------------------------------------
    DefectType.DYNAMIC_COMPRESSION_EXCESS: PhaseAssignment(
        defect_type=DefectType.DYNAMIC_COMPRESSION_EXCESS,
        primary_phases=[
            "phase_08_transient_preservation",  # Transientenwiederherstellung (Anschläge, Attacks)
            "phase_07_declip",  # Declipping der übersteuerten Peaks
        ],
        secondary_phases=[
            "phase_04_eq",  # Spektrale Balance nach Kompressionsartefakten
            "phase_06_stereo_enhancement",  # Stereofeld-Restauration (Kompression verengt Stereo)
        ],
        description=(
            "Teilrestauration übermäßig komprimierter Aufnahmen (Loudness War, DR < 6 dB). "
            "Vollständige Rückgängigmachung ist ohne Quelldaten nicht möglich — aber: "
            "Transientenwiederherstellung (phase_08) rekonstruiert Attack-Energie, "
            "Declipping (phase_07) hebt begrenzte Peaks an, EQ (phase_04) restauriert "
            "Spektralbalance. Ziel: DR +2 bis +4 dB, subjektiv hörbar weniger 'komprimiert'."
        ),
        config_delta={
            "denoise_strength": 0.10,
            "declip_strength": 0.55,  # Hauptwerkzeug: begrenzte Peaks anheben
            "click_removal_sensitivity": 0.0,
            "enable_spectral_repair": False,
            "preserve_analog_character": True,  # Dynamik ist Teil des analogen Charakters
        },
    ),
    # ------------------------------------------------------------------
    # SOFT_SATURATION — Röhren-/Tape-Sättigung soll erhalten, nicht entfernt werden
    # ------------------------------------------------------------------
    DefectType.SOFT_SATURATION: PhaseAssignment(
        defect_type=DefectType.SOFT_SATURATION,
        primary_phases=[
            "phase_22_tape_saturation",  # Emulation/Erhalt statt Entfernung
        ],
        secondary_phases=[
            "phase_08_transient_preservation",
        ],
        description=(
            "Bewahrt weiche Röhren-/Tape-Sättigung als musikalischen Charakter. "
            "Keine destruktive Reparatur, sondern konservative Charaktererhaltung."
        ),
        config_delta={
            "denoise_strength": 0.0,
            "declip_strength": 0.0,
            "click_removal_sensitivity": 0.0,
            "preserve_analog_character": True,
        },
    ),
    # ------------------------------------------------------------------
    # HEAD_WEAR — Frequenzband-Auslöschung durch Kopfverschleiß
    # ------------------------------------------------------------------
    DefectType.HEAD_WEAR: PhaseAssignment(
        defect_type=DefectType.HEAD_WEAR,
        primary_phases=[
            "phase_56_spectral_band_gap_repair",
            "phase_06_frequency_restoration",
        ],
        secondary_phases=[
            "phase_14_phase_correction",
            "phase_25_azimuth_correction",
        ],
        description=(
            "Repariert spektrale Bandlücken und Höhenausfälle durch Kopfverschleiß oder Kontaktprobleme im Bandpfad."
        ),
        config_delta={
            "enable_spectral_repair": True,
            "spectral_repair_strength": 0.85,
            "high_freq_boost_db": 2.0,
            "denoise_strength": 0.15,
            "preserve_analog_character": True,
        },
    ),
    # ------------------------------------------------------------------
    # AZIMUTH_ERROR — HF-Phasen-Slope / Kopf-Schrägstellung
    # ------------------------------------------------------------------
    DefectType.AZIMUTH_ERROR: PhaseAssignment(
        defect_type=DefectType.AZIMUTH_ERROR,
        primary_phases=[
            "phase_25_azimuth_correction",
            "phase_14_phase_correction",
        ],
        secondary_phases=[
            "phase_34_mid_side_processing",
            "phase_15_stereo_balance",
        ],
        description=(
            "Korrigiert Azimuth-Fehler und daraus resultierende Hochton- und Phasenprobleme "
            "zwischen linkem und rechtem Kanal."
        ),
        config_delta={
            "denoise_strength": 0.05,
            "declip_strength": 0.0,
            "click_removal_sensitivity": 0.05,
            "stereo_width_factor": 1.0,
        },
    ),
    # ------------------------------------------------------------------
    # TRANSIENT_SMEARING — verschmierte Anschläge/Attacks
    # ------------------------------------------------------------------
    DefectType.TRANSIENT_SMEARING: PhaseAssignment(
        defect_type=DefectType.TRANSIENT_SMEARING,
        primary_phases=[
            "phase_08_transient_preservation",
            "phase_36_transient_shaper",
        ],
        secondary_phases=[
            "phase_23_spectral_repair",
        ],
        description=(
            "Restauriert verschmierte Transienten und Attack-Definition nach Kompression, "
            "Limiter-Artefakten oder Codec-Verschleifung."
        ),
        config_delta={
            "denoise_strength": 0.05,
            "declip_strength": 0.10,
            "click_removal_sensitivity": 0.0,
            "preserve_analog_character": True,
        },
    ),
    # ------------------------------------------------------------------
    # PRE_ECHO — Codec-Pre-Echo vor Transienten
    # ------------------------------------------------------------------
    DefectType.PRE_ECHO: PhaseAssignment(
        defect_type=DefectType.PRE_ECHO,
        primary_phases=[
            "phase_23_spectral_repair",
            "phase_50_spectral_repair",
        ],
        secondary_phases=[
            "phase_08_transient_preservation",
        ],
        description=(
            "Unterdrückt Codec-Pre-Echo vor Transienten durch spektrale Reparatur, "
            "ohne den eigentlichen Einschwingvorgang zu verwischen."
        ),
        config_delta={
            "enable_spectral_repair": True,
            "spectral_repair_strength": 0.70,
            "denoise_strength": 0.10,
            "click_removal_sensitivity": 0.0,
        },
    ),
    # ------------------------------------------------------------------
    # RIAA_CURVE_ERROR — falsche Disc-Entzerrung
    # ------------------------------------------------------------------
    DefectType.RIAA_CURVE_ERROR: PhaseAssignment(
        defect_type=DefectType.RIAA_CURVE_ERROR,
        primary_phases=[
            "phase_04_eq_correction",
            "phase_06_frequency_restoration",
        ],
        secondary_phases=[
            "phase_07_harmonic_restoration",
        ],
        description=("Korrigiert falsche Entzerrungskurven bei Disc-Transfers (RIAA/AES/NAB/FFRR/Columbia)."),
        config_delta={
            "high_freq_boost_db": 2.5,
            "denoise_strength": 0.10,
            "declip_strength": 0.0,
            "preserve_analog_character": True,
        },
    ),
    # ------------------------------------------------------------------
    # ALIASING — Spiegelartefakte durch unzureichenden AA-Filter
    # ------------------------------------------------------------------
    DefectType.ALIASING: PhaseAssignment(
        defect_type=DefectType.ALIASING,
        primary_phases=[
            "phase_23_spectral_repair",
            "phase_03_denoise",
        ],
        secondary_phases=[
            "phase_50_spectral_repair",
        ],
        description=(
            "Reduziert Aliasing-Spiegelfrequenzen aus fehlerhafter Digitalisierung "
            "durch spektrale Glättung und selektive HF-Bereinigung."
        ),
        config_delta={
            "enable_spectral_repair": True,
            "spectral_repair_strength": 0.55,
            "denoise_strength": 0.25,
            "declip_strength": 0.0,
        },
    ),
    # ------------------------------------------------------------------
    # BIAS_ERROR — falscher Vormagnetisierungsstrom bei Bandaufnahme
    # ------------------------------------------------------------------
    DefectType.BIAS_ERROR: PhaseAssignment(
        defect_type=DefectType.BIAS_ERROR,
        primary_phases=[
            "phase_04_eq_correction",
            "phase_29_tape_hiss_reduction",
        ],
        secondary_phases=[
            "phase_06_frequency_restoration",
            "phase_03_denoise",
        ],
        description=(
            "Kompensiert Bias-Fehler bei Bandaufnahmen, die zu unausgewogenem Frequenzgang, "
            "Hiss und Höhenverlust führen."
        ),
        config_delta={
            "denoise_strength": 0.30,
            "high_freq_boost_db": 1.5,
            "declip_strength": 0.0,
            "preserve_analog_character": True,
        },
    ),
    # ------------------------------------------------------------------
    # SIBILANCE — überbetonte Zischlaute
    # ------------------------------------------------------------------
    DefectType.SIBILANCE: PhaseAssignment(
        defect_type=DefectType.SIBILANCE,
        primary_phases=[
            "phase_19_de_esser",
            "phase_43_ml_deesser",
        ],
        secondary_phases=[
            "phase_38_presence_boost",
        ],
        description=(
            "Kontrolliert überbetonte Sibilanten stimmtyp-adaptiv, ohne Sprachverständlichkeit "
            "oder Präsenz pauschal zu beschneiden."
        ),
        config_delta={
            "denoise_strength": 0.05,
            "declip_strength": 0.0,
            "click_removal_sensitivity": 0.0,
            "preserve_analog_character": True,
        },
    ),
    # ------------------------------------------------------------------
    # TRANSPORT_BUMP — impulsive Mikro-Geschwindigkeitssprünge (50–300 ms)
    # durch mechanische Transporterschütterungen (Kassette/Bandaufnahmen)
    # ------------------------------------------------------------------
    DefectType.TRANSPORT_BUMP: PhaseAssignment(
        defect_type=DefectType.TRANSPORT_BUMP,
        primary_phases=[
            "phase_12_wow_flutter_fix",  # lokale PSOLA-Pitch-Glättung + Envelope-Morphing
            "phase_24_dropout_repair",  # Aussetzer-Interpolation an Bump-Stellen
            "phase_31_speed_pitch_correction",  # Savitzky-Golay Pitch-Korrektur
        ],
        secondary_phases=[
            "phase_08_transient_preservation",  # Schützt Musik-Transienten bei Bump-Reparatur
            "phase_03_denoise",  # Restgeräusche an Bump-Kanten
        ],
        description=(
            "Repariert impulsive Mikro-Geschwindigkeitssprünge (50–300 ms) durch "
            "mechanische Transporterschütterungen bei Kassetten- und Bandaufnahmen. "
            "Unterscheidet sich von kontinuierlichem Wow/Flutter (< 4 Hz) und Dropouts."
        ),
        config_delta={
            "bump_correction_strength": 0.80,
            "crossfade_ms": 15.0,
            "envelope_smoothing": 0.70,
            "denoise_strength": 0.15,
            "click_removal_sensitivity": 0.2,
            "declip_strength": 0.0,
            "preserve_analog_character": True,
        },
    ),
}


# ---------------------------------------------------------------------------
# Material-adaptive Phase-Initialstärken (§2.29 / §2.31)
# ---------------------------------------------------------------------------
# Maps MaterialType.value → { phase_id → initial_strength ∈ (0, 1.0] }
#
# initial_strength < 1.0: Charakter-Schutz / physikalische Grenze
#   (z.B. 0.25 für phase_22_tape_saturation bei shellac → Röhrencharakter bewahren)
# initial_strength > 1.0: NICHT erlaubt — strength ∈ [0,1] in allen Phasen.
#   Stattdessen signalisiert ein Eintrag nahe 1.0 "maximale Stärke gewünscht".
# Kein Eintrag → 1.0 (volle Initialstärke, PMGG-gesteuerter Abbau bei Regression)

_MATERIAL_PHASE_FACTORS: dict[str, dict[str, float]] = {
    # WAX_CYLINDER — extreme noise, very limited BW (≤5 kHz), highest degradation
    "wax_cylinder": {
        "phase_03_denoise": 0.90,  # aggressive NR ok — extreme noise
        "phase_09_crackle_removal": 0.85,  # heavy crackle on wax
        "phase_22_tape_saturation": 0.20,  # protect tube/wax character
        "phase_20_reverb_reduction": 0.20,  # protect period-correct room
        "phase_49_advanced_dereverb": 0.20,  # same: vintage reverb is authentic
        "phase_06_frequency_restoration": 0.30,  # BW << 5kHz, don't over-extend
        "phase_07_harmonic_restoration": 0.35,  # careful harmonic reconstruction
    },
    # SHELLAC — broad noise, BW ≤ 8 kHz, clicks/crackle primary
    "shellac": {
        "phase_03_denoise": 0.85,  # strong NR for shellac noise floor
        "phase_09_crackle_removal": 0.85,  # heavy crackle
        "phase_01_click_removal": 0.85,  # many deep clicks
        "phase_27_click_pop_removal": 0.80,
        "phase_22_tape_saturation": 0.25,  # protect tube character
        "phase_20_reverb_reduction": 0.20,  # vintage room — don't over-dereverberate
        "phase_49_advanced_dereverb": 0.20,
        "phase_06_frequency_restoration": 0.40,  # BW limited; careful extension
        "phase_07_harmonic_restoration": 0.45,
    },
    # LACQUER_DISC — similar to shellac, more substrate clicks
    "lacquer_disc": {
        "phase_03_denoise": 0.80,
        "phase_01_click_removal": 0.85,
        "phase_27_click_pop_removal": 0.80,
        "phase_22_tape_saturation": 0.25,
        "phase_20_reverb_reduction": 0.20,
        "phase_49_advanced_dereverb": 0.20,
        "phase_06_frequency_restoration": 0.50,
    },
    # WIRE_RECORDING — high noise, jitter, good dynamic range
    "wire_recording": {
        "phase_03_denoise": 0.85,
        "phase_12_wow_flutter_fix": 0.90,  # jitter is primary problem
        "phase_31_speed_pitch_correction": 0.85,
        "phase_22_tape_saturation": 0.35,
        "phase_10_compression": 0.40,
    },
    # VINYL — crackle priority, moderate NR
    "vinyl": {
        "phase_09_crackle_removal": 0.85,
        "phase_01_click_removal": 0.80,
        "phase_03_denoise": 0.70,  # vinyl NR gentler than shellac
    },
    # TAPE — hiss priority, preserve tape character (§2.22 Spec)
    "tape": {
        "phase_29_tape_hiss_reduction": 0.85,
        "phase_03_denoise": 0.75,
        "phase_22_tape_saturation": 0.35,  # tape imprint must be preserved
    },
    # REEL_TAPE — higher quality, print-through focus
    "reel_tape": {
        "phase_29_tape_hiss_reduction": 0.80,
        "phase_03_denoise": 0.70,
        "phase_22_tape_saturation": 0.35,  # tape character preserved
    },
    # MP3_LOW — heavy codec artifacts; careful HF extension
    "mp3_low": {
        "phase_06_frequency_restoration": 0.75,  # codec cuts HF; restore carefully
        "phase_07_harmonic_restoration": 0.75,
        "phase_23_spectral_repair": 0.80,
        "phase_50_spectral_repair": 0.80,
    },
    # CD_DIGITAL — high quality input; minimal aggressive processing
    "cd_digital": {
        "phase_03_denoise": 0.25,  # minimal NR for clean digital
        "phase_09_crackle_removal": 0.20,
        "phase_01_click_removal": 0.30,
    },
    # DAT — near-lossless digital; near-zero NR
    "dat": {
        "phase_03_denoise": 0.20,
        "phase_09_crackle_removal": 0.15,
    },
}


def get_material_initial_strength(material: str, phase_id: str) -> float:
    """Returns the material-adaptive initial strength for a given phase.

    Used by PMGG to set the correct starting strength instead of always 1.0.
    Returns 1.0 (default / no override) when no entry is found.

    Args:
        material:  MaterialType.value string (e.g. 'shellac', 'vinyl')
        phase_id:  Full phase_id string (e.g. 'phase_03_denoise')

    Returns:
        initial_strength ∈ (0, 1.0]; default = 1.0
    """
    factors = _MATERIAL_PHASE_FACTORS.get(material, {})
    return float(factors.get(phase_id, 1.0))


# ---------------------------------------------------------------------------
# Haupt-Klasse: DefectPhaseMapper
# ---------------------------------------------------------------------------


class DefectPhaseMapper:
    """
    Ordnet DetectedDefects den richtigen Phase-IDs zu und
    konfiguriert ProcessingConfig präzise für jeden Defekt.

    Verwendung in AutonomousRestorationEngine._build_specialist_variant().
    """

    def get_assignment(self, defect_type: DefectType) -> PhaseAssignment | None:
        """Gibt PhaseAssignment für defect_type zurück, oder None wenn unbekannt."""
        return _PHASE_MAP.get(defect_type)

    def get_primary_phases(self, defect_type: DefectType) -> list[str]:
        """Gibt Primary-Phase-IDs für defect_type zurück."""
        a = _PHASE_MAP.get(defect_type)
        return a.primary_phases if a is not None else []

    def get_all_phases(self, defect_type: DefectType) -> list[str]:
        """Gibt Primary + Secondary Phase-IDs zurück (geordnet nach Priorität)."""
        a = _PHASE_MAP.get(defect_type)
        if a is None:
            return []
        return a.primary_phases + a.secondary_phases

    def build_specialist_config(
        self,
        base_config: object,
        defect_type: DefectType,
        severity: float,
        is_restoration_mode: bool = True,
        material: str | None = None,
    ) -> tuple[object, str]:
        """
        Konfiguriert base_config für den angegebenen Defekt.

        Args:
            base_config:          ProcessingConfig (wird in-place geändert)
            defect_type:          Primärer Defekttyp
            severity:             Defektstärke [0–1]
            is_restoration_mode:  True = RESTORATION (sanfterer mode_factor)
            material:             MaterialType.value-String für material-adaptive Skalierung
                                  (z.B. 'shellac', 'vinyl'). None = kein Material-Override.

        Returns:
            (konfiguriertes_config, variant_name_string)
        """
        import copy

        config = copy.deepcopy(base_config)
        assignment = _PHASE_MAP.get(defect_type)

        if assignment is None:
            logger.debug("Kein Mapping für %s — Basis-Config unverändert.", defect_type)
            return config, f"specialist_{defect_type.value}"

        # RESTORATION-Modus: etwas sanfter (0.8×)
        mode_factor = 0.80 if is_restoration_mode else 1.0

        # Material-Faktor: Mittelwert der primary Phase-Faktoren als config-Skalierung
        mat_factor = 1.0
        if material is not None and assignment.primary_phases:
            phase_factors = [get_material_initial_strength(material, pid) for pid in assignment.primary_phases]
            mat_factor = sum(phase_factors) / len(phase_factors)

        assignment.apply_to_config(config, severity=severity, mode_factor=mode_factor, material_factor=mat_factor)

        # Sicherheitscheck: denoise_strength nie > 0.9 (Authentizität)
        if hasattr(config, "denoise_strength") and is_restoration_mode:
            config.denoise_strength = min(config.denoise_strength, 0.90)  # type: ignore[attr-defined]

        variant_name = f"specialist_{defect_type.value.replace('_', '')}"
        logger.info(
            "Specialist-Config für %s (severity=%.2f, mode_factor=%.1f, mat_factor=%.2f): phases=%s",
            defect_type.value,
            severity,
            mode_factor,
            mat_factor,
            assignment.primary_phases[:2],
        )
        return config, variant_name

    def phases_for_defect_profile(
        self,
        defects: list,
        max_phases: int = 10,
    ) -> list[str]:
        """
        Gibt eine de-duplizierte, priorisierte Phase-Liste für mehrere Defekte zurück.

        Args:
            defects:    Liste von DefectScore-Objekten (mit .defect_type, .severity)
            max_phases: Maximale Anzahl zurückgegebener Phasen

        Returns:
            Geordnete Phase-ID-Liste (primary first, dann secondary, dann de-dup)
        """
        seen: dict[str, float] = {}  # phase_id → max_severity
        for defect in defects:
            severity = getattr(defect, "severity", 0.5)
            dt = getattr(defect, "defect_type", None)
            if dt is None:
                continue
            assignment = _PHASE_MAP.get(dt)
            if assignment is None:
                continue
            for phase_id in assignment.primary_phases:
                seen[phase_id] = max(seen.get(phase_id, 0.0), severity * 1.0)
            for phase_id in assignment.secondary_phases:
                seen[phase_id] = max(seen.get(phase_id, 0.0), severity * 0.6)

        # Sortieren: primäre (severity×1.0) zuerst, sekundäre danach
        sorted_phases = sorted(seen.items(), key=lambda kv: kv[1], reverse=True)
        return [phase_id for phase_id, _ in sorted_phases[:max_phases]]

    def describe(self, defect_type: DefectType) -> str:
        """Menschenlesbare Beschreibung der Strategie für einen Defekttyp."""
        a = _PHASE_MAP.get(defect_type)
        if a is None:
            return f"Kein Mapping für {defect_type.value} bekannt."
        return (
            f"[{defect_type.value}] {a.description}\n"
            f"  Primary : {', '.join(a.primary_phases)}\n"
            f"  Secondary: {', '.join(a.secondary_phases)}"
        )


# ---------------------------------------------------------------------------
# Reverse Phase Map — phase_id → [DefectType] (§MusikalischeHarmonisierung)
# ---------------------------------------------------------------------------
_REVERSE_PHASE_MAP: dict[str, list[DefectType]] | None = None
_REVERSE_LOCK = threading.Lock()


def _build_reverse_phase_map() -> dict[str, list[DefectType]]:
    """Builds reverse mapping: phase_id → [DefectType] from _PHASE_MAP.

    Only primary_phases are mapped (these are the phases designed to FIX
    the defect). Secondary phases are support roles and should not be
    severity-scaled.
    """
    reverse: dict[str, list[DefectType]] = {}
    for defect_type, assignment in _PHASE_MAP.items():
        for phase_id in assignment.primary_phases:
            reverse.setdefault(phase_id, []).append(defect_type)
    return reverse


def get_reverse_phase_map() -> dict[str, list[DefectType]]:
    """Thread-safe accessor for the reverse phase map (cached).

    Returns:
        Dict mapping phase_id → list of DefectTypes this phase primarily targets.
        Enhancement phases (not in _PHASE_MAP as primary) are absent.
    """
    global _REVERSE_PHASE_MAP
    if _REVERSE_PHASE_MAP is None:
        with _REVERSE_LOCK:
            if _REVERSE_PHASE_MAP is None:
                _REVERSE_PHASE_MAP = _build_reverse_phase_map()
    return _REVERSE_PHASE_MAP


def get_phase_defect_severity(phase_id: str, defect_scores: dict) -> float:
    """Returns a severity factor ∈ [_MIN_SEVERITY_FLOOR, 1.0] for a given phase.

    For defect-repair phases (present in reverse map): the factor scales
    proportionally to the maximum measured severity among all DefectTypes
    this phase primarily targets. This ensures:
      - Phases process proportionally to actual defect intensity
      - Low severity → gentle processing (psychoacoustic preservation)
      - High severity → full processing

    For enhancement phases (NOT in reverse map): returns 1.0 (no modulation).

    Args:
        phase_id:      Full phase ID (e.g. 'phase_03_denoise')
        defect_scores: dict[DefectType, DefectScore] from DefectScanner

    Returns:
        Severity factor ∈ [0.15, 1.0].
        0.15 = minimal (defect barely present, gentle processing).
        1.0  = full severity or enhancement phase (no reduction).
    """
    rmap = get_reverse_phase_map()
    target_defects = rmap.get(phase_id)
    if not target_defects:
        return 1.0  # Enhancement phase — no modulation

    max_severity = 0.0
    found_any = False
    for dt in target_defects:
        score = defect_scores.get(dt)
        if score is not None:
            found_any = True
            sev = getattr(score, "severity", 0.0)
            max_severity = max(max_severity, float(sev))

    if not found_any:
        return 1.0  # None of the targeted DefectTypes were scanned — don't penalize

    # Floor at 0.15: even low-severity defects need minimum processing.
    # The phase was selected for a reason — never fully bypass.
    return max(0.15, min(1.0, max_severity))
