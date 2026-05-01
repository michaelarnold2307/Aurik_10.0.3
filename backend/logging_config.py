import logging
import os
from logging.handlers import RotatingFileHandler

from .error_notifier import setup_error_notifier

LOG_DIR = os.path.join(os.path.dirname(__file__), "../logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "aurik_backend.log")

root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

# Guard: only register the FileHandler if no other handler for the same file is
# already active on the root logger (Aurik910/main.py registers one first).
_log_file_abs = os.path.abspath(LOG_FILE)
_already_registered = any(
    isinstance(h, RotatingFileHandler) and os.path.abspath(getattr(h, "baseFilename", "")) == _log_file_abs
    for h in root_logger.handlers
)
if not _already_registered:
    # Rotierendes Logfile: 5 MB, 5 Backups
    handler = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=5)
    formatter = logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s")
    handler.setFormatter(formatter)
    root_logger.addHandler(handler)

# Fehlerbenachrichtigung aktivieren (E-Mail), falls konfiguriert
setup_error_notifier()

# Optional: Fehler-Alerts (z.B. per E-Mail) können hier ergänzt werden


def get_logger(name=None, level: int = logging.INFO) -> logging.Logger:
    """
    Gibt einen konfigurierten Logger zurück.
    Kombiniert globales Logfile-Setup mit individuellem Level-Support
    (portiert aus backend.core.regulator.logging_config).
    """
    lg = logging.getLogger(name)
    lg.setLevel(level)
    return lg
