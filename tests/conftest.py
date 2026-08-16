from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("FLOWPDF_DATA_DIR", str(Path.cwd() / ".pytest-tmp" / "app-data"))


def _disable_windows_native_error_dialogs() -> None:
    """Make native test crashes fail the command instead of blocking the desktop."""
    if sys.platform != "win32":
        return
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    no_fault_dialog = 0x0002
    fail_critical_errors = 0x0001
    previous = kernel32.SetErrorMode(0)
    kernel32.SetErrorMode(previous | no_fault_dialog | fail_critical_errors)


_disable_windows_native_error_dialogs()


@pytest.fixture(scope="session")
def qapp():
    """Keep one QApplication wrapper alive until every Qt test has torn down."""
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication

    application = QApplication.instance() or QApplication(["flowpdf-tests"])
    yield application
    application.closeAllWindows()
    application.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
