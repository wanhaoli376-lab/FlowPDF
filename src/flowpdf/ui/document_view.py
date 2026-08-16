from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QCloseEvent,
    QKeyEvent,
    QPainter,
    QResizeEvent,
    QTransform,
    QWheelEvent,
)
from PySide6.QtWidgets import QGraphicsView

from flowpdf.backends.base import PageInfo, SearchHit
from flowpdf.rendering.render_scheduler import RenderPriority, RenderScheduler, RenderSource
from flowpdf.rendering.tile_cache import TileKey
from flowpdf.ui.page_scene import PageScene


class DocumentView(QGraphicsView):
    """Virtualized continuous/single-page view with progressive tiled rendering."""

    current_page_changed = Signal(int)
    zoom_changed = Signal(float)
    escape_pressed = Signal()

    def __init__(self, scheduler: RenderScheduler, parent=None) -> None:
        super().__init__(parent)
        self.page_scene = PageScene(self)
        self.setScene(self.page_scene)
        self.scheduler = scheduler
        self.scheduler.tile_ready.connect(self._on_tile_ready)
        self.scheduler.tile_failed.connect(self._on_tile_failed)
        self._source: RenderSource | None = None
        self._page_infos: list[PageInfo] = []
        self._revision = 0
        self._zoom = 1.0
        self._current_page = 0
        self._continuous = True
        self._last_error = ""
        self._owner = f"document-view-{id(self)}"

        self.setRenderHints(
            self.renderHints()
            | QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.MinimalViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._schedule_timer = QTimer(self)
        self._schedule_timer.setSingleShot(True)
        self._schedule_timer.setInterval(25)
        self._schedule_timer.timeout.connect(self._schedule_visible)
        self.horizontalScrollBar().valueChanged.connect(self._queue_schedule)
        self.verticalScrollBar().valueChanged.connect(self._queue_schedule)

    @property
    def zoom(self) -> float:
        return self._zoom

    @property
    def current_page(self) -> int:
        return self._current_page

    @property
    def continuous_mode(self) -> bool:
        return self._continuous

    @property
    def last_render_error(self) -> str:
        return self._last_error

    def set_document(
        self,
        source: RenderSource,
        page_infos: list[PageInfo],
        *,
        revision: int = 0,
    ) -> None:
        self.scheduler.cancel_owner_obsolete(self._owner, set())
        self._source = source
        self._page_infos = list(page_infos)
        self._revision = revision
        self._current_page = 0
        self.page_scene.set_pages(page_infos)
        self.set_zoom(1.0)
        self._queue_schedule()

    def update_snapshot(
        self,
        source: RenderSource,
        page_infos: list[PageInfo] | None = None,
        *,
        revision: int,
    ) -> None:
        self.scheduler.cancel_owner_obsolete(self._owner, set())
        self._source = source
        self._revision = revision
        self.page_scene.clear_rasters()
        if page_infos is not None:
            self._page_infos = list(page_infos)
            self.page_scene.set_pages(page_infos)
            self._current_page = min(self._current_page, max(0, len(page_infos) - 1))
        self._queue_schedule()

    def clear_document(self) -> None:
        self.scheduler.cancel_owner_obsolete(self._owner, set())
        self._source = None
        self._page_infos.clear()
        self.page_scene.clear_pages()

    def set_continuous_mode(self, continuous: bool) -> None:
        if self._continuous == continuous:
            return
        self._continuous = continuous
        self.page_scene.set_single_page(None if continuous else self._current_page)
        self._queue_schedule()

    def set_zoom(self, zoom: float) -> None:
        self._apply_zoom(zoom, under_mouse=False)

    def _apply_zoom(self, zoom: float, *, under_mouse: bool) -> None:
        bounded = max(0.1, min(8.0, zoom))
        if math.isclose(bounded, self._zoom, rel_tol=1e-6) and not self.transform().isIdentity():
            return
        self._zoom = bounded
        scale = self._base_scale() * bounded
        old_anchor = self.transformationAnchor()
        self.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse
            if under_mouse
            else QGraphicsView.ViewportAnchor.AnchorViewCenter
        )
        self.setTransform(QTransform.fromScale(scale, scale))
        self.setTransformationAnchor(old_anchor)
        self.zoom_changed.emit(self._zoom)
        self._queue_schedule()

    def zoom_in(self) -> None:
        self.set_zoom(self._zoom * 1.2)

    def zoom_out(self) -> None:
        self.set_zoom(self._zoom / 1.2)

    def actual_size(self) -> None:
        self.set_zoom(1.0)

    def fit_page(self) -> None:
        if not self._page_infos:
            return
        info = self._page_infos[self._current_page]
        available_width = max(1, self.viewport().width() - 32)
        available_height = max(1, self.viewport().height() - 32)
        base = self._base_scale()
        self.set_zoom(
            min(available_width / (info.width * base), available_height / (info.height * base))
        )

    def fit_width(self) -> None:
        if not self._page_infos:
            return
        width = self._page_infos[self._current_page].width
        available = max(1, self.viewport().width() - 32)
        self.set_zoom(available / (width * self._base_scale()))

    def jump_to_page(self, page_index: int) -> None:
        if not 0 <= page_index < len(self.page_scene.pages):
            return
        self._set_current_page(page_index)
        if not self._continuous:
            self.page_scene.set_single_page(page_index)
        self.ensureVisible(self.page_scene.pages[page_index], 0, 16)
        self._queue_schedule()

    def show_search_hits(self, hits: list[SearchHit], current_index: int | None) -> None:
        self.page_scene.set_search_hits(hits, current_index)
        if current_index is not None and 0 <= current_index < len(hits):
            self.jump_to_page(hits[current_index].page_index)
            hit = hits[current_index]
            page = self.page_scene.pages[hit.page_index]
            rect = QRectF(hit.rect.x0, hit.rect.y0, hit.rect.width, hit.rect.height)
            self.ensureVisible(page.mapRectToScene(rect), 40, 40)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if event.angleDelta().y() > 0:
                self._apply_zoom(self._zoom * 1.2, under_mouse=True)
            elif event.angleDelta().y() < 0:
                self._apply_zoom(self._zoom / 1.2, under_mouse=True)
            event.accept()
            return
        super().wheelEvent(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.escape_pressed.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._queue_schedule()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._schedule_timer.stop()
        self.clear_document()
        super().closeEvent(event)

    def viewportEvent(self, event: QEvent) -> bool:
        result = super().viewportEvent(event)
        if event.type() is QEvent.Type.Show:
            self._queue_schedule()
        return result

    def _queue_schedule(self) -> None:
        if self._source is not None:
            self._schedule_timer.start()

    def _schedule_visible(self) -> None:
        if self._source is None or not self.page_scene.pages:
            return
        viewport_rect = self.mapToScene(self.viewport().rect()).boundingRect()
        visible: list[tuple[int, float]] = []
        for page in self.page_scene.pages:
            if not page.isVisible():
                continue
            intersection = viewport_rect.intersected(page.sceneBoundingRect())
            if not intersection.isEmpty():
                visible.append((page.page_index, intersection.width() * intersection.height()))
        if not visible:
            visible = [(self._current_page, 1.0)]
        current = max(visible, key=lambda item: item[1])[0]
        self._set_current_page(current)

        desired: set[TileKey] = set()
        visible_indices = {index for index, _area in visible}
        request_indices = set(visible_indices)
        if self._continuous:
            for index in tuple(visible_indices):
                request_indices.update(
                    candidate
                    for candidate in (index - 1, index + 1)
                    if 0 <= candidate < len(self._page_infos)
                )
        for page_index in sorted(request_indices):
            is_visible = page_index in visible_indices
            desired.update(self._request_page(page_index, viewport_rect, is_visible))
        self.scheduler.cancel_owner_obsolete(self._owner, desired)

    def _request_page(
        self,
        page_index: int,
        viewport_rect: QRectF,
        is_visible: bool,
    ) -> set[TileKey]:
        assert self._source is not None
        page_item = self.page_scene.pages[page_index]
        device_scale = self._base_scale() * self._zoom * self.devicePixelRatioF()
        render_scale = max(0.25, min(8.0, round(device_scale * 4) / 4))
        desired: set[TileKey] = set()

        if not is_visible:
            render_scale = min(0.75, render_scale)
            key = self._key(page_index, render_scale, None)
            desired.add(key)
            self.scheduler.request(
                self._source,
                key,
                owner=self._owner,
                priority=RenderPriority.ADJACENT,
            )
            return desired

        if render_scale <= 2.0:
            key = self._key(page_index, render_scale, None)
            desired.add(key)
            self.scheduler.request(
                self._source,
                key,
                owner=self._owner,
                priority=RenderPriority.VISIBLE,
            )
            return desired

        low_key = self._key(page_index, min(1.0, render_scale), None)
        desired.add(low_key)
        self.scheduler.request(
            self._source,
            low_key,
            owner=self._owner,
            priority=RenderPriority.CURRENT_PAGE,
        )
        local_visible = page_item.mapRectFromScene(viewport_rect).intersected(page_item.rect())
        tile_points = 512.0 / render_scale
        x_start = math.floor(local_visible.left() / tile_points) * tile_points
        y_start = math.floor(local_visible.top() / tile_points) * tile_points
        x = max(0.0, x_start)
        while x < local_visible.right():
            y = max(0.0, y_start)
            while y < local_visible.bottom():
                tile = (
                    round(x, 3),
                    round(y, 3),
                    round(min(page_item.info.width, x + tile_points), 3),
                    round(min(page_item.info.height, y + tile_points), 3),
                )
                key = self._key(page_index, render_scale, tile)
                desired.add(key)
                self.scheduler.request(
                    self._source,
                    key,
                    owner=self._owner,
                    priority=RenderPriority.VISIBLE,
                )
                y += tile_points
            x += tile_points
        return desired

    def _key(
        self,
        page_index: int,
        scale: float,
        tile: tuple[float, float, float, float] | None,
    ) -> TileKey:
        assert self._source is not None
        return TileKey(
            self._source.document_id,
            page_index,
            scale,
            self._page_infos[page_index].rotation,
            tile,
            self._revision,
            "page",
        )

    def _set_current_page(self, page_index: int) -> None:
        if page_index == self._current_page:
            return
        self._current_page = page_index
        self.current_page_changed.emit(page_index)

    def _on_tile_ready(self, key: TileKey, rendered) -> None:
        if (
            self._source is None
            or key.document_id != self._source.document_id
            or key.revision != self._revision
            or key.purpose != "page"
        ):
            return
        self.page_scene.apply_render(key, rendered)

    def _on_tile_failed(self, key: TileKey, message: str) -> None:
        if self._source is not None and key.document_id == self._source.document_id:
            self._last_error = message

    def _base_scale(self) -> float:
        screen = self.screen()
        dpi = screen.logicalDotsPerInchX() if screen is not None else 96.0
        return max(0.5, dpi / 72.0)
