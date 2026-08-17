from __future__ import annotations

import io

import pymupdf
import pytest
from PIL import Image

from flowpdf.document_mode.importing import ImportCancelled, PdfImportError, PdfImportService
from flowpdf.document_mode.models import BlockImage, Paragraph, SemanticRole


def _create_two_page_chinese_report(path) -> None:
    document = pymupdf.open()
    first = document.new_page(width=595, height=842)
    first.insert_text(
        (72, 92),
        "FlowPDF 文档模式",
        fontname="china-s",
        fontsize=22,
    )
    first.insert_text(
        (72, 145),
        "这是第一段中文正文，用于验证单栏文档的阅读顺序。",
        fontname="china-s",
        fontsize=12,
    )
    first.insert_text(
        (72, 170),
        "同一段的第二行应该跟随上一行，而不是成为固定文字框。",
        fontname="china-s",
        fontsize=12,
    )
    second = document.new_page(width=595, height=842)
    second.insert_text(
        (72, 92),
        "第二页正文会进入同一个连续文档。",
        fontname="china-s",
        fontsize=12,
    )
    document.ez_save(path)
    document.close()


def test_import_single_column_pdf_reconstructs_title_and_continuous_paragraphs(tmp_path) -> None:
    source = tmp_path / "单栏中文两页.pdf"
    _create_two_page_chinese_report(source)

    result = PdfImportService().import_file(source)

    paragraphs = [
        block
        for section in result.document.sections
        for block in section.blocks
        if isinstance(block, Paragraph)
    ]
    assert paragraphs[0].semantic_role is SemanticRole.TITLE
    assert paragraphs[0].text == "FlowPDF 文档模式"
    assert "第一段中文正文" in result.document.plain_text
    assert "第二页正文会进入同一个连续文档" in result.document.plain_text
    assert [paragraph.source_ref.page_index for paragraph in paragraphs] == [0, 0, 1]
    assert result.report.score >= 80
    assert result.report.recommended_mode == "document"


def test_import_places_bitmap_between_surrounding_paragraphs_and_marks_caption(tmp_path) -> None:
    source = tmp_path / "图片和图注.pdf"
    image = Image.new("RGB", (160, 80), "#2563eb")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    pdf = pymupdf.open()
    page = pdf.new_page(width=595, height=842)
    page.insert_text((72, 90), "图片前的正文", fontname="china-s", fontsize=12)
    page.insert_image(pymupdf.Rect(72, 120, 312, 240), stream=buffer.getvalue())
    page.insert_text((72, 270), "图 1：蓝色示例图", fontname="china-s", fontsize=10)
    pdf.ez_save(source)
    pdf.close()

    result = PdfImportService().import_file(source)

    blocks = result.document.sections[0].blocks
    assert [type(block) for block in blocks] == [Paragraph, BlockImage, Paragraph]
    assert blocks[2].semantic_role is SemanticRole.CAPTION
    image_block = blocks[1]
    assert isinstance(image_block, BlockImage)
    assert result.document.assets[image_block.asset_id].data


def test_import_detects_repeated_headers_footers_without_polluting_body(tmp_path) -> None:
    source = tmp_path / "重复页眉页脚.pdf"
    pdf = pymupdf.open()
    for page_number in range(1, 4):
        page = pdf.new_page(width=595, height=842)
        page.insert_text((72, 40), "FlowPDF 内部报告", fontname="china-s", fontsize=9)
        page.insert_text(
            (72, 110),
            f"第 {page_number} 页的独立正文内容",
            fontname="china-s",
            fontsize=12,
        )
        page.insert_text((72, 805), "仅供内部使用", fontname="china-s", fontsize=9)
        page.insert_text((292, 825), str(page_number), fontsize=9)
    pdf.ez_save(source)
    pdf.close()

    result = PdfImportService().import_file(source)

    assert [paragraph.text for paragraph in result.document.headers] == ["FlowPDF 内部报告"]
    assert "仅供内部使用" in [paragraph.text for paragraph in result.document.footers]
    assert "FlowPDF 内部报告" not in result.document.plain_text
    assert "仅供内部使用" not in result.document.plain_text
    assert result.report.detected_headers == ["flowpdf 内部报告"]


