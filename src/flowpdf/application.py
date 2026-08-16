from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QStandardPaths, Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from flowpdf.document_controller import DocumentController
from flowpdf.rendering.render_scheduler import RenderScheduler
from flowpdf.services.recent_files import RecentFiles
from flowpdf.services.recovery_service import RecoveryService
from flowpdf.services.settings_service import SettingsService
from flowpdf.ui.main_window import MainWindow


def create_application(
    argv: Sequence[str] | None = None,
    *,
    data_root: str | Path | None = None,
) -> tuple[QApplication, MainWindow]:
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

    settings = SettingsService()
    scheduler = RenderScheduler(max_cache_bytes=settings.cache_limit_mb * 1024 * 1024)
    window = MainWindow(scheduler)
    root = _application_data_root(data_root)
    controller = DocumentController(
        window,
        recovery_service=RecoveryService(root / "recovery"),
        recent_files=RecentFiles(settings.settings),
    )
    window.controller = controller

    arguments = list(argv or [])
    if len(arguments) > 1:
        candidate = Path(arguments[1])
        if candidate.suffix.casefold() == ".pdf":
            QTimer.singleShot(0, lambda: controller.open_path(candidate))
    return app, window


def _application_data_root(override: str | Path | None) -> Path:
    configured = override or os.environ.get("FLOWPDF_DATA_DIR")
    if configured:
        root = Path(configured)
    else:
        location = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppLocalDataLocation
        )
        root = Path(location)
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve(strict=True)
