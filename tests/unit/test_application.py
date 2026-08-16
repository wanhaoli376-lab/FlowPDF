from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDockWidget

from flowpdf.application import create_application


def test_application_creates_three_column_main_window() -> None:
    app, window = create_application(["flowpdf-test"])

    assert isinstance(app, QApplication)
    assert window.windowTitle() == "FlowPDF"
    assert window.centralWidget() is not None
    assert {dock.objectName() for dock in window.findChildren(QDockWidget)} >= {
        "navigationDock",
        "propertiesDock",
    }
    window.close()
