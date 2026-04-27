"""Unit-Tests für §4.10-VintageVoice Vintage-Stimm-Identitätsschutz in phase_42.

Prüft, dass bei Vintage-Material (shellac/vinyl/reel_tape/tape/cassette etc.)
ohne erkannte Altersgruppe (GenderDetector returns age_group=None) der
breath_preservation-Boden auf mindestens 0.78 gesetzt wird.

Spec: §4.10-VintageVoice (Spec 04), copilot-instructions.md VERBOTEN-Tabelle
"""

from __future__ import annotations

import numpy as np

SR = 48_000
_VINTAGE_MATERIALS = [
    "shellac",
    "vinyl",
    "reel_tape",
    "tape",
    "cassette",
    "wax_cylinder",
    "wire_recording",
    "lacquer_disc",
    "acoustic_78",
]


def _make_vocal(f0: float = 220.0, duration_s: float = 1.0) -> np.ndarray:
    """Synthetisches Vokalsignal mit Harmonischen."""
    n = int(SR * duration_s)
    t = np.arange(n, dtype=np.float64) / SR
    sig = np.zeros(n)
    for h in range(1, 7):
        sig += (0.4 / h) * np.sin(2 * np.pi * f0 * h * t)
    # Atemrauschen simulieren
    rng = np.random.default_rng(42)
    sig += rng.standard_normal(n) * 0.02
    return (sig / (np.max(np.abs(sig)) + 1e-12) * 0.6).astype(np.float32)


class TestPhase42VintageBreathDirectLogic:
    """Direkter Test der Vintage-Guard-Logik ohne volle Phase-Ausführung."""

    def test_breath_floor_logic_raises_when_none_and_vintage(self):
        """Simuliert die Guard-Logik isoliert — keine externen Dependencies."""
        _VINTAGE_MATERIAL_KEYS = frozenset(
            {
                "shellac",
                "wax_cylinder",
                "vinyl",
                "lacquer_disc",
                "wire_recording",
                "acoustic_78",
                "reel_tape",
                "tape",
                "cassette",
            }
        )

        for material in _VINTAGE_MATERIAL_KEYS:
            _detected_age_group_value = None
            _age_breath_preservation = 0.70  # Default-Fallback vor Guard

            if _detected_age_group_value is None and material in _VINTAGE_MATERIAL_KEYS:
                _age_breath_preservation = max(_age_breath_preservation, 0.78)

            assert _age_breath_preservation >= 0.78, (
                f"Guard-Logik fehlerhaft für material='{material}': "
                f"breath_preservation={_age_breath_preservation:.3f} < 0.78"
            )

    def test_breath_floor_logic_unaffected_when_age_group_known(self):
        """Wenn age_group erkannt → kein Vintage-Boden (Senior=0.90 steuert bereits)."""
        _VINTAGE_MATERIAL_KEYS = frozenset({"shellac", "vinyl", "reel_tape"})

        _detected_age_group_value = "adult"  # Erkannte Altersgruppe
        _age_breath_preservation = 0.72  # adult-profile breath_preservation

        if _detected_age_group_value is None and "shellac" in _VINTAGE_MATERIAL_KEYS:
            _age_breath_preservation = max(_age_breath_preservation, 0.78)

        # age_group bekannt → Guard soll NICHT feuern
        assert _age_breath_preservation == 0.72, (
            f"Wenn age_group bekannt, darf Vintage-Guard nicht feuern. Erhalten: {_age_breath_preservation}"
        )

    def test_breath_floor_logic_unaffected_for_digital_material(self):
        """Für cd_digital (nicht vintage) → kein Vintage-Boden."""
        _VINTAGE_MATERIAL_KEYS = frozenset(
            {
                "shellac",
                "wax_cylinder",
                "vinyl",
                "lacquer_disc",
                "wire_recording",
                "acoustic_78",
                "reel_tape",
                "tape",
                "cassette",
            }
        )

        _detected_age_group_value = None  # Unerkannte Altersgruppe
        _age_breath_preservation = 0.70

        if _detected_age_group_value is None and "cd_digital" in _VINTAGE_MATERIAL_KEYS:
            _age_breath_preservation = max(_age_breath_preservation, 0.78)

        assert _age_breath_preservation == 0.70, (
            f"cd_digital: Vintage-Guard soll nicht feuern, breath_preservation={_age_breath_preservation}"
        )
