from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from flowpdf.backends.pymupdf_runtime import serialized_pymupdf


class PdfExportValidationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PdfExportValidation:
    page_count: int
    file_size: int
    image_count: int


class ExportValidator:
    @serialized_pymupdf
    def validate(
        self,
        path: str | Path,
        *,
        expected_pages: int,
        expected_width_pt: float,
        expected_height_pt: float,
        required_texts: tuple[str, ...],
        minimum_images: int,
    ) -> PdfExportValidation:
        source = Path(path)
        try:
            file_size = source.stat().st_size
        except OSError as exc:
            raise PdfExportValidationError("导出结果不存在或无法读取") from exc
        if file_size < 512:
            raise PdfExportValidationError("导出结果文件大小异常")
        document: pymupdf.Document | None = None
        try:
            document = pymupdf.open(source)
            if document.needs_pass:
                raise PdfExportValidationError("文档模式导出结果不应意外加密")
            if document.page_count != expected_pages:
                raise PdfExportValidationError(
                    f"导出页数验证失败：预期 {expected_pages} 页，实际 {document.page_count} 页"
                )
            first = document.load_page(0).rect
            if (
                abs(first.width - expected_width_pt) > 1
                or abs(first.height - expected_height_pt) > 1
            ):
                raise PdfExportValidationError("导出页面尺寸与文档设置不一致")
            extracted = _normalized_text(
                "".join(
                    document.load_page(index).get_text() for index in range(document.page_count)
                )
            )
            for required in required_texts:
                if _normalized_text(required) not in extracted:
                    raise PdfExportValidationError(f"导出文字层验证失败：{required[:20]}")
            image_count = sum(
                len(document.load_page(index).get_images(full=True))
                for index in range(document.page_count)
            )
            if image_count < minimum_images:
                raise PdfExportValidationError("导出图片数量验证失败")
            return PdfExportValidation(document.page_count, file_size, image_count)
        except PdfExportValidationError:
            raise
        except (OSError, RuntimeError, ValueError, pymupdf.FileDataError) as exc:
            raise PdfExportValidationError("导出 PDF 无法重新打开或结构无效") from exc
        finally:
            if document is not None:
                document.close()


def _normalized_text(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()
