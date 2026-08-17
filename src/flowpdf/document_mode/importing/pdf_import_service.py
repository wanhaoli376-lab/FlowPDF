from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from flowpdf.backends.base import PdfResourceLimits
from flowpdf.backends.pymupdf_runtime import PYMUPDF_LOCK
from flowpdf.document_mode.importing.complexity_scorer import score_import
from flowpdf.document_mode.importing.extracted import ExtractedLine
from flowpdf.document_mode.importing.font_resolver import ImportFontResolver
from flowpdf.document_mode.importing.header_footer_detector import (
    detect_headers_and_footers,
    matches_any,
)
from flowpdf.document_mode.importing.heading_detector import classify_headings
from flowpdf.document_mode.importing.image_importer import import_images_in_reading_order
from flowpdf.document_mode.importing.paragraph_reconstructor import ParagraphReconstructor
from flowpdf.document_mode.importing.reading_order import ordered_lines
from flowpdf.document_mode.importing.report import ImportOptions, ImportReport
from flowpdf.document_mode.importing.text_extractor import ImportCancelled, TextExtractor
from flowpdf.document_mode.models import (
    DocumentMetadata,
    FlowDocument,
    PageSetup,
    Paragraph,
    Section,
    SemanticRole,
)


class PdfImportError(RuntimeError):
    pass


class ImportPasswordRequired(PdfImportError):
    pass


class ImportInvalidPassword(PdfImportError):
    pass


@dataclass(frozen=True, slots=True)
class ImportResult:
    document: FlowDocument
    report: ImportReport


class PdfImportService:
    def __init__(
        self,
        *,
        limits: PdfResourceLimits | None = None,
        extractor: TextExtractor | None = None,
    ) -> None:
        self._limits = limits or PdfResourceLimits()
        self._extractor = extractor or TextExtractor()

    def import_file(
        self,
        path: str | Path,
        *,
        password: str | None = None,
        options: ImportOptions | None = None,
        cancel_check: Callable[[], bool] | None = None,
        progress: Callable[[int, str], None] | None = None,
    ) -> ImportResult:
        source = Path(path)
        cancel = cancel_check or (lambda: False)
        report_progress = progress or (lambda _value, _message: None)
        selected_options = options or ImportOptions()
        document: pymupdf.Document | None = None
        try:
            resolved = source.resolve(strict=True)
            source_size = resolved.stat().st_size
            if source_size <= 0 or source_size > self._limits.max_source_bytes:
                raise PdfImportError("PDF 文件为空或超过导入安全大小上限")
            report_progress(2, "正在安全打开 PDF")
            with PYMUPDF_LOCK:
                document = pymupdf.open(resolved)
                if document.needs_pass:
                    if password is None:
                        raise ImportPasswordRequired("此 PDF 需要密码")
                    if not document.authenticate(password):
                        raise ImportInvalidPassword("PDF 密码不正确")
                self._validate_document(document)
                pages = self._extractor.extract(
                    document,
                    cancel_check=cancel,
                    progress=report_progress,
                )
                document.close()
                document = None
            if cancel():
                raise ImportCancelled
            headers, footers, page_numbers = detect_headers_and_footers(pages)
            all_lines = ordered_lines(pages)
            body_lines = [
                line
                for line in all_lines
                if not matches_any(line, headers | footers | page_numbers)
            ]
            font_resolver = ImportFontResolver()
            reconstructor = ParagraphReconstructor(font_resolver)
            paragraphs = reconstructor.reconstruct(body_lines)
            report_progress(65, "正在重构段落和标题")
            classify_headings(paragraphs, pages[0].width_pt)
            document_model = FlowDocument(
                metadata=DocumentMetadata(
                    title=resolved.stem,
                    source_pdf_path=str(resolved),
                    source_pdf_sha256=self._file_sha256(resolved),
                ),
                page_setup=PageSetup(width_pt=pages[0].width_pt, height_pt=pages[0].height_pt),
                sections=[Section()],
                headers=self._reconstruct_repeated(
                    all_lines,
                    headers,
                    reconstructor,
                    SemanticRole.HEADER,
                    selected_options.preserve_headers_and_footers,
                ),
                footers=self._reconstruct_repeated(
                    all_lines,
                    footers | (page_numbers if selected_options.preserve_page_numbers else set()),
                    reconstructor,
                    SemanticRole.FOOTER,
                    selected_options.preserve_headers_and_footers,
                ),
            )
            image_result = import_images_in_reading_order(
                document_model,
                pages,
                paragraphs,
                max_image_bytes=self._limits.max_image_bytes,
                max_image_pixels=self._limits.max_render_pixels,
            )
            document_model.sections[0].blocks = image_result.blocks
            import_report = score_import(pages, paragraphs)
            import_report.detected_headers = sorted(headers)
            import_report.detected_footers = sorted(footers)
            import_report.font_substitutions = font_resolver.warnings
            import_report.warnings.extend(font_resolver.warnings)
            import_report.warnings.extend(image_result.warnings)
            report_progress(100, "文档结构分析完成")
            return ImportResult(document_model, import_report)
        except (ImportPasswordRequired, ImportInvalidPassword, PdfImportError, ImportCancelled):
            raise
        except (OSError, RuntimeError, ValueError, pymupdf.FileDataError) as exc:
            raise PdfImportError("无法导入 PDF，文件可能损坏、受限制或资源异常") from exc
        finally:
            if document is not None:
                with PYMUPDF_LOCK:
                    document.close()

    def _validate_document(self, document: pymupdf.Document) -> None:
        if document.page_count <= 0 or document.page_count > self._limits.max_pages:
            raise PdfImportError("PDF 页数为空或超过导入安全上限")
        if document.xref_length() > self._limits.max_xref_objects:
            raise PdfImportError("PDF 内部对象数量超过导入安全上限")
        for page_index in range(document.page_count):
            rect = document.load_page(page_index).rect
            if max(rect.width, rect.height) > self._limits.max_page_dimension:
                raise PdfImportError("PDF 页面尺寸超过导入安全上限")

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _reconstruct_repeated(
        lines: list[ExtractedLine],
        values: set[str],
        reconstructor: ParagraphReconstructor,
        role: SemanticRole,
        preserve: bool,
    ) -> list[Paragraph]:
        if not preserve or not values:
            return []
        matches = [line for line in lines if matches_any(line, values)]
        first_page: dict[str, ExtractedLine] = {}
        for line in matches:
            first_page.setdefault(line.text.strip(), line)
        paragraphs = reconstructor.reconstruct(list(first_page.values()))
        for paragraph in paragraphs:
            paragraph.semantic_role = role
        return paragraphs
