from __future__ import annotations

import io

import pymupdf
import pytest
from PIL import Image

from flowpdf.document_mode.export import DocumentPdfExporter, PdfExportCancelled, PdfExportError
from flowpdf.document_mode.models import (
    BlockImage,
    FlowDocument,
    ImageAsset,
    PageBreak,
    PageSetup,
    Paragraph,
    ParagraphAlignment,
    ParagraphStyle,
    TextRun,
    TextStyle,
)


def _export_document() -> FlowDocument:
    document = FlowDocument.new(title="可搜索导出")
    document.page_setup = PageSetup(
        width_pt=320,
        height_pt=360,
        margin_top_pt=36,
        margin_bottom_pt=42,
        margin_left_pt=36,
        margin_right_pt=36,
        page_number_position="bottom_center",
    )
    document.append_block(
        Paragraph(
            runs=[
                TextRun(
                    "FlowPDF 文档模式中文可搜索",
                    TextStyle(font_family="Microsoft YaHei", font_size_pt=16, bold=True),
                )
            ],
            style=ParagraphStyle(
                alignment=ParagraphAlignment.CENTER,
                space_after_pt=12,
            ),
        )
    )
    for index in range(12):
        document.append_block(
            Paragraph(
                runs=[TextRun(f"Paragraph {index + 1}: 中英文混排内容会自动分页。" * 2)],
                style=ParagraphStyle(line_spacing=1.5, space_after_pt=8),
            )
        )
    image = Image.new("RGB", (160, 80), "#7c3aed")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    asset = ImageAsset.create(
        buffer.getvalue(),
        media_type="image/png",
        width_px=160,
        height_px=80,
    )
    document.add_asset(asset)
    document.append_block(
        BlockImage(
            asset_id=asset.asset_id,
            width_pt=160,
            height_pt=80,
            alignment="center",
            alt_text="紫色示例图片",
        )
    )
    return document


def test_export_reopens_with_matching_pages_searchable_chinese_and_image(qapp, tmp_path) -> None:
    document = _export_document()
    output = tmp_path / "文档模式导出.pdf"

    result = DocumentPdfExporter().export(document, output)

    assert result.page_count > 1
    exported = pymupdf.open(output)
    try:
        assert exported.page_count == result.page_count
        assert abs(exported[0].rect.width - document.page_setup.width_pt) < 1
        text = "".join(page.get_text() for page in exported)
        assert "FlowPDF" in text
        assert "中文可搜索" in text.replace(" ", "").replace("\n", "")
        assert any(page.search_for("中文可搜索") for page in exported)
        assert sum(len(page.get_images(full=True)) for page in exported) >= 1
    finally:
        exported.close()


def test_export_replace_failure_preserves_existing_target(qapp, tmp_path, monkeypatch) -> None:
    target = tmp_path / "existing.pdf"
    target.write_bytes(b"existing target")

    def fail_replace(_source, _destination) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr("flowpdf.document_mode.export.pdf_exporter.os.replace", fail_replace)

    with pytest.raises(PdfExportError, match="无法安全导出"):
        DocumentPdfExporter().export(_export_document(), target)

    assert target.read_bytes() == b"existing target"
    assert list(tmp_path.glob(".flowpdf-*.tmp.pdf")) == []


def test_export_cancellation_does_not_modify_target(qapp, tmp_path) -> None:
    target = tmp_path / "cancelled.pdf"
    target.write_bytes(b"keep me")
    checks = 0

    def cancel_during_layout() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 2

    with pytest.raises(PdfExportCancelled):
        DocumentPdfExporter().export(
            _export_document(),
            target,
            cancel_check=cancel_during_layout,
        )

    assert target.read_bytes() == b"keep me"
    assert list(tmp_path.glob(".flowpdf-*.tmp.pdf")) == []


def test_export_honors_structural_page_break(qapp, tmp_path) -> None:
    document = FlowDocument.new()
    document.append_block(Paragraph(runs=[TextRun("硬分页之前")]))
    document.append_block(PageBreak())
    document.append_block(Paragraph(runs=[TextRun("硬分页之后")]))
    output = tmp_path / "硬分页.pdf"

    result = DocumentPdfExporter().export(document, output)
    exported = pymupdf.open(output)
    try:
        assert result.page_count == 2
        assert "硬分页之前" in exported[0].get_text()
        assert "硬分页之后" in exported[1].get_text()
    finally:
        exported.close()


def test_export_reports_preview_page_mismatch_without_changing_page_margins(qapp, tmp_path) -> None:
    document = _export_document()
    output = tmp_path / "分页差异.pdf"

    result = DocumentPdfExporter().export(document, output, expected_page_count=999)

    assert result.preview_page_count == 999
    assert not result.pagination_matches
    exported = pymupdf.open(output)
    try:
        assert exported.page_count == result.page_count
        assert abs(exported[0].rect.height - document.page_setup.height_pt) < 1
    finally:
        exported.close()
