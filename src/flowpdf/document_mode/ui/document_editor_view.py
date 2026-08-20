from __future__ import annotations

from PySide6.QtCore import QElapsedTimer, QEvent, QPointF, QRectF, QSizeF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QGuiApplication,
    QMouseEvent,
    QResizeEvent,
    QShowEvent,
    QTextCursor,
    QTransform,
)
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

    visible_page_changed = Signal(int)

    def __init__(self, editor: PaginatedTextEdit, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.editor = editor
        self._zoom_factor = 1.0
        self._visible_page = 0
        self._selection_anchor: int | None = None
        self._drag_viewport_position: QPointF | None = None
        self._double_click_timer = QElapsedTimer()
        self._double_click_position = QPointF()
        self._autoscroll_timer = QTimer(self)
        self._autoscroll_timer.setInterval(32)
        self._autoscroll_timer.timeout.connect(self._auto_scroll_selection)
        self._viewport_update_timer = QTimer(self)
        self._viewport_update_timer.setSingleShot(True)
        self._viewport_update_timer.timeout.connect(self._viewport_changed)
        scene = QGraphicsScene(self)
        self._proxy = scene.addWidget(editor)
        self.setScene(scene)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        editor.zoom_changed.connect(self.set_zoom_factor)
        editor.presentation_changed.connect(self._presentation_changed)
        editor.cursor_visibility_requested.connect(self._ensure_cursor_visible)
        editor.wheel_scroll_requested.connect(self._scroll_from_wheel)
        editor.cursorPositionChanged.connect(self._update_input_method_geometry)
        self.horizontalScrollBar().valueChanged.connect(self._viewport_changed)
        self.verticalScrollBar().valueChanged.connect(self._viewport_changed)
        editor.installEventFilter(self)
        self._resize_proxy()

    @property
    def visible_page(self) -> int:
        return self._visible_page

    def set_zoom_factor(self, factor: float) -> None:
        self._zoom_factor = factor
        self.resetTransform()
        self.scale(factor, factor)
        self._resize_proxy()
        self._viewport_changed()

    def fit_width(self) -> None:
        factor = self.editor.page_presentation.fit_width_factor(QSizeF(self.viewport().size()))
        self.editor.set_zoom_factor(factor)

    def fit_page(self) -> None:
        factor = self.editor.page_presentation.fit_page_factor(QSizeF(self.viewport().size()))
        self.editor.set_zoom_factor(factor)

    def scroll_to_page(self, page_index: int) -> None:
        selected = max(0, min(self.editor.page_count - 1, page_index))
        self.centerOn(self.editor.page_presentation.paper_rect(selected).center())
        self._set_visible_page(selected)
        self._update_input_method_geometry()

    def reset_document_view(self) -> None:
        self.horizontalScrollBar().setValue(0)
        self.verticalScrollBar().setValue(0)
        self._set_visible_page(0)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._resize_proxy()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._viewport_update_timer.start(0)

    def eventFilter(self, watched, event: QEvent) -> bool:
        if watched is self.editor and event.type() == QEvent.Type.FocusIn:
            self._viewport_update_timer.start(0)
        elif watched is self.editor and event.type() == QEvent.Type.FocusOut:
            self._release_input_method_geometry()
        return super().eventFilter(watched, event)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return
        editor_position = self._editor_position(event.position())
        if self._is_triple_click(event.position()) and self.editor.select_paragraph_at_visual(
            editor_position
        ):
            self.editor.setFocus(Qt.FocusReason.MouseFocusReason)
            event.accept()
            return
        if not self.editor.place_cursor_at_visual(
            editor_position,
            keep_anchor=bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier),
        ):
            super().mousePressEvent(event)
            return
        self.editor.setFocus(Qt.FocusReason.MouseFocusReason)
        self._selection_anchor = self.editor.textCursor().anchor()
        self._drag_viewport_position = event.position()
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        dragging = bool(
            self._selection_anchor is not None and event.buttons() & Qt.MouseButton.LeftButton
        )
        if dragging:
            self._drag_viewport_position = event.position()
        if not dragging:
            super().mouseMoveEvent(event)
            return
        if self._drag_scroll_delta():
            self._autoscroll_timer.start()
        else:
            self._autoscroll_timer.stop()
        self._extend_drag_selection()
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._autoscroll_timer.stop()
            self._selection_anchor = None
            self._drag_viewport_position = None
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.editor.select_word_at_visual(
            self._editor_position(event.position())
        ):
            self.editor.setFocus(Qt.FocusReason.MouseFocusReason)
            self._double_click_position = event.position()
            self._double_click_timer.start()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def _resize_proxy(self) -> None:
        size = self.editor.page_presentation.visual_size
        self.editor.setFixedSize(size.toSize())
        self._proxy.resize(size)
        self.scene().setSceneRect(self._proxy.boundingRect())
        self._set_visible_page(self._visible_page)
        self._viewport_update_timer.start(0)

    def _presentation_changed(self) -> None:
        self._resize_proxy()
        if self.editor.hasFocus():
            self._viewport_update_timer.stop()
            self._ensure_cursor_visible(self.editor.visual_cursor_rect())

    def _ensure_cursor_visible(self, rect) -> None:
        if self._autoscroll_timer.isActive():
            return
        self.ensureVisible(rect, 36, 36)
        self._set_visible_page(self.editor.current_page)
        self._update_input_method_geometry()

    def _scroll_from_wheel(self, delta_x: int, delta_y: int) -> None:
        if delta_y:
            bar = self.verticalScrollBar()
            bar.setValue(bar.value() - delta_y)
        if delta_x:
            bar = self.horizontalScrollBar()
            bar.setValue(bar.value() - delta_x)

    def _viewport_changed(self, _value: int | None = None) -> None:
        if self.scene() is None:
            return
        center = self.mapToScene(self.viewport().rect().center())
        local = self._proxy.mapFromScene(center)
        page = self.editor.page_presentation.page_for_visual_y(local.y())
        self._set_visible_page(page)
        self._update_input_method_geometry()

    def _set_visible_page(self, page_index: int) -> None:
        selected = max(0, min(self.editor.page_count - 1, page_index))
        self.editor.set_active_page(selected)
        if selected == self._visible_page:
            return
        self._visible_page = selected
        self.visible_page_changed.emit(selected)

    def _update_input_method_geometry(self) -> None:
        if not self.editor.hasFocus():
            return
        origin_in_viewport = self.mapFromScene(self._proxy.mapToScene(QPointF(0, 0)))
        origin_in_window = self.viewport().mapTo(self.window(), origin_in_viewport)
        transform = QTransform()
        transform.translate(origin_in_window.x(), origin_in_window.y())
        transform.scale(self.transform().m11(), self.transform().m22())
        input_method = QGuiApplication.inputMethod()
        input_method.setInputItemRectangle(QRectF(self.editor.rect()))
        input_method.setInputItemTransform(transform)
        input_method.update(Qt.InputMethodQuery.ImCursorRectangle)

    @staticmethod
    def _release_input_method_geometry() -> None:
        input_method = QGuiApplication.inputMethod()
        input_method.setInputItemRectangle(QRectF())
        input_method.setInputItemTransform(QTransform())

    def _drag_scroll_delta(self) -> int:
        if self._drag_viewport_position is None:
            return 0
        edge = 34.0
        y = self._drag_viewport_position.y()
        height = self.viewport().height()
        if y < edge:
            return -max(8, round((edge - y) * 0.8))
        if y > height - edge:
            return max(8, round((y - (height - edge)) * 0.8))
        return 0

    def _auto_scroll_selection(self) -> None:
        delta = self._drag_scroll_delta()
        if not delta:
            self._autoscroll_timer.stop()
            return
        bar = self.verticalScrollBar()
        previous = bar.value()
        bar.setValue(previous + delta)
        if bar.value() == previous:
            self._autoscroll_timer.stop()
            return
        self._extend_drag_selection()

    def _extend_drag_selection(self) -> None:
        if self._drag_viewport_position is None or self._selection_anchor is None:
            return
        scene_position = self.mapToScene(self._drag_viewport_position.toPoint())
        editor_position = self._proxy.mapFromScene(scene_position)
        self.editor.extend_selection_to_visual(editor_position, self._selection_anchor)

    def _editor_position(self, viewport_position: QPointF) -> QPointF:
        return self._proxy.mapFromScene(self.mapToScene(viewport_position.toPoint()))

    def _is_triple_click(self, viewport_position: QPointF) -> bool:
        if not self._double_click_timer.isValid():
            return False
        elapsed = self._double_click_timer.elapsed()
        distance = (viewport_position - self._double_click_position).manhattanLength()
        style_hints = QGuiApplication.styleHints()
        selected = (
            elapsed <= style_hints.mouseDoubleClickInterval()
            and distance <= style_hints.startDragDistance()
        )
        self._double_click_timer.invalidate()
        return selected


