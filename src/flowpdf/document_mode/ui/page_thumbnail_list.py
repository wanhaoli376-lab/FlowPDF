from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt, QTimer
from PySide6.QtGui import QCloseEvent, QIcon, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QListWidget, QListWidgetItem

from flowpdf.document_mode.editing import PaginatedTextEdit


class DocumentPageList(QListWidget):
    """Debounced, visible-page-only thumbnails for the live reflowable document."""

    def __init__(self, editor: PaginatedTextEdit, parent=None) -> None:
        super().__init__(parent)
        self._editor = editor
        self._rendered_pages: set[int] = set()
        self._pending_pages: list[int] = []
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(240)
        self._refresh_timer.timeout.connect(self._refresh_visible)
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.timeout.connect(self._render_next)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setIconSize(QSize(136, 176))
        self.setSpacing(8)
        self.setUniformItemSizes(True)
        self.verticalScrollBar().valueChanged.connect(self.schedule_refresh)
        editor.model_changed.connect(self.schedule_refresh)
        editor.presentation_changed.connect(self._sync_from_editor)

    def set_page_count(self, count: int) -> None:
        selected = max(1, count)
        if selected == self.count():
            self.schedule_refresh()
            return
        current = min(max(0, self.currentRow()), selected - 1)
        blocked = self.blockSignals(True)
        self.clear()
        self._rendered_pages.clear()
        self._pending_pages.clear()
        self._render_timer.stop()
        for page_index in range(selected):
            item = QListWidgetItem(f"第 {page_index + 1} 页")
            item.setData(Qt.ItemDataRole.UserRole, page_index)
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            item.setSizeHint(QSize(164, 212))
            self.addItem(item)
        self.setCurrentRow(current)
        self.blockSignals(blocked)
        self.schedule_refresh()

    def select_page(self, page_index: int) -> None:
        if not 0 <= page_index < self.count():
            return
        blocked = self.blockSignals(True)
        self.setCurrentRow(page_index)
        self.blockSignals(blocked)
        self.scrollToItem(
            self.item(page_index),
            QAbstractItemView.ScrollHint.EnsureVisible,
        )
        self.schedule_refresh()

    def clear_document(self) -> None:
        self._refresh_timer.stop()
        self._render_timer.stop()
        self._pending_pages.clear()
        self._rendered_pages.clear()
        self.clear()

    def schedule_refresh(self) -> None:
        if self.count():
            self._render_timer.stop()
            self._pending_pages.clear()
            self._refresh_timer.start()

    def viewportEvent(self, event: QEvent) -> bool:
        result = super().viewportEvent(event)
        if event.type() in {QEvent.Type.Show, QEvent.Type.Resize}:
            self.schedule_refresh()
        return result

    def closeEvent(self, event: QCloseEvent) -> None:
        self._refresh_timer.stop()
        self._render_timer.stop()
        super().closeEvent(event)

    def _sync_from_editor(self) -> None:
        if not self._editor.has_flow_document:
            self.clear_document()
            return
        self.set_page_count(self._editor.page_count)

    def _refresh_visible(self) -> None:
        if not self.count():
            return
        top = self.indexAt(self.viewport().rect().topLeft()).row()
        bottom = self.indexAt(self.viewport().rect().bottomLeft()).row()
        if top < 0:
            top = max(0, self.currentRow())
        if bottom < 0:
            bottom = min(self.count() - 1, top + 5)
        first = max(0, top - 1)
        last = min(self.count() - 1, bottom + 1)
        desired = set(range(first, last + 1))
        for page_index in self._rendered_pages - desired:
            if 0 <= page_index < self.count():
                self.item(page_index).setIcon(QIcon())
        current = max(first, min(last, self.currentRow()))
        self._pending_pages = sorted(desired, key=lambda page: (abs(page - current), page))
        self._rendered_pages.intersection_update(desired)
        self._render_timer.start(0)

    def _render_next(self) -> None:
        if not self._pending_pages or not self._editor.has_flow_document:
            return
        page_index = self._pending_pages.pop(0)
        if 0 <= page_index < self.count() and page_index < self._editor.page_count:
            item = self.item(page_index)
            image = self._editor.render_page_thumbnail(page_index, self.iconSize())
            item.setIcon(QIcon(QPixmap.fromImage(image)))
            self._rendered_pages.add(page_index)
        if self._pending_pages:
            self._render_timer.start(0)
