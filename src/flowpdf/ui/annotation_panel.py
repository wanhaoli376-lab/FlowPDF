from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QKeyEvent
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QMenu

from flowpdf.backends.base import AnnotationInfo, AnnotationKind

_KIND_LABELS = {
    AnnotationKind.HIGHLIGHT: "高亮",
    AnnotationKind.UNDERLINE: "下划线",
    AnnotationKind.STRIKEOUT: "删除线",
    AnnotationKind.NOTE: "便签",
    AnnotationKind.FREE_TEXT: "文字批注",
    AnnotationKind.INK: "手写",
    AnnotationKind.LINE: "直线",
    AnnotationKind.ARROW: "箭头",
    AnnotationKind.RECTANGLE: "矩形",
    AnnotationKind.ELLIPSE: "椭圆",
}


class AnnotationPanel(QListWidget):
    annotation_activated = Signal(int, int)
    delete_requested = Signal(int, int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAlternatingRowColors(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.itemActivated.connect(self._activate_item)

    def set_annotations(self, annotations: list[AnnotationInfo]) -> None:
        self.clear()
        for annotation in annotations:
            label = _KIND_LABELS.get(annotation.kind, annotation.kind.value)
            summary = " ".join(annotation.content.split())
            text = f"第 {annotation.page_index + 1} 页 · {label}"
            if summary:
                text += f"\n{summary[:80]}"
            item = QListWidgetItem(text, self)
            item.setData(
                Qt.ItemDataRole.UserRole,
                (annotation.page_index, annotation.xref),
            )
            item.setToolTip(summary)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Delete and self.currentItem() is not None:
            self._emit_delete()
            event.accept()
            return
        super().keyPressEvent(event)

    def _activate_item(self, item: QListWidgetItem) -> None:
        page, xref = item.data(Qt.ItemDataRole.UserRole)
        self.annotation_activated.emit(int(page), int(xref))

    def _emit_delete(self) -> None:
        item = self.currentItem()
        if item is None:
            return
        page, xref = item.data(Qt.ItemDataRole.UserRole)
        self.delete_requested.emit(int(page), int(xref))

    def _show_context_menu(self, position) -> None:
        if self.itemAt(position) is None:
            return
        menu = QMenu(self)
        delete = QAction("删除批注", menu)
        delete.triggered.connect(self._emit_delete)
        menu.addAction(delete)
        menu.exec(self.viewport().mapToGlobal(position))
