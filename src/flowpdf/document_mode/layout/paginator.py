from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtGui import QTextDocument


@dataclass(frozen=True, slots=True)
class PaginationSnapshot:
    page_count: int
    block_tops: tuple[float, ...]
    block_pages: tuple[int, ...]
    block_line_counts: tuple[int, ...]


class Paginator:
    """Read pagination facts from one continuous QTextDocument layout."""

    @staticmethod
    def snapshot(
        document: QTextDocument,
        *,
        page_height_px: float | None = None,
    ) -> PaginationSnapshot:
        layout = document.documentLayout()
        requested_height = page_height_px or document.pageSize().height()
        page_height = max(1.0, requested_height)
        block_tops: list[float] = []
        block_pages: list[int] = []
        line_counts: list[int] = []
        block = document.begin()
        while block.isValid():
            rect = layout.blockBoundingRect(block)
            top = round(rect.top(), 4)
            block_tops.append(top)
            block_pages.append(max(0, int(top // page_height)))
            line_counts.append(block.layout().lineCount())
            block = block.next()
        return PaginationSnapshot(
            page_count=max(1, math.ceil(layout.documentSize().height() / page_height)),
            block_tops=tuple(block_tops),
            block_pages=tuple(block_pages),
            block_line_counts=tuple(line_counts),
        )
