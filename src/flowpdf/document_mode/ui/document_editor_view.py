from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QResizeEvent, QTextCursor
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsScene,
    QGraphicsView,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from flowpdf.document_mode.editing import PaginatedTextEdit
from flowpdf.document_mode.importing import ImportReport
from flowpdf.document_mode.models import FlowDocument


class _ZoomableEditorCanvas(QGraphicsView):
    """Scale the complete editor widget so text, images, margins and cursors stay aligned."""

    def __init__(self, editor: PaginatedTextEdit, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.editor = editor
        self._zoom_factor = 1.0
        scene = QGraphicsScene(self)
        self._proxy = scene.addWidget(editor)
        self.setScene(scene)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        editor.zoom_changed.connect(self.set_zoom_factor)

    def set_zoom_factor(self, factor: float) -> None:
        self._zoom_factor = factor
        self.resetTransform()
        self.scale(factor, factor)
        self._resize_proxy()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._resize_proxy()

    def _resize_proxy(self) -> None:
        viewport = self.viewport().size()
        width = max(1.0, viewport.width() / self._zoom_factor)
        height = max(1.0, viewport.height() / self._zoom_factor)
        self._proxy.resize(width, height)
        self.scene().setSceneRect(self._proxy.boundingRect())


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
        self.editor_canvas = _ZoomableEditorCanvas(self.editor, self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(38, 20, 38, 20)
        layout.setSpacing(10)
        layout.addWidget(self.import_notice)
        layout.addWidget(self.editor_canvas, 1)
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
                if report.recommended_mode in {"document", "document_with_warning"}
                else "复杂版式，建议改用版面编辑模式"
            )
            warning = f"；{report.warnings[0]}" if report.warnings else ""
            self.import_notice.setText(f"导入质量 {report.score}/100 · {recommendation}{warning}")
            self.import_notice.show()
        self._emit_page_status()

    def clear_document(self) -> None:
        self.editor.clear()
        self.import_notice.hide()

    def restore_cursor(
        self,
        position: int,
        anchor: int,
        scroll_y: int,
        zoom_factor: float = 1.0,
    ) -> None:
        self.editor.set_zoom_factor(zoom_factor)
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