class DocumentEditorView(QWidget):
    """Continuous document-mode surface backed by exactly one QTextDocument."""

    page_status_changed = Signal(int, int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.editor = PaginatedTextEdit(self)
        self.editor.setObjectName("documentModeTextEdit")
        self.editor.setStyleSheet(
            "QTextEdit#documentModeTextEdit {"
            "background: #e5e7eb; color: #111827; border: 0;"
            "selection-background-color: #bfdbfe;"
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
        self.editor_canvas.visible_page_changed.connect(self._emit_page_status)

    @property
    def current_page(self) -> int:
        return self.editor_canvas.visible_page

    @property
    def scroll_y(self) -> int:
        return self.editor_canvas.verticalScrollBar().value()

    def set_document(self, document: FlowDocument, report: ImportReport | None = None) -> None:
        self.editor.set_flow_document(document)
        self.editor_canvas.reset_document_view()
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
        self.editor.clearFocus()
        self.editor.clear_flow_document()
        self.editor_canvas.reset_document_view()
        self.import_notice.hide()

    def fit_width(self) -> None:
        self.editor_canvas.fit_width()

    def fit_page(self) -> None:
        self.editor_canvas.fit_page()

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
        self.editor_canvas.verticalScrollBar().setValue(max(0, scroll_y))

    def jump_to_page(self, page_index: int) -> None:
        target = max(0, min(page_index, self.editor.page_count - 1))
        logical_y = target * self.editor.page_geometry.content_height_px + 1.0
        position = (
            self.editor.document()
            .documentLayout()
            .hitTest(
                QPointF(self.editor.page_geometry.content_width_px / 2, logical_y),
                Qt.HitTestAccuracy.FuzzyHit,
            )
        )
        cursor = QTextCursor(self.editor.document())
        end = max(0, self.editor.document().characterCount() - 1)
        cursor.setPosition(min(max(0, position), end))
        self.editor.setTextCursor(cursor)
        self.editor_canvas.scroll_to_page(target)
        self.editor.setFocus()

    def _emit_page_status(self, _page_count: int | None = None) -> None:
        self.page_status_changed.emit(self.current_page, self.editor.page_count)
