from __future__ import annotations

import os
from collections.abc import Sequence
from importlib.resources import files
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QStandardPaths, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QIcon
from PySide6.QtWidgets import QApplication, QInputDialog

from flowpdf.document_controller import DocumentController
from flowpdf.rendering.render_scheduler import RenderScheduler
from flowpdf.services.recent_files import RecentFiles
from flowpdf.services.recovery_service import RecoveryService
from flowpdf.services.settings_service import SettingsService
from flowpdf.services.temp_file_service import TempFileService
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
    icon = QIcon(str(files("flowpdf.resources").joinpath("flowpdf.svg")))
    app.setWindowIcon(icon)

    settings = SettingsService()
    root = _application_data_root(data_root)
    TempFileService(root / "temp").cleanup()
    scheduler = RenderScheduler(max_cache_bytes=settings.cache_limit_mb * 1024 * 1024)
    window = MainWindow(scheduler)
    window.setWindowIcon(icon)
    controller = DocumentController(
        window,
        recovery_service=RecoveryService(root / "recovery"),
        recent_files=RecentFiles(settings.settings),
    )
    window.controller = controller
    window.theme_requested.connect(lambda value: _set_theme(app, window, settings, value))
    window.cache_settings_action.triggered.connect(
        lambda _checked=False: _configure_cache(window, scheduler, settings)
    )
    _set_theme(app, window, settings, settings.theme.value)

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


def _set_theme(
    app: QApplication,
    window: MainWindow,
    settings: SettingsService,
    value: str,
) -> None:
    from flowpdf.services.settings_service import Theme

    theme = Theme(value)
    settings.theme = theme
    settings.sync()
    window.set_theme_choice(theme.value)
    if theme is Theme.DARK:
        app.setStyleSheet(
            "QWidget{background:#202226;color:#E5E7EB;}"
            "QLineEdit,QTextEdit,QSpinBox,QDoubleSpinBox,QComboBox,QListWidget{"
            "background:#2B2E34;color:#F3F4F6;border:1px solid #4B5563;}"
            "QMenuBar,QMenu,QToolBar,QStatusBar{background:#26292F;color:#F3F4F6;}"
            "QPushButton{background:#343841;border:1px solid #525866;padding:5px;}"
            "QPushButton:hover{background:#414652;}"
        )
        window.document_view.page_scene.setBackgroundBrush(QColor("#30343B"))
    else:
        app.setStyleSheet("")
        window.document_view.page_scene.setBackgroundBrush(QColor("#E7E9ED"))


def _configure_cache(
    window: MainWindow,
    scheduler: RenderScheduler,
    settings: SettingsService,
) -> None:
    value, accepted = QInputDialog.getInt(
        window,
        "渲染缓存",
        "内存缓存上限（MB）：",
        settings.cache_limit_mb,
        64,
        4096,
        64,
    )
    if accepted:
        settings.cache_limit_mb = value
        settings.sync()
        scheduler.set_cache_limit(value * 1024 * 1024)
        window.set_saved_status(f"渲染缓存上限已设为 {value} MB")
