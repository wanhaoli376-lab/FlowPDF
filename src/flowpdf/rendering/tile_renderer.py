from __future__ import annotations

import math

import pymupdf

from flowpdf.backends.base import (
    InvalidPasswordError,
    PdfOpenError,
    PdfResourceLimitError,
    RenderedPage,
)
from flowpdf.backends.pymupdf_runtime import serialized_pymupdf
from flowpdf.rendering.tile_cache import TileKey
from flowpdf.utils.coordinates import Rect


@serialized_pymupdf
def render_pdf_snapshot(
    source: object,
    key: TileKey,
    cancellation: object,
    *,
    max_render_pixels: int = 80_000_000,
) -> RenderedPage:
    """Render one immutable PDF snapshot in a worker thread."""
    if _cancelled(cancellation):
        raise RenderCancelled
    data = getattr(source, "data", None)
    password = getattr(source, "password", None)
    if not isinstance(data, bytes):
        raise PdfOpenError("渲染源无效")
    if not math.isfinite(key.scale) or key.scale <= 0 or key.scale > 16:
        raise PdfResourceLimitError("渲染缩放比例超出安全范围")

    document: pymupdf.Document | None = None
    try:
        document = pymupdf.open(stream=data, filetype="pdf")
        if document.needs_pass and (not password or not document.authenticate(password)):
            raise InvalidPasswordError("渲染快照的密码无效")
        if not 0 <= key.page_index < document.page_count:
            raise PdfOpenError("待渲染页码超出范围")
        page = document.load_page(key.page_index)
        clip = pymupdf.Rect(key.tile) if key.tile is not None else page.rect
        clip &= page.rect
        if clip.is_empty:
            raise PdfOpenError("渲染图块不在页面内")
        pixels = math.ceil(clip.width * key.scale) * math.ceil(clip.height * key.scale)
        if pixels > max_render_pixels:
            raise PdfResourceLimitError("图块超过像素安全上限")
        if _cancelled(cancellation):
            raise RenderCancelled
        pixmap = page.get_pixmap(
            matrix=pymupdf.Matrix(key.scale, key.scale),
            clip=clip,
            colorspace=pymupdf.csRGB,
            alpha=False,
            annots=True,
        )
        if _cancelled(cancellation):
            raise RenderCancelled
        return RenderedPage(
            width=pixmap.width,
            height=pixmap.height,
            stride=pixmap.stride,
            samples=bytes(pixmap.samples),
            clip=Rect(clip.x0, clip.y0, clip.x1, clip.y1),
            scale=key.scale,
        )
    except RenderCancelled:
        raise
    except (InvalidPasswordError, PdfOpenError, PdfResourceLimitError):
        raise
    except (RuntimeError, ValueError, pymupdf.FileDataError) as exc:
        raise PdfOpenError("PDF 页面渲染失败，页面结构可能异常") from exc
    finally:
        if document is not None:
            document.close()


class RenderCancelled(Exception):
    """Internal sentinel; cancelled work is intentionally not reported as an error."""


def _cancelled(token: object) -> bool:
    checker = getattr(token, "is_cancelled", None)
    return bool(checker()) if checker is not None else False
