from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, QSizeF

from flowpdf.document_mode.layout.page_geometry import PageGeometry


@dataclass(frozen=True, slots=True)
class PagePresentation:
    """Map one continuous text layout onto separated physical paper rectangles."""

    geometry: PageGeometry
    page_count: int
    page_gap_px: float = 28.0
    workspace_padding_px: float = 28.0
    _PAGE_EDGE_TOLERANCE_PX = 0.5

    def __post_init__(self) -> None:
        if self.page_count < 1:
            raise ValueError("页面数量至少为 1")
        if self.page_gap_px < 0 or self.workspace_padding_px < 0:
            raise ValueError("页面间距和工作区边距不能为负数")

    @property
    def visual_size(self) -> QSizeF:
        height = (
            self.workspace_padding_px * 2
            + self.page_count * self.geometry.page_height_px
            + (self.page_count - 1) * self.page_gap_px
        )
        width = self.workspace_padding_px * 2 + self.geometry.page_width_px
        return QSizeF(width, height)

    def paper_rect(self, page_index: int) -> QRectF:
        self._check_page(page_index)
        top = self.workspace_padding_px + page_index * (
            self.geometry.page_height_px + self.page_gap_px
        )
        return QRectF(
            self.workspace_padding_px,
            top,
            self.geometry.page_width_px,
            self.geometry.page_height_px,
        )

    def content_rect(self, page_index: int) -> QRectF:
        paper = self.paper_rect(page_index)
        left = self.geometry.points_to_pixels(self.geometry.margin_left_pt)
        top = self.geometry.points_to_pixels(self.geometry.margin_top_pt)
        return QRectF(
            paper.left() + left,
            paper.top() + top,
            self.geometry.content_width_px,
            self.geometry.content_height_px,
        )

    def fit_width_factor(self, viewport: QSizeF) -> float:
        self._check_viewport(viewport)
        return viewport.width() / self.visual_size.width()

    def fit_page_factor(self, viewport: QSizeF) -> float:
        self._check_viewport(viewport)
        single_page_height = self.geometry.page_height_px + self.workspace_padding_px * 2
        return min(
            viewport.width() / self.visual_size.width(),
            viewport.height() / single_page_height,
        )

    def document_to_visual(self, point: QPointF) -> QPointF:
        page = self.page_for_document_y(point.y())
        content = self.content_rect(page)
        return QPointF(
            content.left() + point.x(),
            content.top() + max(0.0, point.y() - page * self.geometry.content_height_px),
        )

    def document_to_visual_rect(self, rect: QRectF) -> QRectF:
        page = self.page_for_document_y(rect.center().y())
        content = self.content_rect(page)
        return QRectF(
            content.left() + rect.left(),
            content.top() + max(0.0, rect.top() - page * self.geometry.content_height_px),
            rect.width(),
            rect.height(),
        )

    def page_for_document_y(self, value: float) -> int:
        selected = int(
            max(0.0, value + self._PAGE_EDGE_TOLERANCE_PX) // self.geometry.content_height_px
        )
        return max(0, min(self.page_count - 1, selected))

    def page_for_visual_y(self, value: float) -> int:
        """Return the nearest physical page for a workspace y coordinate."""

        relative_y = value - self.workspace_padding_px
        if relative_y <= 0:
            return 0
        stride = self.geometry.page_height_px + self.page_gap_px
        page = math.floor(relative_y / stride)
        if page >= self.page_count:
            return self.page_count - 1
        within_stride = relative_y - page * stride
        if within_stride > self.geometry.page_height_px + self.page_gap_px / 2:
            page += 1
        return max(0, min(self.page_count - 1, page))

    def visual_to_document(self, point: QPointF) -> QPointF | None:
        relative_y = point.y() - self.workspace_padding_px
        if relative_y < 0:
            return None
        stride = self.geometry.page_height_px + self.page_gap_px
        page = math.floor(relative_y / stride)
        if not 0 <= page < self.page_count:
            return None
        content = self.content_rect(page)
        if not content.contains(point):
            return None
        return QPointF(
            point.x() - content.left(),
            page * self.geometry.content_height_px + point.y() - content.top(),
        )

    def visual_to_document_clamped(self, point: QPointF) -> QPointF:
        """Map margins or page gaps to the nearest editable content edge."""

        page = self.page_for_visual_y(point.y())
        content = self.content_rect(page)
        x = min(max(point.x(), content.left()), content.right())
        y = min(max(point.y(), content.top()), content.bottom() - 0.01)
        return QPointF(
            x - content.left(),
            page * self.geometry.content_height_px + y - content.top(),
        )

    def page_indices_intersecting(self, rect: QRectF) -> tuple[int, ...]:
        stride = self.geometry.page_height_px + self.page_gap_px
        first = math.floor((rect.top() - self.workspace_padding_px - 7.0) / stride)
        last = math.floor((rect.bottom() - self.workspace_padding_px + 7.0) / stride)
        first = max(0, first)
        last = min(self.page_count - 1, last)
        if first > last:
            return ()
        return tuple(
            page_index
            for page_index in range(first, last + 1)
            if self.paper_rect(page_index).adjusted(-4, -4, 6, 7).intersects(rect)
        )

    def _check_page(self, page_index: int) -> None:
        if not 0 <= page_index < self.page_count:
            raise IndexError("页面索引超出范围")

    @staticmethod
    def _check_viewport(viewport: QSizeF) -> None:
        if viewport.width() <= 0 or viewport.height() <= 0:
            raise ValueError("视口尺寸必须大于零")
