"""RestorationMemory — Persistente GPOptimizer-Priors (§2.70, v9.13).

Speichert erfolgreiche Restaurierungs-Läufe (era × material × defect_cluster_hash)
als JSON unter ~/.aurik/restoration_memory.json und stellt sie als Prior für den
GPOptimizer zur Verfügung. Nur erfolgreiche Läufe werden gespeichert
(HPI > 0 AND artifact_freedom >= 0.95).

Design:
    - Singleton (thread-safe, double-checked locking).
    - Atomarer Schreibvorgang: .tmp → os.replace().
    - LRU-Eviction bei Dateigröße > 10 MB.
    - Kein Crash bei korrupter Datei (Fallback → leeres Dict).

Kanonische Nutzung:
    from backend.core.restoration_memory import get_restoration_memory
    mem = get_restoration_memory()

    # Vor GPOptimizer:
    prior = mem.get_prior((era, material, cluster_hash))  # None wenn kein Prior

    # Nach HolisticPerceptualGate (HPI > 0 AND artifact_freedom >= 0.95):
    mem.save_result(key=(era, material, cluster_hash), phase_params={...}, hpi_achieved=0.81)
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Maximale Dateigröße in Bytes (10 MB). Bei Überschreitung → LRU-Eviction.
_MAX_FILE_BYTES: int = 10 * 1024 * 1024
# Pfad zur persistenten Datei (§Pfad-Mapping).
_DEFAULT_MEMORY_PATH: Path = Path.home() / ".aurik" / "restoration_memory.json"

_instance: RestorationMemory | None = None
_lock: threading.Lock = threading.Lock()


def _make_key_str(key: tuple[Any, ...]) -> str:
    """Wandelt einen Tupel-Schlüssel in einen stabilen String-Key um."""
    raw = json.dumps(key, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16] + "__" + raw[:64]


class RestorationMemory:
    """Persistente Priors für GPOptimizer (§2.70).

    Nur über get_restoration_memory() instantiieren.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path: Path = path or _DEFAULT_MEMORY_PATH
        self._data: dict[str, Any] = {}
        self._dirty: bool = False
        self._internal_lock = threading.Lock()
        self._load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_prior(self, key: tuple[Any, ...]) -> dict[str, Any] | None:
        """Gibt gespeicherten Prior für einen (era, material, cluster_hash)-Schlüssel zurück.

        Returns:
            Dict mit 'phase_params' und 'hpi_achieved' oder None wenn kein Prior vorhanden.
        """
        key_str = _make_key_str(key)
        with self._internal_lock:
            entry = self._data.get(key_str)
        if entry is None:
            return None
        # Zugriffszeit für LRU aktualisieren (in-memory only, kein sofortiger Schreibvorgang)
        entry["_last_access"] = time.time()
        return {
            "phase_params": entry.get("phase_params", {}),
            "hpi_achieved": float(entry.get("hpi_achieved", 0.0)),
        }

    def save_result(
        self,
        key: tuple[Any, ...],
        phase_params: dict[str, Any],
        hpi_achieved: float,
    ) -> None:
        """Speichert ein erfolgreiches Ergebnis als Prior.

        Nur aufrufen wenn HPI > 0 AND artifact_freedom >= 0.95 (§2.70).

        Args:
            key:           (era, material, defect_cluster_hash)-Tupel.
            phase_params:  Phasen-Parameter-Dict aus GPOptimizer-Ergebnis.
            hpi_achieved:  HPI-Score dieses Laufs.
        """
        if hpi_achieved <= 0.0:
            logger.debug("RestorationMemory: HPI <= 0 → nicht gespeichert (key=%s)", key)
            return

        key_str = _make_key_str(key)
        entry: dict[str, Any] = {
            "phase_params": phase_params,
            "hpi_achieved": float(hpi_achieved),
            "_timestamp": time.time(),
            "_last_access": time.time(),
        }

        with self._internal_lock:
            existing = self._data.get(key_str)
            # Nur überschreiben wenn neuer Score besser als gespeicherter
            if existing is not None and float(existing.get("hpi_achieved", 0.0)) >= hpi_achieved:
                logger.debug(
                    "RestorationMemory: Vorhandener Prior HPI=%.3f >= %.3f → nicht überschrieben",
                    existing.get("hpi_achieved", 0.0),
                    hpi_achieved,
                )
                return
            self._data[key_str] = entry
            self._dirty = True

        self._persist()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Lädt die Memory-Datei; ignoriert Fehler (leeres Dict als Fallback)."""
        try:
            if self._path.exists():
                raw = self._path.read_bytes()
                self._data = json.loads(raw)
                logger.debug("RestorationMemory: %d Einträge geladen aus %s", len(self._data), self._path)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("RestorationMemory: Ladevorgang fehlgeschlagen (non-blocking): %s", exc)
            self._data = {}

    def _persist(self) -> None:
        """Schreibt _data atomar in die JSON-Datei (§2.70 Atomic-Write-Invariante)."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._internal_lock:
                data_copy = dict(self._data)

            payload = json.dumps(data_copy, indent=2, default=str)
            encoded = payload.encode("utf-8")

            # LRU-Eviction wenn > 10 MB
            if len(encoded) > _MAX_FILE_BYTES:
                data_copy = self._evict_lru(data_copy)
                payload = json.dumps(data_copy, indent=2, default=str)
                encoded = payload.encode("utf-8")
                with self._internal_lock:
                    self._data = data_copy

            # Atomarer Schreibvorgang: tmp-Datei → os.replace
            tmp_path = self._path.with_suffix(".tmp")
            tmp_path.write_bytes(encoded)
            os.replace(str(tmp_path), str(self._path))
            self._dirty = False
            logger.debug("RestorationMemory: %d Einträge geschrieben nach %s", len(data_copy), self._path)
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("RestorationMemory: Schreibvorgang fehlgeschlagen (non-blocking): %s", exc)

    @staticmethod
    def _evict_lru(data: dict[str, Any]) -> dict[str, Any]:
        """Entfernt die ältesten 20 % der Einträge (LRU nach _last_access)."""
        if not data:
            return data
        sorted_keys = sorted(data.keys(), key=lambda k: float(data[k].get("_last_access", 0.0)))
        evict_count = max(1, len(sorted_keys) // 5)
        for k in sorted_keys[:evict_count]:
            del data[k]
        logger.info("RestorationMemory LRU-Eviction: %d Einträge entfernt", evict_count)
        return data


def get_restoration_memory() -> RestorationMemory:
    """Thread-sicherer Singleton-Getter für RestorationMemory (§Singleton-Pattern)."""
    global _instance  # pylint: disable=global-statement
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = RestorationMemory()
    return _instance
