from __future__ import annotations

from collections.abc import Callable

import pymupdf

from flowpdf.document_mode.importing.extracted import (
    ExtractedImage,
    ExtractedLine,
    ExtractedPage,
    ExtractedSpan,
)


class TextExtractor:
    def extract(
        self,
        document: pymupdf.Document,
        *,
        cancel_check: Callable[[], bool],
        progress: Callable[[int, str], None],
    ) -> list[ExtractedPage]:
        pages: list[ExtractedPage] = []
        page_count = document.page_count
        for page_index in range(page_count):
            if cancel_check():
                raise ImportCancelled
            page = document.load_page(page_index)
            raw = page.get_text("dict", sort=False)
            lines: list[ExtractedLine] = []
            images: list[ExtractedImage] = []
            for block in raw.get("blocks", []):
                block_type = int(block.get("type", -1))
                if block_type == 0:
                    lines.extend(self._text_lines(page_index, block))
                elif block_type == 1:
                    image = self._image(page_index, block)
                    if image is not None:
                        images.append(image)
            pages.append(
                ExtractedPage(
                    page_index=page_index,
                    width_pt=float(page.rect.width),
                    height_pt=float(page.rect.height),
                    rotation=int(page.rotation),
                    lines=lines,
                    images=images,
                    drawing_count=len(page.get_drawings()),
                )
            )
            progress(5 + round(45 * (page_index + 1) / page_count), "正在提取文字和图片")
        return pages

    @staticmethod
    def _text_lines(page_index: int, block: dict) -> list[ExtractedLine]:
        output: list[ExtractedLine] = []
        for raw_line in block.get("lines", []):
            spans = [
                ExtractedSpan(
                    text=str(span.get("text", "")),
                    bbox=_bbox(span.get("bbox")),
                    font_family=str(span.get("font", "")),
                    font_size_pt=float(span.get("size", 11.0)),
                    color=int(span.get("color", 0)),
                    flags=int(span.get("flags", 0)),
                )
                for span in raw_line.get("spans", [])
                if str(span.get("text", ""))
            ]
            if spans:
                output.append(
                    ExtractedLine(
                        page_index=page_index,
                        bbox=_bbox(raw_line.get("bbox")),
                        spans=spans,
                    )
                )
        return output

    @staticmethod
    def _image(page_index: int, block: dict) -> ExtractedImage | None:
        data = block.get("image")
        extension = str(block.get("ext", "")).casefold()
        if (
            not isinstance(data, bytes)
            or not data
            or extension not in {"png", "jpeg", "jpg", "webp"}
        ):
            return None
        return ExtractedImage(
            page_index=page_index,
            bbox=_bbox(block.get("bbox")),
            data=data,
            extension="jpeg" if extension == "jpg" else extension,
            width_px=int(block.get("width", 1)),
            height_px=int(block.get("height", 1)),
        )


class ImportCancelled(RuntimeError):
    pass


def _bbox(value: object) -> tuple[float, float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return (0.0, 0.0, 0.0, 0.0)
    return tuple(float(item) for item in value)  # type: ignore[return-value]
