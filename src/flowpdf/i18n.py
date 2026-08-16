from __future__ import annotations

from PySide6.QtCore import QCoreApplication


def tr(context: str, text: str) -> str:
    """Translate UI text through Qt's standard translation seam."""
    return QCoreApplication.translate(context, text)
