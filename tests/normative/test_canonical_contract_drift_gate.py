"""[RELEASE_MUST] Canonical Contract Drift Gate.

Dieses Gate verhindert Parallelpfade neben dem kanonischen Aurik-Vertrag:
Import -> Pre-Analysis -> AurikDenker.denke -> Bridge/Exporter-Export.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_COPILOT_INSTRUCTIONS = _ROOT / ".github" / "copilot-instructions.md"
_SPEC_08 = _ROOT / ".github" / "specs" / "08_architecture_and_distribution.md"
_SPEC_07 = _ROOT / ".github" / "specs" / "07_quality_and_tests.md"
_CLI = _ROOT / "cli" / "aurik_cli.py"
_FRONTEND = _ROOT / "Aurik910" / "ui" / "modern_window.py"
_REST_LEGACY = [
    _ROOT / "backend" / "api" / "rest" / "batch_api.py",
    _ROOT / "backend" / "api" / "rest" / "batch_endpoints.py",
]
_DEBUG_LEGACY = [
    _ROOT / "cli" / "aurik_debug.py",
    _ROOT / "backend" / "api" / "debug_api.py",
]


@pytest.mark.normative
@pytest.mark.timeout(20)
def test_canonical_contract_is_documented_in_vorgaben_and_specs() -> None:
    """Canonical Contract Drift muss in Vorgaben und Specs normativ verankert sein."""
    expected = "Canonical Contract Drift Gate"
    for path in (_COPILOT_INSTRUCTIONS, _SPEC_08, _SPEC_07):
        assert path.exists(), f"{path} fehlt."
        text = path.read_text(encoding="utf-8")
        assert expected in text, f"{expected} fehlt in {path}."


@pytest.mark.normative
@pytest.mark.timeout(20)
def test_cli_release_path_uses_full_canonical_contract() -> None:
    """CLI muss Import, Voranalyse, Denker und Export ueber den Bridge-Vertrag fuehren."""
    src = _CLI.read_text(encoding="utf-8")
    required_tokens = {
        "get_load_audio_fn": "CLI muss Audio ueber den kanonischen Bridge-Loader laden.",
        "run_pre_analysis": "CLI muss die Voranalyse vor dem Denker ausfuehren.",
        "get_aurik_denker_instance": "CLI muss den Denker-Singleton nutzen.",
        "denker.denke(": "CLI muss den Pflicht-Einstieg AurikDenker.denke() nutzen.",
        "export_guard(": "CLI-Export muss vor Schreiboperationen export_guard() nutzen.",
        "validate_export_quality(": "CLI muss das Bridge-Export-Quality-Gate nutzen.",
        "build_export_quality_gate_payload(": "CLI muss den strukturierten Export-Gate-Payload erzeugen.",
        "get_audio_exporter_class": "CLI muss den AudioExporter als Primaerpfad nutzen.",
        "os.replace(tmp_path, out_path)": "CLI-Fallback muss atomic WAV schreiben.",
    }
    for token, message in required_tokens.items():
        assert token in src, message

    forbidden_tokens = (
        "UnifiedRestorerV3.restore(",
        "get_restorer().restore(",
        "sf.write(output_path",
        "sf.read(",
        "librosa.load(",
    )
    for token in forbidden_tokens:
        assert token not in src, f"CLI enthaelt verbotenen Parallelpfad: {token}"


@pytest.mark.normative
@pytest.mark.timeout(20)
def test_frontend_release_path_uses_bridge_contract() -> None:
    """Frontend muss Bridge/Denker/Export-Gate statt direkter Core-Bypaesse nutzen."""
    src = _FRONTEND.read_text(encoding="utf-8")
    required_tokens = {
        "_bridge_run_pre_analysis": "Frontend muss die Bridge-Voranalyse nutzen.",
        "_bridge_get_load_audio_fn": "Frontend muss den Bridge-Loader nutzen.",
        "_bridge_get_aurik_denker_instance": "Frontend muss den Denker-Singleton nutzen.",
        ".denke(": "Frontend muss AurikDenker.denke() nutzen.",
        "_export_guard(": "Frontend-Export muss export_guard nutzen.",
        "_validate_export_quality(": "Frontend muss das Export-Quality-Gate nutzen.",
        "_build_export_quality_gate_payload": "Frontend muss strukturierten Gate-Payload erzeugen.",
        "_bridge_get_audio_exporter_class": "Frontend muss den Bridge-AudioExporter nutzen.",
    }
    for token, message in required_tokens.items():
        assert token in src, message

    assert "get_restorer().restore(" not in src, (
        "Frontend darf UV3 nicht direkt ueber get_restorer().restore() aufrufen."
    )
    assert "UnifiedRestorerV3.restore(" not in src, "Frontend darf UV3 nicht direkt aufrufen."


@pytest.mark.normative
@pytest.mark.timeout(20)
def test_legacy_rest_server_paths_are_explicitly_non_release() -> None:
    """REST-Altpfade mit eigenem IO muessen klar als nicht release-faehig markiert sein."""
    for path in _REST_LEGACY:
        assert path.exists(), f"{path} fehlt."
        src = path.read_text(encoding="utf-8")
        assert "LEGACY_NON_RELEASE" in src, (
            f"{path} nutzt historische Server-/Batch-Logik und muss als LEGACY_NON_RELEASE markiert sein "
            "oder vollstaendig auf den Canonical Bridge Contract migriert werden."
        )


@pytest.mark.normative
@pytest.mark.timeout(20)
def test_legacy_debug_paths_are_explicitly_non_release() -> None:
    """Debug-Bypasspfade muessen klar als LEGACY_NON_RELEASE markiert bleiben."""
    for path in _DEBUG_LEGACY:
        assert path.exists(), f"{path} fehlt."
        src = path.read_text(encoding="utf-8")
        assert "LEGACY_NON_RELEASE" in src, (
            f"{path} ist ein Debug-/Bypasspfad und muss als LEGACY_NON_RELEASE markiert sein, "
            "damit keine Release-Parallelwelt entsteht."
        )


@pytest.mark.normative
@pytest.mark.timeout(20)
def test_release_mode_surface_remains_two_button_only() -> None:
    """Release-Oberflaechen duerfen nur Restoration und Studio 2026 als Nutzerentscheidung anbieten."""
    cli_src = _CLI.read_text(encoding="utf-8")
    ui_src = _FRONTEND.read_text(encoding="utf-8")
    assert "Restoration" in cli_src and "Studio 2026" in cli_src
    assert '"RESTORATION"' in ui_src and '"STUDIO_2026"' in ui_src
    assert "--strength" not in cli_src
    assert "--phase" not in cli_src
    assert "--policy" not in cli_src


@pytest.mark.normative
@pytest.mark.timeout(20)
def test_cli_mode_aliases_use_bridge_normalizer() -> None:
    """Mode-Alias-Normalisierung darf nicht parallel in der CLI driften."""
    cli_src = _CLI.read_text(encoding="utf-8")
    bridge_src = (_ROOT / "backend" / "api" / "bridge.py").read_text(encoding="utf-8")

    assert "def normalize_user_mode(" in bridge_src, (
        "Bridge muss den zentralen normalize_user_mode()-Resolver bereitstellen."
    )
    assert "normalize_user_mode = _bridge.normalize_user_mode" in cli_src, (
        "CLI muss den Bridge-Resolver für Mode-Aliase verwenden."
    )
    assert "return normalize_user_mode(mode)" in cli_src, (
        "CLI _normalize_mode() muss an die Bridge delegieren, statt eigene Alias-Tabellen zu pflegen."
    )
