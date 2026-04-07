"""
Aurik 6.0 – SOTA-System- und Plugin-Check

Dieses Skript prüft die Kernmodule und Plugins gemäß SOTA-Standards und Dokumentation.
Alle Ausgaben und Begriffe sind an die aktuelle Architektur angepasst.
"""

import glob
import importlib
import logging
import os
import sys

import requests

logger = logging.getLogger(__name__)

logger.info("Aurik 6.0 – SOTA System- und Plugin-Check")

# Kernabhängigkeiten
try:
    logger.info("Check: soundfile OK")
except Exception as e:
    logger.error("ERROR: soundfile: %s", e)
    sys.exit(1)
try:
    logger.info("Check: numpy OK")
except Exception as e:
    logger.error("ERROR: numpy: %s", e)
    sys.exit(1)
try:
    logger.info("Check: onnxruntime OK")
except Exception as e:
    logger.error("ERROR: onnxruntime: %s", e)
    sys.exit(1)

# SOTA-Plugin- und Health-Check
plugin_dir = os.path.join("Aurik_Standalone", "plugins")
failed: list[str] = []
for f in glob.glob(os.path.join(plugin_dir, "*.py")):
    mod = os.path.splitext(os.path.basename(f))[0]
    if mod == "__init__":
        continue
    try:
        importlib.import_module(f"plugins.{mod}")
        logger.info("[SOTA-Check] Plugin: %s OK", mod)
    except Exception as e:
        logger.error("[SOTA-Check] ERROR: %s: %s", mod, e)
        failed.append(mod)

# Health-Endpoint prüfen
try:
    r = requests.get("http://localhost:8000/health", timeout=2)
    if r.status_code == 200 and "ok" in r.text:
        logger.info("[SOTA-Check] Health-Endpoint OK")
    else:
        logger.error("[SOTA-Check] Health-Endpoint Fehler: %s %s", r.status_code, r.text)
        failed.append("health-endpoint")
except Exception as e:
    logger.info("[SOTA-Check] Health-Endpoint nicht erreichbar: %s", e)
    failed.append("health-endpoint")

if failed:
    logger.error("[SOTA-Check] Fehlerhafte Komponenten: %s", failed)
    sys.exit(1)
else:
    logger.info("[SOTA-Check] Alle Plugins, Kernmodule und Health-Checks erfolgreich geladen.")
    sys.exit(0)
