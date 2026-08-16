from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path

from PySide6.QtCore import QStandardPaths


def _log_directory() -> Path:
    configured = os.environ.get("FLOWPDF_DATA_DIR")
    base = configured or QStandardPaths.writableLocation(
        QStandardPaths.StandardLocation.AppLocalDataLocation
    )
    path = Path(base or ".") / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def configure_logging() -> None:
    """Configure bounded technical logs without recording document content."""
    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(logging.INFO)
    handler = logging.handlers.RotatingFileHandler(
        _log_directory() / "flowpdf.log",
        maxBytes=1_000_000,
        backupCount=2,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
