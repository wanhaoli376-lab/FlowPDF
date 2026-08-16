from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QCloseEvent,
    QDragEnterEvent,
    QDropEvent,
    QIcon,
    QImage,
    QPixmap,
)
from PySide6.QtWidgets import QAbstractItemView, QListWidget, QListWidgetItem, QMenu

from flowpdf.backends.base import PageInfo
from flowpdf.rendering.render_scheduler import RenderPriority, RenderScheduler, RenderSource
from flowpdf.rendering.tile_cache import TileKey


class ThumbnailPanel(QListWidget):
    """Virtualized thumbnail list with page management drop signals."""

    page_activated = Signal(int)
    pages_selected = Signal(list)
    page_move_requested = Signal(int, int)
    insert_pdf_requested = Signal(str, int)
    delete_requested = Signal(list)
    duplicate_requested = Signal(list)
    rotate_requested = Signal(list)
    export_requested = Signal(list)
    insert_blank_requested = Signal(int)

    def __init__(self, scheduler: RenderScheduler, parent=None) -> None:
        super().__init__(parent)
        self.scheduler = scheduler
        self._source: RenderSource | None = None
        self._infos: list[PageInfo] = []
        self._revision = 0
        self._owner = f"thumbnail-panel-{id(self)}"
        self._schedule_timer = QTimer(self)
        self._schedule_timer.setSingleShot(True)
        self._schedule_timer.setInterval(40)
        self._schedule_timer.timeout.connect(self._schedule_visible)

        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setIconSize(QSize(136, 176))
        self.setSpacing(8)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.itemActivated.connect(self._emit_activated)
        self.currentRowChanged.connect(self._emit_current)
        self.itemSelectionChanged.connect(self._emit_selection)
        self.verticalScrollBar().valueChanged.connect(self._queue_schedule)
        self.scheduler.tile_ready.connect(self._on_tile_ready)

    def set_document(
        self,
        source: RenderSource,
        infos: list[PageInfo],
        *,
        revision: int = 0,
    ) -> None:
        self.scheduler.cancel_owner_obsolete(self._owner, set())
        self._source = source
        self._infos = list(infos)
        self._revision = revision
        self.clear()
        for index, info in enumerate(infos):
            item = QListWidgetItem(f"第 {index + 1} 页")
            item.setData(Qt.ItemDataRole.UserRole, index)
            ratio = info.height / max(1.0, info.width)
            item.setSizeHint(QSize(164, min(220, int(150 * ratio) + 36)))
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter)
            self.addItem(item)
        if infos:
            self.setCurrentRow(0)
        self._queue_schedule()

    def clear_document(self) -> None:
        self.scheduler.cancel_owner_obsolete(self._owner, set())
        self._source = None
        self._infos.clear()
        self.clear()

    def selected_pages(self) -> list[int]:
        return sorted(int(item.data(Qt.ItemDataRole.UserRole)) for item in self.selectedItems())

    def select_page(self, page_index: int) -> None:
        if 0 <= page_index < self.count():
            self.setCurrentRow(page_index)
            self.scrollToItem(self.item(page_index), QAbstractItemView.ScrollHint.PositionAtCenter)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._has_pdf_urls(event.mimeData()) or event.source() is self:
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if self._has_pdf_urls(event.mimeData()) or event.source() is self:
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        target = self.indexAt(event.position().toPoint()).row()
        if target < 0:
            target = self.count()
        if self._has_pdf_urls(event.mimeData()):
            for url in event.mimeData().urls():
                path = Path(url.toLocalFile())
                if path.suffix.casefold() == ".pdf":
                    self.insert_pdf_requested.emit(str(path), target)
                    target += 1
            event.acceptProposedAction()
            return
        if event.source() is self:
            selected = self.selected_pages()
            if len(selected) == 1:
                old = selected[0]
                adjusted = target - 1 if target > old else target
                adjusted = max(0, min(self.count() - 1, adjusted))
                if adjusted != old:
                    self.page_move_requested.emit(old, adjusted)
                event.acceptProposedAction()
                return
        super().dropEvent(event)

    def viewportEvent(self, event: QEvent) -> bool:
        result = super().viewportEvent(event)
        if event.type() in {QEvent.Type.Show, QEvent.Type.Resize}:
            self._queue_schedule()
        return result

    def closeEvent(self, event: QCloseEvent) -> None:
        self._schedule_timer.stop()
        self.clear_document()
        super().closeEvent(event)

    def _queue_schedule(self) -> None:
        if self._source is not None:
            self._schedule_timer.start()

    def _schedule_visible(self) -> None:
        if self._source is None or not self._infos:
            return
        top = self.indexAt(self.viewport().rect().topLeft()).row()
        bottom = self.indexAt(self.viewport().rect().bottomLeft()).row()
        if top < 0:
            top = max(0, self.currentRow())
        if bottom < 0:
            bottom = min(len(self._infos) - 1, top + 6)
        desired: set[TileKey] = set()
        for index in range(max(0, top - 2), min(len(self._infos), bottom + 3)):
            info = self._infos[index]
            logical_scale = min(136 / info.width, 176 / info.height)
            scale = max(0.1, round(logical_scale * self.devicePixelRatioF() * 20) / 20)
            key = TileKey(
                self._source.document_id,
                index,
                scale,
                info.rotation,
                None,
                self._revision,
                "thumbnail",
            )
            desired.add(key)
            self.scheduler.request(
                self._source,
                key,
                owner=self._owner,
                priority=RenderPriority.THUMBNAIL,
            )
        self.scheduler.cancel_owner_obsolete(self._owner, desired)

    def _on_tile_ready(self, key: TileKey, rendered) -> None:
        if (
            self._source is None
            or key.document_id != self._source.document_id
            or key.revision != self._revision
            or key.purpose != "thumbnail"
            or not 0 <= key.page_index < self.count()
        ):
            return
        image = QImage(
            rendered.samples,
            rendered.width,
            rendered.height,
            rendered.stride,
            QImage.Format.Format_RGB888,
        ).copy()
        pixmap = QPixmap.fromImage(image)
        self.item(key.page_index).setIcon(QIcon(pixmap))

    def _emit_activated(self, item: QListWidgetItem) -> None:
        self.page_activated.emit(int(item.data(Qt.ItemDataRole.UserRole)))

    def _emit_current(self, row: int) -> None:
        if row >= 0:
            self.page_activated.emit(row)

    def _emit_selection(self) -> None:
        self.pages_selected.emit(self.selected_pages())

    def _show_context_menu(self, position) -> None:
        pages = self.selected_pages()
        if not pages:
            return
        menu = QMenu(self)
        actions: list[tuple[str, Signal]] = [
            ("复制页面", self.duplicate_requested),
            ("顺时针旋转", self.rotate_requested),
            ("导出所选页面", self.export_requested),
            ("删除页面", self.delete_requested),
        ]
        for text, signal in actions:
            action = QAction(text, menu)
            action.triggered.connect(lambda _checked=False, s=signal: s.emit(pages))
            menu.addAction(action)
        menu.addSeparator()
        insert = QAction("在此处插入空白页", menu)
        insert.triggered.connect(lambda: self.insert_blank_requested.emit(pages[0]))
        menu.addAction(insert)
        menu.exec(self.viewport().mapToGlobal(position))

    @staticmethod
    def _has_pdf_urls(mime_data) -> bool:
        return mime_data.hasUrls() and any(
            Path(url.toLocalFile()).suffix.casefold() == ".pdf" for url in mime_data.urls()
        )
