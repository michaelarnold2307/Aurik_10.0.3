"""Unit-Tests für RestorationMemory (§2.70, v9.13)."""

import pytest

from backend.core.restoration_memory import RestorationMemory, get_restoration_memory


@pytest.fixture()
def mem(tmp_path):
    """Erzeugt eine frische RestorationMemory-Instanz mit tmp-Pfad (kein globaler Singleton-State)."""
    return RestorationMemory(path=tmp_path / "restoration_memory.json")


class TestRestorationMemoryBasic:
    def test_get_prior_returns_none_for_unknown_key(self, mem):
        result = mem.get_prior((1960, "vinyl", "abc12345"))
        assert result is None

    def test_save_and_get_prior_round_trip(self, mem):
        key = (1970, "tape", "deadbeef")
        mem.save_result(key, {"strength": 0.5}, hpi_achieved=0.82)
        result = mem.get_prior(key)
        assert result is not None
        assert result["hpi_achieved"] == pytest.approx(0.82, abs=1e-4)

    def test_save_does_not_overwrite_better_prior(self, mem):
        key = (1970, "tape", "deadbeef")
        mem.save_result(key, {"strength": 0.5}, hpi_achieved=0.90)
        mem.save_result(key, {"strength": 0.3}, hpi_achieved=0.70)  # schlechterer Prior
        result = mem.get_prior(key)
        assert result["hpi_achieved"] == pytest.approx(0.90, abs=1e-4), (
            "Schlechterer Prior soll besseren nicht überschreiben"
        )

    def test_save_overwrites_with_better_prior(self, mem):
        key = (1970, "tape", "deadbeef")
        mem.save_result(key, {"strength": 0.5}, hpi_achieved=0.70)
        mem.save_result(key, {"strength": 0.7}, hpi_achieved=0.92)  # besserer Prior
        result = mem.get_prior(key)
        assert result["hpi_achieved"] == pytest.approx(0.92, abs=1e-4)

    def test_hpi_zero_not_saved(self, mem):
        key = (1970, "tape", "cafe1234")
        mem.save_result(key, {}, hpi_achieved=0.0)
        assert mem.get_prior(key) is None

    def test_hpi_negative_not_saved(self, mem):
        key = (1970, "tape", "babe5678")
        mem.save_result(key, {}, hpi_achieved=-0.5)
        assert mem.get_prior(key) is None

    def test_multiple_keys_independent(self, mem):
        key1 = (1960, "vinyl", "aaaaaaaa")
        key2 = (1980, "cd", "bbbbbbbb")
        mem.save_result(key1, {}, hpi_achieved=0.88)
        mem.save_result(key2, {}, hpi_achieved=0.75)
        assert mem.get_prior(key1)["hpi_achieved"] == pytest.approx(0.88, abs=1e-4)
        assert mem.get_prior(key2)["hpi_achieved"] == pytest.approx(0.75, abs=1e-4)

    def test_persistence_across_instances(self, tmp_path):
        """Gespeicherte Priors überleben eine neue Instanz (Disk-Persistenz)."""
        path = tmp_path / "restoration_memory.json"
        m1 = RestorationMemory(path=path)
        key = (1970, "vinyl", "persist01")
        m1.save_result(key, {"x": 1}, hpi_achieved=0.88)

        m2 = RestorationMemory(path=path)
        result = m2.get_prior(key)
        assert result is not None
        assert result["hpi_achieved"] == pytest.approx(0.88, abs=1e-4)


class TestRestorationMemorySingleton:
    def test_singleton_returns_same_instance(self):
        a = get_restoration_memory()
        b = get_restoration_memory()
        assert a is b
