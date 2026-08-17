from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtGui import QTextDocument, QTextFormat


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
        page_offset = 0.0
        maximum_bottom = 0.0
        block = document.begin()
        while block.isValid():
            rect = layout.blockBoundingRect(block)
            top = rect.top() + page_offset
            policy = block.blockFormat().pageBreakPolicy()
            if (
                policy & QTextFormat.PageBreakFlag.PageBreak_AlwaysBefore
                and block.blockNumber() > 0
            ):
                page_start = math.ceil((top + 0.0001) / page_height) * page_height
                page_offset += max(0.0, page_start - top)
                top = rect.top() + page_offset
            top = round(top, 4)
            block_tops.append(top)
            block_pages.append(max(0, int(top // page_height)))
            line_counts.append(block.layout().lineCount())
            maximum_bottom = max(maximum_bottom, top + rect.height())
            block = block.next()
        return PaginationSnapshot(
            page_count=max(1, math.ceil(maximum_bottom / page_height)),
            block_tops=tuple(block_tops),
            block_pages=tuple(block_pages),
            block_line_counts=tuple(line_counts),
        )
