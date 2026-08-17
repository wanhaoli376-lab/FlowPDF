from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ParagraphAlignment(StrEnum):
    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"
    JUSTIFY = "justify"


@dataclass(frozen=True, slots=True)
class TextStyle:
    font_family: str = "Microsoft YaHei"
    font_size_pt: float = 11.0
    bold: bool = False
    italic: bool = False
    underline: bool = False
    strikeout: bool = False
    color: str = "#000000"
    background_color: str | None = None
    superscript: bool = False
    subscript: bool = False

    def __post_init__(self) -> None:
        if not self.font_family.strip():
            raise ValueError("字体名称不能为空")
        if not 1.0 <= self.font_size_pt <= 512.0:
            raise ValueError("字号超出允许范围")
        if self.superscript and self.subscript:
            raise ValueError("文字不能同时设置为上标和下标")


@dataclass(frozen=True, slots=True)
class ParagraphStyle:
    alignment: ParagraphAlignment = ParagraphAlignment.LEFT
    first_line_indent_pt: float = 0.0
    left_indent_pt: float = 0.0
    right_indent_pt: float = 0.0
    line_spacing: float = 1.15
    space_before_pt: float = 0.0
    space_after_pt: float = 6.0
    keep_with_next: bool = False
    keep_together: bool = False
    list_kind: str | None = None
    list_level: int = 0

    def __post_init__(self) -> None:
        if not 0.5 <= self.line_spacing <= 10.0:
            raise ValueError("行距倍数超出允许范围")
        if not 0 <= self.list_level <= 9:
            raise ValueError("列表层级超出允许范围")
        if self.list_kind not in {None, "bullet", "number"}:
            raise ValueError("列表类型无效")
