from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from flowpdf.ui.main_window import MainWindow


def create_application(argv: Sequence[str] | None = None) -> tuple[QApplication, MainWindow]:
    """Create the Qt application and its main window without entering the event loop."""
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication.instance()
    if app is None:
        app = QApplication(list(argv or []))
    app.setApplicationName("FlowPDF")
    app.setOrganizationName("FlowPDF")
    app.setApplicationVersion("0.1.0a1")
    QCoreApplication.setOrganizationDomain("flowpdf.local")

    font = QFont()
    font.setFamilies(["Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", "sans-serif"])
    font.setPointSize(10)
    app.setFont(font)

    window = MainWindow()
    return app, window
