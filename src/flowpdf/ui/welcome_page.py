from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from flowpdf.i18n import tr


class WelcomePage(QWidget):
    """Simple, keyboard-friendly start screen."""

    open_requested = Signal()
    new_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(80, 60, 80, 60)
        layout.setSpacing(16)
        layout.addStretch(1)

        title = QLabel("FlowPDF", self)
        title.setObjectName("welcomeTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 30pt; font-weight: 600;")
        subtitle = QLabel(tr("WelcomePage", "本地打开、查看和编辑 PDF。文件不会上传。"), self)
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)

        open_button = QPushButton(tr("WelcomePage", "打开 PDF"), self)
        open_button.setMinimumHeight(42)
        open_button.clicked.connect(self.open_requested)
        new_button = QPushButton(tr("WelcomePage", "新建空白 PDF"), self)
        new_button.setMinimumHeight(38)
        new_button.clicked.connect(self.new_requested)

        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(12)
        layout.addWidget(open_button)
        layout.addWidget(new_button)
        layout.addStretch(2)
