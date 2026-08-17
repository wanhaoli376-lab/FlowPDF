from __future__ import annotations

import html
import os
import uuid
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import pymupdf

from flowpdf.backends.pymupdf_runtime import serialized_pymupdf
from flowpdf.document_mode.export.export_validator import (
    ExportValidator,
    PdfExportValidationError,
)
from flowpdf.document_mode.models import BlockImage, FlowDocument, PageBreak, Paragraph


class PdfExportError(RuntimeError):
    pass


class PdfExportCancelled(PdfExportError):
    pass


class ArtifactRegistry(Protocol):
    def register(self, artifact: str | Path) -> None: ...

    def unregister(self, artifact: str | Path) -> None: ...


@dataclass(frozen=True, slots=True)
class PdfExportResult:
    output_path: Path
    page_count: int
    file_size: int
    image_count: int
    preview_page_count: int | None = None

    @property
    def pagination_matches(self) -> bool:
        return self.preview_page_count is None or self.preview_page_count == self.page_count


@dataclass(frozen=True, slots=True)
class _PdfLayoutResult:
    page_count: int
    cancelled: bool = False


class DocumentPdfExporter:
    def __init__(
        self,
        *,
        validator: ExportValidator | None = None,
        artifact_registry: ArtifactRegistry | None = None,
    ) -> None:
        self._validator = validator or ExportValidator()
        self._artifact_registry = artifact_registry

    def export(
        self,
        document: FlowDocument,
        output_path: str | Path,
        *,
        expected_page_count: int | None = None,
        cancel_check: Callable[[], bool] | None = None,
        progress: Callable[[int, str], None] | None = None,
    ) -> PdfExportResult:
        target = Path(output_path)
        if target.suffix.casefold() != ".pdf":
            target = target.with_suffix(".pdf")
        if not target.parent.is_dir():
            raise PdfExportError("PDF 导出目录不存在")
        if target.is_symlink():
            raise PdfExportError("为保护数据，不能导出到符号链接目标")
        cancel = cancel_check or (lambda: False)
        report = progress or (lambda _value, _message: None)
        temporary = target.parent / f".flowpdf-export-{uuid.uuid4().hex}.tmp.pdf"
        story_temporary = target.parent / f".flowpdf-story-{uuid.uuid4().hex}.tmp.pdf"
        try:
            if self._artifact_registry is not None:
                self._artifact_registry.register(temporary)
                self._artifact_registry.register(story_temporary)
            report(5, "正在准备文档布局")
            self._raise_if_cancelled(cancel)
            layout = self._write_pdf(
                document,
                temporary,
                story_temporary,
                cancel,
                report,
            )
            if layout.cancelled:
                raise PdfExportCancelled("PDF 导出已取消，目标文件未被修改")
            page_count = layout.page_count
            report(85, "正在重新打开并验证导出结果")
            validation = self._validator.validate(
                temporary,
                expected_pages=page_count,
                expected_width_pt=document.page_setup.width_pt,
                expected_height_pt=document.page_setup.height_pt,
                required_texts=_validation_terms(document),
                minimum_images=_used_image_count(document),
            )
            self._raise_if_cancelled(cancel)
            os.replace(temporary, target)
            report(100, "PDF 导出完成")
            return PdfExportResult(
                target,
                validation.page_count,
                validation.file_size,
                validation.image_count,
                expected_page_count,
            )
        except (PdfExportError, PdfExportValidationError):
            raise
        except OSError as exc:
            raise PdfExportError(f"无法安全导出 PDF：{target.name}") from exc
        finally:
            if temporary.exists() and not temporary.is_symlink():
                with suppress(OSError):
                    temporary.unlink()
            if story_temporary.exists() and not story_temporary.is_symlink():
                with suppress(OSError):
                    story_temporary.unlink()
            if self._artifact_registry is not None:
                for artifact in (temporary, story_temporary):
                    if not artifact.exists():
                        with suppress(OSError, ValueError):
                            self._artifact_registry.unregister(artifact)

    @staticmethod
    @serialized_pymupdf
    def _write_pdf(
        document: FlowDocument,
        output: Path,
        story_output: Path,
        cancel: Callable[[], bool],
        progress: Callable[[int, str], None],
    ) -> _PdfLayoutResult:
        archive = pymupdf.Archive()
        for asset in document.assets.values():
            archive.add(asset.data, asset.file_name)
        setup = document.page_setup
        mediabox = pymupdf.Rect(0, 0, setup.width_pt, setup.height_pt)
        full_height = setup.height_pt - setup.margin_top_pt - setup.margin_bottom_pt
        page_counter, cancelled_during_layout = _write_story_layout(
            document,
            archive,
            story_output,
            mediabox,
            content_height=full_height,
            cancel=cancel,
            progress=progress,
        )
        if cancelled_during_layout:
            # Return cancellation instead of raising while Story and DocumentWriter are
            # still referenced by an exception frame. On Windows that traceback kept
            # the native output handle alive until after the outer cleanup attempted
            # to unlink it.
            return _PdfLayoutResult(page_counter, cancelled=True)
        if page_counter <= 0:
            raise PdfExportError("文档排版没有生成页面")
        _decorate_pdf(story_output, output, document, page_counter)
        return _PdfLayoutResult(page_counter)

    @staticmethod
    def _raise_if_cancelled(cancel: Callable[[], bool]) -> None:
        if cancel():
            raise PdfExportCancelled("PDF 导出已取消，目标文件未被修改")


