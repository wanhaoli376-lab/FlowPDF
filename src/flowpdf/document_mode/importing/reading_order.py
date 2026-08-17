from __future__ import annotations

from flowpdf.document_mode.importing.extracted import ExtractedLine, ExtractedPage


def ordered_lines(pages: list[ExtractedPage]) -> list[ExtractedLine]:
    output: list[ExtractedLine] = []
    for page in pages:
        output.extend(sorted(page.lines, key=lambda line: (round(line.bbox[1], 2), line.bbox[0])))
    return output


def detect_columns(pages: list[ExtractedPage]) -> int:
    detected = 1
    for page in pages:
        usable = [line for line in page.lines if len(line.text) >= 4]
        if len(usable) < 4:
            continue
        middle = page.width_pt / 2
        left = [line for line in usable if line.bbox[2] < middle * 1.05]
        right = [line for line in usable if line.bbox[0] > middle * 0.95]
        if len(left) >= 2 and len(right) >= 2 and _vertical_overlap(left, right):
            detected = max(detected, 2)
    return detected


def _vertical_overlap(left: list[ExtractedLine], right: list[ExtractedLine]) -> bool:
    left_top = min(line.bbox[1] for line in left)
    left_bottom = max(line.bbox[3] for line in left)
    right_top = min(line.bbox[1] for line in right)
    right_bottom = max(line.bbox[3] for line in right)
    overlap = min(left_bottom, right_bottom) - max(left_top, right_top)
    smaller = min(left_bottom - left_top, right_bottom - right_top)
    return smaller > 0 and overlap / smaller >= 0.35
