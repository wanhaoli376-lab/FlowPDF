from __future__ import annotations

from collections import defaultdict

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPen, QPixmap
from PySide6.QtWidgets import (
    QGraphicsPixmapItem,
    QGraphicsRectItem,
    QGraphicsScene,
)

from flowpdf.backends.base import PageInfo, RenderedPage, SearchHit
from flowpdf.rendering.tile_cache import TileKey
from flowpdf.utils.coordinates import PageTransform, Point, Rect


class PageGraphicsItem(QGraphicsRectItem):
    """A lightweight page placeholder with separate raster and overlay children."""

    def __init__(self, page_index: int, info: PageInfo) -> None:
        super().__init__(0, 0, info.width, info.height)
        self.page_index = page_index
        self.info = info
        self.setBrush(QColor("white"))
        self.setPen(QPen(QColor("#B9BEC7"), 0))
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemClipsChildrenToShape, True)
        self._rasters: dict[TileKey, QGraphicsPixmapItem] = {}
        self._search_items: list[QGraphicsRectItem] = []

    @property
    def raster_keys(self) -> frozenset[TileKey]:
        return frozenset(self._rasters)

    def pdf_rect_to_local(self, rect: Rect) -> QRectF:
        transformed = self._local_transform().pdf_rect_to_scene(rect)
        return QRectF(
            transformed.x0,
            transformed.y0,
            transformed.width,
            transformed.height,
        )

    def scene_rect_to_pdf(self, rect: QRectF) -> Rect:
        transform = self._scene_transform()
        return transform.scene_rect_to_pdf(
            Rect(rect.left(), rect.top(), rect.right(), rect.bottom())
        )

    def scene_point_to_pdf(self, x: float, y: float) -> Point:
        return self._scene_transform().scene_to_pdf(Point(x, y))

    def apply_render(self, key: TileKey, rendered: RenderedPage) -> None:
        image = QImage(
            rendered.samples,
            rendered.width,
            rendered.height,
            rendered.stride,
            QImage.Format.Format_RGB888,
        ).copy()
        pixmap = QPixmap.fromImage(image)

        if key.tile is None:
            for old_key in [item_key for item_key in self._rasters if item_key.tile is None]:
                self._remove_raster(old_key)
        else:
            for old_key in [
                item_key
                for item_key in self._rasters
                if item_key.tile == key.tile and item_key != key
            ]:
                self._remove_raster(old_key)

        raster = QGraphicsPixmapItem(pixmap, self)
        raster.setOffset(rendered.clip.x0, rendered.clip.y0)
        raster.setScale(1.0 / rendered.scale)
        raster.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        raster.setZValue(2 if key.tile is not None else 1)
        self._rasters[key] = raster

    def clear_rasters(self) -> None:
        for key in tuple(self._rasters):
            self._remove_raster(key)

    def set_search_hits(self, hits: list[SearchHit], current: SearchHit | None) -> None:
        for item in self._search_items:
            if item.scene() is not None:
                item.scene().removeItem(item)
        self._search_items.clear()
        for hit in hits:
            rect = self.pdf_rect_to_local(hit.rect)
            overlay = QGraphicsRectItem(rect, self)
            is_current = current == hit
            overlay.setBrush(QColor(255, 145 if is_current else 210, 0, 130 if is_current else 80))
            overlay.setPen(QPen(QColor("#F97316" if is_current else "#EAB308"), 1.0))
            overlay.setZValue(20)
            self._search_items.append(overlay)

    def _local_transform(self) -> PageTransform:
        crop = self.info.cropbox
        return PageTransform(
            page_width=crop.width,
            page_height=crop.height,
            rotation=self.info.rotation,
            crop_origin=Point(crop.x0, crop.y0),
        )

    def _scene_transform(self) -> PageTransform:
        crop = self.info.cropbox
        position = self.scenePos()
        return PageTransform(
            page_width=crop.width,
            page_height=crop.height,
            rotation=self.info.rotation,
            scene_origin=Point(position.x(), position.y()),
            crop_origin=Point(crop.x0, crop.y0),
        )

    def _remove_raster(self, key: TileKey) -> None:
        item = self._rasters.pop(key, None)
        if item is not None and item.scene() is not None:
            item.scene().removeItem(item)


class PageScene(QGraphicsScene):
    page_gap = 24.0
    outer_margin = 32.0

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setBackgroundBrush(QColor("#E7E9ED"))
        self.pages: list[PageGraphicsItem] = []
        self._single_page: int | None = None

    def set_pages(self, page_infos: list[PageInfo]) -> None:
        self.clear()
        self.pages = [PageGraphicsItem(index, info) for index, info in enumerate(page_infos)]
        for item in self.pages:
            self.addItem(item)
        self._single_page = None
        self._layout_continuous()

    def clear_pages(self) -> None:
        self.clear()
        self.pages.clear()
        self._single_page = None

    def set_single_page(self, page_index: int | None) -> None:
        self._single_page = page_index
        if page_index is None:
            for page in self.pages:
                page.setVisible(True)
            self._layout_continuous()
            return
        for page in self.pages:
            page.setVisible(page.page_index == page_index)
        if 0 <= page_index < len(self.pages):
            rect = (
                self.pages[page_index]
                .sceneBoundingRect()
                .adjusted(
                    -self.outer_margin,
                    -self.outer_margin,
                    self.outer_margin,
                    self.outer_margin,
                )
            )
            self.setSceneRect(rect)

    def apply_render(self, key: TileKey, rendered: RenderedPage) -> None:
        if 0 <= key.page_index < len(self.pages):
            self.pages[key.page_index].apply_render(key, rendered)

    def clear_rasters(self) -> None:
        for page in self.pages:
            page.clear_rasters()

    def set_search_hits(self, hits: list[SearchHit], current_index: int | None) -> None:
        grouped: dict[int, list[SearchHit]] = defaultdict(list)
        for hit in hits:
            grouped[hit.page_index].append(hit)
        current = hits[current_index] if current_index is not None and hits else None
        for page in self.pages:
            page.set_search_hits(grouped.get(page.page_index, []), current)

    def page_at(self, scene_x: float, scene_y: float) -> int | None:
        for page in self.pages:
            if page.isVisible() and page.sceneBoundingRect().contains(scene_x, scene_y):
                return page.page_index
        return None

    def _layout_continuous(self) -> None:
        if not self.pages:
            self.setSceneRect(QRectF())
            return
        max_width = max(page.info.width for page in self.pages)
        y = self.outer_margin
        for page in self.pages:
            x = self.outer_margin + (max_width - page.info.width) / 2
            page.setPos(x, y)
            y += page.info.height + self.page_gap
        self.setSceneRect(
            0,
            0,
            max_width + 2 * self.outer_margin,
            y - self.page_gap + self.outer_margin,
        )
