from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDockWidget

from flowpdf.application import create_application
from flowpdf.services.save_artifact_registry import SaveArtifactRegistry


def test_application_creates_three_column_main_window(qapp) -> None:
    app, window = create_application(["flowpdf-test"])

    assert isinstance(app, QApplication)
    assert window.windowTitle() == "FlowPDF"
    assert window.centralWidget() is not None
    assert {dock.objectName() for dock in window.findChildren(QDockWidget)} >= {
        "navigationDock",
        "propertiesDock",
    }
    window.dark_theme_action.trigger()
    assert "#202226" in app.styleSheet()
    window.light_theme_action.trigger()
    assert app.styleSheet() == ""
    window.close()


def test_application_startup_cleans_registered_export_artifact(qapp, tmp_path) -> None:
    data_root = tmp_path / "app-data"
    documents = tmp_path / "documents"
    documents.mkdir()
    artifact = documents / ".flowpdf-export-0123456789abcdef0123456789abcdef.tmp.pdf"
    artifact.write_bytes(b"sensitive exported page")
    registry = SaveArtifactRegistry(data_root / "pending-saves.json")
    registry.register(artifact)

    _app, window = create_application(["flowpdf-test"], data_root=data_root)

    assert not artifact.exists()
    window.close()
