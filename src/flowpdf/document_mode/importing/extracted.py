from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ExtractedSpan:
    text: str
    bbox: tuple[float, float, float, float]
    font_family: str
    font_size_pt: float
    color: int
    flags: int


@dataclass(slots=True)
class ExtractedLine:
    page_index: int
    bbox: tuple[float, float, float, float]
    spans: list[ExtractedSpan] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "".join(span.text for span in self.spans).strip()

    @property
    def dominant_size(self) -> float:
        if not self.spans:
            return 0.0
        return max(self.spans, key=lambda span: len(span.text)).font_size_pt

    @property
    def dominant_font(self) -> str:
        if not self.spans:
            return ""
        return max(self.spans, key=lambda span: len(span.text)).font_family


@dataclass(frozen=True, slots=True)
class ExtractedImage:
    page_index: int
    bbox: tuple[float, float, float, float]
    data: bytes
    extension: str
    width_px: int
    height_px: int


@dataclass(slots=True)
class ExtractedPage:
    page_index: int
    width_pt: float
    height_pt: float
    rotation: int
    lines: list[ExtractedLine] = field(default_factory=list)
    images: list[ExtractedImage] = field(default_factory=list)
    drawing_count: int = 0
