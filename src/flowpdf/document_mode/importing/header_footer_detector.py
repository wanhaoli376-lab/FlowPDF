from __future__ import annotations

import math
import re
from collections import Counter

from flowpdf.document_mode.importing.extracted import ExtractedLine, ExtractedPage

_PAGE_NUMBER = re.compile(r"^(?:第\s*)?\d+(?:\s*页)?$", re.IGNORECASE)


def detect_headers_and_footers(
    pages: list[ExtractedPage],
) -> tuple[set[str], set[str], set[str]]:
    if len(pages) < 2:
        return set(), set(), set()
    header_counts: Counter[str] = Counter()
    footer_counts: Counter[str] = Counter()
    page_numbers: set[str] = set()
    for page in pages:
        seen_headers: set[str] = set()
        seen_footers: set[str] = set()
        for line in page.lines:
            normalized = normalize_repeated_text(line.text)
            if not normalized:
                continue
            if line.bbox[1] <= page.height_pt * 0.12:
                seen_headers.add(normalized)
            if line.bbox[3] >= page.height_pt * 0.88:
                seen_footers.add(normalized)
                if _PAGE_NUMBER.fullmatch(line.text.strip()):
                    page_numbers.add(normalized)
        header_counts.update(seen_headers)
        footer_counts.update(seen_footers)
    threshold = max(2, math.ceil(len(pages) * 0.6))
    headers = {text for text, count in header_counts.items() if count >= threshold}
    footers = {text for text, count in footer_counts.items() if count >= threshold}
    return headers, footers, page_numbers


def normalize_repeated_text(text: str) -> str:
    return " ".join(text.casefold().split())


def matches_any(line: ExtractedLine, values: set[str]) -> bool:
    return normalize_repeated_text(line.text) in values
