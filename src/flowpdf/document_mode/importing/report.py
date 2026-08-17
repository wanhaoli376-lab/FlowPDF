from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class UnsupportedRegion:
    page_index: int
    bbox: tuple[float, float, float, float]
    reason: str
    fallback: str = "fixed_block"


@dataclass(slots=True)
class ImportReport:
    score: int
    recommended_mode: str
    detected_columns: int
    text_coverage: float
    image_coverage: float
    paragraph_count: int
    heading_count: int
    table_count: int = 0
    unsupported_regions: list[UnsupportedRegion] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    font_substitutions: list[str] = field(default_factory=list)
    detected_headers: list[str] = field(default_factory=list)
    detected_footers: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ImportOptions:
    preserve_headers_and_footers: bool = True
    preserve_page_numbers: bool = True
    preserve_original_page_breaks: bool = False