def _write_story_layout(
    document: FlowDocument,
    archive: pymupdf.Archive,
    output: Path,
    mediabox: pymupdf.Rect,
    *,
    content_height: float,
    cancel: Callable[[], bool],
    progress: Callable[[int, str], None],
) -> tuple[int, bool]:
    if output.exists() and not output.is_symlink():
        output.unlink()
    story = pymupdf.Story(
        _document_html(document),
        user_css=_document_css(),
        em=11,
        archive=archive,
    )
    writer = pymupdf.DocumentWriter(str(output))
    setup = document.page_setup
    content = pymupdf.Rect(
        setup.margin_left_pt,
        setup.margin_top_pt,
        setup.width_pt - setup.margin_right_pt,
        setup.margin_top_pt + content_height,
    )
    page_counter = 0
    cancelled = False

    def rect_for_page(
        _rect_number: int,
        _filled: pymupdf.Rect,
    ) -> tuple[pymupdf.Rect, pymupdf.Rect, None]:
        nonlocal cancelled, page_counter
        cancelled = cancelled or cancel()
        page_counter += 1
        progress(min(75, 10 + page_counter * 5), f"正在排版第 {page_counter} 页")
        return mediabox, content, None

    try:
        story.write(writer, rect_for_page)
    finally:
        writer.close()
    return page_counter, cancelled


def _decorate_pdf(
    source_path: Path,
    output: Path,
    document: FlowDocument,
    page_count: int,
) -> None:
    setup = document.page_setup
    source: pymupdf.Document | None = None
    try:
        source = pymupdf.open(source_path)
        source.set_metadata(
            {
                "title": document.metadata.title,
                "author": document.metadata.author,
                "creator": "FlowPDF",
                "producer": "FlowPDF / PyMuPDF",
            }
        )
        for page_index, page in enumerate(source):
            if document.headers:
                page.insert_textbox(
                    pymupdf.Rect(
                        setup.margin_left_pt,
                        6,
                        setup.width_pt - setup.margin_right_pt,
                        max(12.0, setup.margin_top_pt - 6),
                    ),
                    document.headers[0].text,
                    fontname="china-s",
                    fontsize=9,
                    align=pymupdf.TEXT_ALIGN_LEFT,
                )
            footer_text = document.footers[0].text if document.footers else ""
            if footer_text:
                page.insert_textbox(
                    pymupdf.Rect(
                        setup.margin_left_pt,
                        setup.height_pt - setup.margin_bottom_pt + 2,
                        setup.width_pt - setup.margin_right_pt,
                        setup.height_pt - 4,
                    ),
                    footer_text,
                    fontname="china-s",
                    fontsize=9,
                    align=pymupdf.TEXT_ALIGN_LEFT,
                )
            show_number = not (page_index == 0 and setup.first_page_number_hidden)
            if setup.page_number_position != "none" and show_number:
                alignment = (
                    pymupdf.TEXT_ALIGN_CENTER
                    if setup.page_number_position == "bottom_center"
                    else pymupdf.TEXT_ALIGN_RIGHT
                )
                page.insert_textbox(
                    pymupdf.Rect(
                        setup.margin_left_pt,
                        setup.height_pt - setup.margin_bottom_pt + 2,
                        setup.width_pt - setup.margin_right_pt,
                        setup.height_pt - 4,
                    ),
                    f"{page_index + 1} / {page_count}",
                    fontname="helv",
                    fontsize=9,
                    align=alignment,
                )
        source.ez_save(output)
        source.close()
        source = None
    finally:
        if source is not None:
            source.close()


