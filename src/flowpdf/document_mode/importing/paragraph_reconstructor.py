from __future__ import annotations

import re
from dataclasses import dataclass

from flowpdf.document_mode.importing.extracted import ExtractedLine
from flowpdf.document_mode.importing.font_resolver import ImportFontResolver
from flowpdf.document_mode.models import (
    Paragraph,
    ParagraphStyle,
    SemanticRole,
    SourceReference,
    TextRun,
    TextStyle,
)

_LIST_ITEM = re.compile(r"^\s*(?:[•·●▪◦*-]|\(?\d+[.)、])\s+")
_LATIN_END = re.compile(r"[A-Za-z]$")
_LATIN_START = re.compile(r"^[a-z]")


@dataclass(slots=True)
class _ParagraphLines:
    lines: list[ExtractedLine]


class ParagraphReconstructor:
    def __init__(self, font_resolver: ImportFontResolver) -> None:
        self._fonts = font_resolver

    def reconstruct(self, lines: list[ExtractedLine]) -> list[Paragraph]:
        groups: list[_ParagraphLines] = []
        for line in lines:
            if not line.text:
                continue
            if groups and self._continues(groups[-1].lines[-1], line):
                groups[-1].lines.append(line)
            else:
                groups.append(_ParagraphLines([line]))
        return [self._paragraph(group.lines) for group in groups]

    @staticmethod
    def _continues(previous: ExtractedLine, current: ExtractedLine) -> bool:
        if previous.page_index != current.page_index:
            return False
        if _LIST_ITEM.match(current.text):
            return False
        size = max(previous.dominant_size, current.dominant_size, 1.0)
        vertical_gap = current.bbox[1] - previous.bbox[3]
        left_delta = abs(current.bbox[0] - previous.bbox[0])
        same_size = abs(current.dominant_size - previous.dominant_size) <= max(0.8, size * 0.08)
        return (
            same_size
            and left_delta <= max(12.0, size)
            and -(size * 0.35) <= vertical_gap <= size * 1.1
        )

    def _paragraph(self, lines: list[ExtractedLine]) -> Paragraph:
        runs: list[TextRun] = []
        for line_index, line in enumerate(lines):
            if line_index:
                self._join_line(runs, line.text)
            for span in line.spans:
                if line_index and span is line.spans[0]:
                    text = self._remove_consumed_prefix(span.text, runs)
                else:
                    text = span.text
                if not text:
                    continue
                style = TextStyle(
                    font_family=self._fonts.resolve(span.font_family, span.text),
                    font_size_pt=max(1.0, span.font_size_pt),
                    bold=bool(span.flags & 16),
                    italic=bool(span.flags & 2),
                    color=_color_hex(span.color),
                )
                runs.append(
                    TextRun(
                        text=text,
                        style=style,
                        source_ref=SourceReference(
                            page_index=line.page_index,
                            bbox=span.bbox,
                            original_text=span.text,
                            original_font=span.font_family,
                            confidence=0.9,
                        ),
                    )
                )
        original_text = "".join(run.text for run in runs)
        x0 = min(line.bbox[0] for line in lines)
        y0 = min(line.bbox[1] for line in lines)
        x1 = max(line.bbox[2] for line in lines)
        y1 = max(line.bbox[3] for line in lines)
        list_match = _LIST_ITEM.match(original_text)
        if list_match:
            self._remove_run_prefix(runs, list_match.end())
        text = "".join(run.text for run in runs)
        paragraph = Paragraph(
            runs=runs,
            style=ParagraphStyle(
                first_line_indent_pt=max(
                    0.0, lines[0].bbox[0] - min(line.bbox[0] for line in lines)
                ),
                list_kind=(
                    "number"
                    if list_match and any(c.isdigit() for c in list_match.group())
                    else "bullet"
                )
                if list_match
                else None,
            ),
            semantic_role=SemanticRole.LIST_ITEM if list_match else SemanticRole.UNKNOWN,
            source_ref=SourceReference(
                page_index=lines[0].page_index,
                bbox=(x0, y0, x1, y1),
                original_text=original_text,
                original_font=lines[0].dominant_font,
                confidence=0.88,
            ),
        )
        paragraph.normalize()
        return paragraph

    @staticmethod
    def _join_line(runs: list[TextRun], next_text: str) -> None:
        if not runs:
            return
        previous = runs[-1].text
        if (
            previous.endswith("-")
            and _LATIN_END.search(previous[:-1])
            and _LATIN_START.match(next_text)
        ):
            runs[-1].text = previous[:-1]
            return
        if _LATIN_END.search(previous) and re.match(r"^[A-Za-z]", next_text):
            runs[-1].text += " "

    @staticmethod
    def _remove_consumed_prefix(text: str, runs: list[TextRun]) -> str:
        return text

    @staticmethod
    def _remove_run_prefix(runs: list[TextRun], length: int) -> None:
        remaining = length
        for run in runs:
            if remaining <= 0:
                break
            consumed = min(len(run.text), remaining)
            run.text = run.text[consumed:]
            remaining -= consumed


def _color_hex(color: int) -> str:
    return f"#{(color >> 16) & 0xFF:02x}{(color >> 8) & 0xFF:02x}{color & 0xFF:02x}"
