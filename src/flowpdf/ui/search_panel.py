from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget


class SearchPanel(QWidget):
    search_requested = Signal(str)
    previous_requested = Signal()
    next_requested = Signal()
    close_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current = 0
        self._total = 0
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(6)

        self.query_edit = QLineEdit(self)
        self.query_edit.setPlaceholderText("在文档中搜索")
        self.query_edit.setClearButtonEnabled(True)
        self.query_edit.setMinimumWidth(220)
        self.query_edit.returnPressed.connect(
            lambda: self.search_requested.emit(self.query_edit.text())
        )
        self.result_label = QLabel("0 个结果", self)
        self.previous_button = QPushButton("上一个", self)
        self.next_button = QPushButton("下一个", self)
        self.close_button = QPushButton("关闭", self)
        self.previous_button.clicked.connect(self.previous_requested)
        self.next_button.clicked.connect(self.next_requested)
        self.close_button.clicked.connect(self.close_requested)

        layout.addWidget(self.query_edit, 1)
        layout.addWidget(self.result_label)
        layout.addWidget(self.previous_button)
        layout.addWidget(self.next_button)
        layout.addWidget(self.close_button)
        self.set_results(0, 0)

    @property
    def result_count(self) -> int:
        return self._total

    def open_and_focus(self) -> None:
        self.show()
        self.query_edit.setFocus()
        self.query_edit.selectAll()

    def set_results(self, current: int, total: int) -> None:
        self._total = max(0, total)
        self._current = max(0, min(current, self._total)) if self._total else 0
        if self._total:
            self.result_label.setText(f"{self._current} / {self._total}")
        else:
            self.result_label.setText("0 个结果")
        enabled = self._total > 0
        self.previous_button.setEnabled(enabled)
        self.next_button.setEnabled(enabled)
