from __future__ import annotations

import re
from statistics import median

from flowpdf.document_mode.models import Paragraph, SemanticRole

_CHAPTER = re.compile(r"^(?:第[一二三四五六七八九十百\d]+[章节]|\d+(?:\.\d+){0,2}\s+)")


def classify_headings(paragraphs: list[Paragraph], page_width: float) -> None:
    sizes = [
        run.style.font_size_pt for paragraph in paragraphs for run in paragraph.runs if run.text
    ]
    if not sizes:
        return
    body_size = median(sizes)
    for index, paragraph in enumerate(paragraphs):
        if paragraph.semantic_role is SemanticRole.LIST_ITEM or not paragraph.runs:
            continue
        size = max(run.style.font_size_pt for run in paragraph.runs)
        text = paragraph.text.strip()
        short = len(text) <= 80
        centered = False
        if paragraph.source_ref is not None:
            x0, _y0, x1, _y1 = paragraph.source_ref.bbox
            centered = abs((x0 + x1) / 2 - page_width / 2) <= page_width * 0.12
        bold = any(run.style.bold for run in paragraph.runs)
        if index == 0 and short and size >= body_size * 1.45:
            paragraph.semantic_role = SemanticRole.TITLE
        elif short and size >= body_size * 1.3 and (bold or centered or _CHAPTER.match(text)):
            paragraph.semantic_role = SemanticRole.HEADING1
        elif short and size >= body_size * 1.15 and (bold or _CHAPTER.match(text)):
            paragraph.semantic_role = SemanticRole.HEADING2
        else:
            paragraph.semantic_role = SemanticRole.BODY