def _document_html(document: FlowDocument) -> str:
    parts = ["<html><body>"]
    active_list: str | None = None
    for section in document.sections:
        for block in section.blocks:
            if isinstance(block, Paragraph) and block.style.list_kind is not None:
                list_tag = "ol" if block.style.list_kind == "number" else "ul"
                if active_list != list_tag:
                    if active_list is not None:
                        parts.append(f"</{active_list}>")
                    parts.append(f"<{list_tag}>")
                    active_list = list_tag
                parts.append(f"<li>{_paragraph_runs(block)}</li>")
                continue
            if active_list is not None:
                parts.append(f"</{active_list}>")
                active_list = None
            if isinstance(block, PageBreak):
                parts.append('<div style="page-break-before:always"></div>')
                continue
            if isinstance(block, Paragraph):
                parts.append(
                    f'<p class="{block.semantic_role.value}" '
                    f'style="{_paragraph_css(block)}">{_paragraph_runs(block)}</p>'
                )
            else:
                asset = document.assets[block.asset_id]
                parts.append(
                    f'<div style="text-align:{block.alignment};margin:6pt 0">'
                    f'<img src="{html.escape(asset.file_name, quote=True)}" '
                    f'width="{block.width_pt}pt" height="{block.height_pt}pt" '
                    f'alt="{html.escape(block.alt_text, quote=True)}"></div>'
                )
    if active_list is not None:
        parts.append(f"</{active_list}>")
    parts.append("</body></html>")
    return "".join(parts)


def _paragraph_runs(paragraph: Paragraph) -> str:
    return "".join(
        f'<span style="{_text_css(run.style)}">{html.escape(run.text)}</span>'
        for run in paragraph.runs
    )


def _paragraph_css(paragraph: Paragraph) -> str:
    style = paragraph.style
    # Qt and MuPDF Story use different font metrics for the same nominal CJK point
    # size. This conversion keeps line boxes close without changing the page content
    # rectangle or the user's configured margins.
    story_line_height = style.line_spacing * 1.15
    return ";".join(
        (
            f"text-align:{style.alignment.value}",
            f"text-indent:{style.first_line_indent_pt}pt",
            f"margin-left:{style.left_indent_pt}pt",
            f"margin-right:{style.right_indent_pt}pt",
            f"margin-top:{style.space_before_pt}pt",
            f"margin-bottom:{style.space_after_pt}pt",
            f"line-height:{story_line_height}",
            "page-break-inside:avoid" if style.keep_together else "",
            "page-break-after:avoid" if style.keep_with_next else "",
        )
    )


def _text_css(style) -> str:
    decorations = []
    if style.underline:
        decorations.append("underline")
    if style.strikeout:
        decorations.append("line-through")
    vertical = "super" if style.superscript else "sub" if style.subscript else "baseline"
    return ";".join(
        (
            f"font-family:'{html.escape(style.font_family, quote=True)}'",
            f"font-size:{style.font_size_pt}pt",
            f"font-weight:{'bold' if style.bold else 'normal'}",
            f"font-style:{'italic' if style.italic else 'normal'}",
            f"text-decoration:{' '.join(decorations) if decorations else 'none'}",
            f"color:{style.color}",
            f"background-color:{style.background_color or 'transparent'}",
            f"vertical-align:{vertical}",
        )
    )


def _document_css() -> str:
    return (
        "body{margin:0;padding:0;font-family:sans-serif;font-size:11pt;color:#000;}"
        "p{orphans:2;widows:2;}"
        "img{max-width:100%;object-fit:contain;}"
        "ul,ol{margin-top:0;margin-bottom:6pt;}"
    )


def _validation_terms(document: FlowDocument) -> tuple[str, ...]:
    terms: list[str] = []
    for section in document.sections:
        for block in section.blocks:
            if isinstance(block, Paragraph) and block.text.strip():
                terms.append(block.text.strip()[:40])
                if len(terms) == 3:
                    return tuple(terms)
    return tuple(terms)


def _used_image_count(document: FlowDocument) -> int:
    return sum(
        isinstance(block, BlockImage) for section in document.sections for block in section.blocks
    )
