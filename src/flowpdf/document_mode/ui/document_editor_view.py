from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from flowpdf.document_mode.editing import PaginatedTextEdit
from flowpdf.document_mode.importing import ImportReport
from flowpdf.document_mode.models import FlowDocument


class DocumentEditorView(QWidget):
    """Continuous document-mode surface backed by exactly one QTextDocument."""

    page_status_changed = Signal(int, int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.editor = PaginatedTextEdit(self)
        self.editor.setObjectName("documentModeTextEdit")
        self.editor.setStyleSheet(
            "QTextEdit#documentModeTextEdit {"
            "background: white; color: #111827; border: 1px solid #cbd5e1;"
            "padding: 28px; selection-background-color: #bfdbfe;"
            "}"
        )
        self.import_notice = QLabel(self)
        self.import_notice.setObjectName("documentImportNotice")
        self.import_notice.setWordWrap(True)
        self.import_notice.setFrameShape(QFrame.Shape.StyledPanel)
        self.import_notice.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(38, 20, 38, 20)
        layout.setSpacing(10)
        layout.addWidget(self.import_notice)
        layout.addWidget(self.editor, 1, Qt.AlignmentFlag.AlignHCenter)
        self.setStyleSheet("DocumentEditorView { background: #e5e7eb; }")

        self.editor.pagination_changed.connect(self._emit_page_status)
        self.editor.cursorPositionChanged.connect(self._emit_page_status)

    @property
    def current_page(self) -> int:
        snapshot = self.editor.pagination_snapshot()
        block_number = self.editor.textCursor().blockNumber()
        if not snapshot.block_pages:
            return 0
        block_number = min(max(0, block_number), len(snapshot.block_pages) - 1)
        return snapshot.block_pages[block_number]

    def set_document(self, document: FlowDocument, report: ImportReport | None = None) -> None:
        self.editor.set_flow_document(document)
        if report is None:
            self.import_notice.hide()
        else:
            recommendation = (
                "推荐文档编辑模式"
                if report.recommended_mode == "document"
                else "复杂版式，建议改用版面编辑模式"
            )
            warning = f"；{report.warnings[0]}" if report.warnings else ""
            self.import_notice.setText(f"导入质量 {report.score}/100 · {recommendation}{warning}")
            self.import_notice.show()
        self._emit_page_status()

    def clear_document(self) -> None:
        self.editor.clear()
        self.import_notice.hide()

    def restore_cursor(self, position: int, anchor: int, scroll_y: int) -> None:
        end = max(0, self.editor.document().characterCount() - 1)
        cursor = QTextCursor(self.editor.document())
        cursor.setPosition(min(max(0, anchor), end))
        cursor.setPosition(
            min(max(0, position), end),
            QTextCursor.MoveMode.KeepAnchor,
        )
        self.editor.setTextCursor(cursor)
        self.editor.verticalScrollBar().setValue(max(0, scroll_y))

    def jump_to_page(self, page_index: int) -> None:
        snapshot = self.editor.pagination_snapshot()
        target = max(0, min(page_index, snapshot.page_count - 1))
        try:
            block_number = snapshot.block_pages.index(target)
        except ValueError:
            block_number = max(0, len(snapshot.block_pages) - 1)
        block = self.editor.document().findBlockByNumber(block_number)
        cursor = QTextCursor(block)
        self.editor.setTextCursor(cursor)
        self.editor.ensureCursorVisible()
        self.editor.setFocus()

    def _emit_page_status(self, _page_count: int | None = None) -> None:
        self.page_status_changed.emit(self.current_page, self.editor.page_count)
