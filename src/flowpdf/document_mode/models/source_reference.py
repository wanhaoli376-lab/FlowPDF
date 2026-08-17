from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourceReference:
    page_index: int
    bbox: tuple[float, float, float, float]
    original_text: str | None = None
    original_font: str | None = None
    confidence: float = 1.0

    def __post_init__(self) -> None:
        if self.page_index < 0:
            raise ValueError("来源页码不能为负数")
        if len(self.bbox) != 4:
            raise ValueError("来源区域必须包含四个坐标")
        x0, y0, x1, y1 = self.bbox
        if x1 < x0 or y1 < y0:
            raise ValueError("来源区域坐标无效")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("来源置信度必须位于 0 到 1 之间")