def test_import_scores_two_column_pdf_for_layout_mode(tmp_path) -> None:
    source = tmp_path / "双栏论文.pdf"
    pdf = pymupdf.open()
    page = pdf.new_page(width=595, height=842)
    for index, y in enumerate((100, 130, 160), start=1):
        page.insert_text((54, y), f"Left column paragraph {index}", fontsize=11)
        page.insert_text((330, y), f"Right column paragraph {index}", fontsize=11)
    pdf.ez_save(source)
    pdf.close()

    result = PdfImportService().import_file(source)

    assert result.report.detected_columns == 2
    assert result.report.score < 60
    assert result.report.recommended_mode == "layout"
    assert any("双栏" in warning for warning in result.report.warnings)


def test_import_scores_scanned_page_for_layout_mode_without_crashing(tmp_path) -> None:
    source = tmp_path / "扫描页.pdf"
    image = Image.new("RGB", (600, 800), "white")
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=80)
    pdf = pymupdf.open()
    page = pdf.new_page(width=595, height=842)
    page.insert_image(page.rect, stream=buffer.getvalue())
    pdf.ez_save(source)
    pdf.close()

    result = PdfImportService().import_file(source)

    assert result.report.score < 60
    assert result.report.recommended_mode == "layout"
    assert any("扫描" in warning for warning in result.report.warnings)
    assert any(isinstance(block, BlockImage) for block in result.document.sections[0].blocks)


def test_import_reconstructs_bullet_numbering_and_conditional_english_hyphen(tmp_path) -> None:
    source = tmp_path / "lists-and-hyphen.pdf"
    pdf = pymupdf.open()
    page = pdf.new_page(width=595, height=842)
    page.insert_text((72, 100), "- Bullet item", fontsize=11)
    page.insert_text((72, 130), "1. Numbered item", fontsize=11)
    page.insert_text((72, 180), "electro-", fontsize=11)
    page.insert_text((72, 193), "magnetic field", fontsize=11)
    pdf.ez_save(source)
    pdf.close()

    result = PdfImportService().import_file(source)
    paragraphs = [
        block for block in result.document.sections[0].blocks if isinstance(block, Paragraph)
    ]

    assert paragraphs[0].semantic_role is SemanticRole.LIST_ITEM
    assert paragraphs[0].style.list_kind == "bullet"
    assert paragraphs[0].text == "Bullet item"
    assert paragraphs[1].semantic_role is SemanticRole.LIST_ITEM
    assert paragraphs[1].style.list_kind == "number"
    assert paragraphs[1].text == "Numbered item"
    assert paragraphs[2].text == "electromagnetic field"


def test_import_can_be_cancelled_between_pages(tmp_path) -> None:
    source = tmp_path / "cancel-import.pdf"
    pdf = pymupdf.open()
    for index in range(3):
        page = pdf.new_page(width=595, height=842)
        page.insert_text((72, 90), f"Page {index + 1}")
    pdf.ez_save(source)
    pdf.close()
    checks = 0

    def cancel_after_first_check() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 2

    with pytest.raises(ImportCancelled):
        PdfImportService().import_file(source, cancel_check=cancel_after_first_check)


def test_import_converts_truncated_pdf_to_user_facing_error(tmp_path) -> None:
    source = tmp_path / "truncated.pdf"
    source.write_bytes(b"%PDF-1.7\ntruncated")

    with pytest.raises(PdfImportError, match="无法导入"):
        PdfImportService().import_file(source)


def test_import_warns_about_mixed_page_sizes_but_keeps_text_order(tmp_path) -> None:
    source = tmp_path / "混合页面尺寸.pdf"
    pdf = pymupdf.open()
    first = pdf.new_page(width=595, height=842)
    first.insert_text((72, 90), "First page")
    second = pdf.new_page(width=842, height=595)
    second.insert_text((72, 90), "Second landscape page")
    pdf.ez_save(source)
    pdf.close()

    result = PdfImportService().import_file(source)

    assert result.document.plain_text.splitlines() == ["First page", "Second landscape page"]
    assert any("混合页面尺寸" in warning for warning in result.report.warnings)
