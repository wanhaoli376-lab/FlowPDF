from __future__ import annotations

import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from flowpdf.utils.coordinates import Rect


class OverflowStrategy(StrEnum):
    AUTO_SHRINK = "auto_shrink"
    WRAP = "wrap"
    EXPAND = "expand"
    WARN = "warn"


@dataclass(frozen=True, slots=True)
class TextLayout:
    lines: tuple[str, ...]
    font_size: float
    rect: Rect
    overflow: bool


def layout_text(
    text: str,
    rect: Rect,
    *,
    font_size: float,
    strategy: OverflowStrategy,
    min_font_size: float = 6.0,
    line_height: float = 1.2,
    measure: Callable[[str, float], float] | None = None,
) -> TextLayout:
    """Resolve text overflow without knowing anything about the PDF engine."""
    box = rect.normalized()
    if box.width <= 0 or box.height <= 0:
        raise ValueError("文字框尺寸必须大于 0")
    if min_font_size <= 0 or font_size < min_font_size or line_height <= 0:
        raise ValueError("字号或行高设置无效")
    width_of = measure or estimate_text_width

    if strategy is OverflowStrategy.WARN:
        lines = tuple(text.splitlines()) or ("",)
        return TextLayout(
            lines,
            font_size,
            box,
            _overflows(lines, font_size, box, line_height, width_of),
        )

    if strategy is OverflowStrategy.AUTO_SHRINK:
        candidate_size = font_size
        while candidate_size >= min_font_size:
            lines = _wrap(text, box.width, candidate_size, width_of)
            if not _overflows(lines, candidate_size, box, line_height, width_of):
                return TextLayout(lines, candidate_size, box, False)
            candidate_size = round(candidate_size - 0.5, 2)
        lines = _wrap(text, box.width, min_font_size, width_of)
        return TextLayout(
            lines,
            min_font_size,
            box,
            _overflows(lines, min_font_size, box, line_height, width_of),
        )

    lines = _wrap(text, box.width, font_size, width_of)
    if strategy is OverflowStrategy.EXPAND:
        required_height = max(font_size * line_height, len(lines) * font_size * line_height)
        expanded = Rect(box.x0, box.y0, box.x1, max(box.y1, box.y0 + required_height))
        return TextLayout(lines, font_size, expanded, False)

    return TextLayout(
        lines,
        font_size,
        box,
        _overflows(lines, font_size, box, line_height, width_of),
    )


def estimate_text_width(text: str, font_size: float) -> float:
    units = 0.0
    for character in text:
        if character.isspace():
            units += 0.32
        elif unicodedata.east_asian_width(character) in {"W", "F", "A"}:
            units += 1.0
        else:
            units += 0.56
    return units * font_size


def _wrap(
    text: str,
    max_width: float,
    font_size: float,
    measure: Callable[[str, float], float],
) -> tuple[str, ...]:
    output: list[str] = []
    paragraphs = text.splitlines() or [""]
    for paragraph in paragraphs:
        if not paragraph:
            output.append("")
            continue
        current = ""
        last_break = -1
        for character in paragraph:
            candidate = current + character
            if measure(candidate, font_size) <= max_width or not current:
                current = candidate
                if character.isspace():
                    last_break = len(current) - 1
                continue
            if last_break >= 0:
                output.append(current[:last_break].rstrip())
                current = current[last_break + 1 :] + character
            else:
                output.append(current.rstrip())
                current = character
            last_break = max(
                (index for index, char in enumerate(current) if char.isspace()),
                default=-1,
            )
        output.append(current.rstrip())
    return tuple(output) or ("",)


def _overflows(
    lines: tuple[str, ...],
    font_size: float,
    rect: Rect,
    line_height: float,
    measure: Callable[[str, float], float],
) -> bool:
    height = len(lines) * font_size * line_height
    return height > rect.height or any(measure(line, font_size) > rect.width for line in lines)
