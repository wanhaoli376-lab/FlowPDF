from __future__ import annotations

import pymupdf
import pytest
from PIL import Image
from tests.generate_test_pdfs import generate_test_pdfs

from flowpdf.backends.base import (
    AnnotationKind,
    AnnotationSpec,
    PdfEditError,
    PdfPermissionError,
    PdfResourceLimitError,
    PdfResourceLimits,
    PdfSaveError,
    TextStyle,
)
from flowpdf.backends.pymupdf_backend import PyMuPdfBackend
from flowpdf.editing.text_editor import OverflowStrategy
from flowpdf.utils.coordinates import Rect
from flowpdf.utils.fonts import FontResolver


@pytest.fixture
def pdfs(tmp_path):
    return generate_test_pdfs(tmp_path / "fixtures", include_stress=False)


def test_add_chinese_text_save_and_reopen(pdfs, tmp_path) -> None:
    output = tmp_path / "添加中文_已修改.pdf"
    backend = PyMuPdfBackend()
    backend.open_document(pdfs["normal"])

    backend.add_text(
        0,
        Rect(72, 160, 320, 200),
        "新增中文 2026",
        TextStyle(font_family="Microsoft YaHei", font_size=12),
    )
    backend.save_document(output)
    backend.close_document()

    reopened = PyMuPdfBackend()
    reopened.open_document(output)
    assert reopened.search_text("新增中文")
    assert reopened.search_text("2026")


def test_replace_text_permanently_removes_old_searchable_content(pdfs, tmp_path) -> None:
    output = tmp_path / "replaced.pdf"
    backend = PyMuPdfBackend()
    backend.open_document(pdfs["normal"])
    span = next(span for span in backend.extract_text_spans(0) if "2025" in span.text)

    backend.replace_text(
        0,
        span.rect,
        "FlowPDF normal text 2026",
        TextStyle(font_family="Helvetica", font_size=span.font_size),
    )
    backend.save_document(output)
    backend.close_document()

    reopened = PyMuPdfBackend()
    reopened.open_document(output)
    assert reopened.search_text("2025") == []
    assert reopened.search_text("2026")
    assert "2025" not in "".join(span.text for span in reopened.extract_text_spans(0))


def test_failed_text_replacement_does_not_delete_the_original(pdfs) -> None:
    backend = PyMuPdfBackend()
    backend.open_document(pdfs["normal"])
    span = next(span for span in backend.extract_text_spans(0) if span.text == "Searchable content")

    with pytest.raises(PdfEditError, match="超出文本框"):
        backend.replace_text(
            0,
            span.rect,
            "This replacement is deliberately far too long for the original text box",
            TextStyle(
                font_family=span.font_family,
                font_size=span.font_size,
                overflow=OverflowStrategy.WARN,
            ),
        )

    assert backend.search_text("Searchable content")


def test_live_text_insertion_failure_rolls_back_the_redaction(pdfs, monkeypatch) -> None:
    backend = PyMuPdfBackend()
    backend.open_document(pdfs["normal"])
    span = next(span for span in backend.extract_text_spans(0) if span.text == "Searchable content")
    original_revision = backend.revision
    original_insert = PyMuPdfBackend._insert_prepared_text
    original_redact = backend._redact
    redaction_applied = False

    def track_redaction(*args, **kwargs) -> None:
        nonlocal redaction_applied
        original_redact(*args, **kwargs)
        redaction_applied = True

    def fail_on_live_page(page, prepared, style) -> None:
        if redaction_applied:
            raise PdfEditError("模拟真实页面写入失败")
        original_insert(page, prepared, style)

    monkeypatch.setattr(backend, "_redact", track_redaction)
    monkeypatch.setattr(
        PyMuPdfBackend,
        "_insert_prepared_text",
        staticmethod(fail_on_live_page),
    )

    with pytest.raises(PdfEditError, match="模拟真实页面写入失败"):
        backend.replace_text(
            0,
            span.rect,
            "Searchable contenX",
            TextStyle(
                font_family=span.font_family,
                font_size=span.font_size,
                overflow=OverflowStrategy.AUTO_SHRINK,
            ),
        )

    assert backend.search_text("Searchable content")
    assert backend.revision == original_revision


def test_replacing_text_with_an_empty_value_deletes_the_original(pdfs, tmp_path) -> None:
    output = tmp_path / "deleted-text.pdf"
    backend = PyMuPdfBackend()
    backend.open_document(pdfs["normal"])
    span = next(span for span in backend.extract_text_spans(0) if span.text == "Searchable content")

    backend.replace_text(0, span.rect, "", TextStyle())
    backend.save_document(output)
    backend.close_document()

    reopened = PyMuPdfBackend()
    reopened.open_document(output)
    assert reopened.search_text("Searchable content") == []


def test_chinese_text_can_remove_one_character_and_remain_searchable(pdfs, tmp_path) -> None:
    output = tmp_path / "中文删字.pdf"
    backend = PyMuPdfBackend()
    backend.open_document(pdfs["chinese"])
    span = next(span for span in backend.extract_text_spans(0) if "本地编辑" in span.text)
    replacement = span.text[:-1]

    backend.replace_text(
        0,
        span.rect,
        replacement,
        TextStyle(
            font_family=span.font_family,
            font_size=span.font_size,
            overflow=OverflowStrategy.AUTO_SHRINK,
        ),
    )
    backend.save_document(output)
    backend.close_document()

    reopened = PyMuPdfBackend()
    reopened.open_document(output)
    assert reopened.search_text(replacement)
    assert reopened.search_text(span.text) == []


def test_chinese_replacement_falls_back_when_requested_font_has_no_cjk_glyphs(
    tmp_path,
) -> None:
    output = tmp_path / "中文字体覆盖.pdf"
    backend = PyMuPdfBackend()
    backend.create_document()
    target = Rect(72, 72, 240, 120)

    backend.add_text(
        0,
        target,
        "Original",
        TextStyle(font_family="Helvetica", font_size=14),
    )
    backend.replace_text(
        0,
        target,
        "责任",
        TextStyle(
            font_family="Arial",
            font_size=14,
            overflow=OverflowStrategy.AUTO_SHRINK,
        ),
    )
    backend.save_document(output)
    backend.close_document()

    reopened = PyMuPdfBackend()
    reopened.open_document(output)
    assert reopened.search_text("Original") == []
    assert reopened.search_text("责任")
    span = next(span for span in reopened.extract_text_spans(0) if span.text == "责任")
    assert "Arial" not in span.font_family
    reopened.close_document()


def test_replacement_keeps_old_text_when_no_font_can_display_new_text(tmp_path) -> None:
    source = tmp_path / "font-preflight-source.pdf"
    target = Rect(72, 72, 240, 120)
    creator = PyMuPdfBackend()
    creator.create_document()
    creator.add_text(
        0,
        target,
        "Original",
        TextStyle(font_family="Helvetica", font_size=14),
    )
    creator.save_document(source)
    creator.close_document()

    backend = PyMuPdfBackend(
        font_resolver=FontResolver({"Unavailable": tmp_path / "not-a-font.ttf"})
    )
    backend.open_document(source)
    revision = backend.revision

    with pytest.raises(PdfEditError, match="没有可显示输入文字的字体"):
        backend.replace_text(
            0,
            target,
            "责任",
            TextStyle(font_family="Unavailable", font_size=14),
        )

    assert backend.revision == revision
    assert backend.search_text("Original")
    assert backend.search_text("责任") == []
    backend.close_document()


def test_small_existing_text_can_be_edited_below_six_points(tmp_path) -> None:
    source = tmp_path / "small-text.pdf"
    document = pymupdf.open()
    page = document.new_page(width=300, height=200)
    page.insert_text((40, 60), "Tiny text", fontsize=5)
    document.ez_save(source)
    document.close()
    backend = PyMuPdfBackend()
    backend.open_document(source)
    span = next(span for span in backend.extract_text_spans(0) if span.text == "Tiny text")

    backend.replace_text(
        0,
        span.rect,
        "Tiny tex",
        TextStyle(
            font_family=span.font_family,
            font_size=span.font_size,
            overflow=OverflowStrategy.AUTO_SHRINK,
        ),
    )

    assert backend.search_text("Tiny text") == []
    assert backend.search_text("Tiny tex")


def test_permanent_delete_removes_text_image_and_vector_content(tmp_path) -> None:
    source = tmp_path / "redaction-source.pdf"
    image_path = tmp_path / "redaction-image.png"
    Image.new("RGB", (80, 60), "#EF4444").save(image_path)
    document = pymupdf.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((72, 90), "Permanently remove me")
    page.draw_rect(pymupdf.Rect(60, 120, 250, 220), color=(0, 0, 1), width=4)
    page.insert_image(pymupdf.Rect(300, 120, 460, 240), filename=str(image_path))
    document.ez_save(source)
    document.close()
    output = tmp_path / "permanently-deleted.pdf"
    backend = PyMuPdfBackend()
    backend.open_document(source)

    backend.delete_content(0, Rect(0, 0, 595, 842))
    backend.save_document(output)
    backend.close_document()

    reopened = PyMuPdfBackend()
    reopened.open_document(output)
    assert reopened.search_text("Permanently remove me") == []
    assert reopened.list_images(0) == []
    reopened.close_document()
    verification = pymupdf.open(output)
    drawings = verification[0].get_drawings()
    assert len(drawings) == 1
    assert drawings[0]["fill"] == (1.0, 1.0, 1.0)
    assert drawings[0]["rect"] == pymupdf.Rect(0, 0, 595, 842)
    verification.close()


def test_insert_image_and_annotation_survive_save(pdfs, tmp_path) -> None:
    image_path = tmp_path / "插入图片.webp"
    Image.new("RGBA", (120, 80), (220, 30, 70, 180)).save(image_path)
    output = tmp_path / "image-and-annotation.pdf"
    backend = PyMuPdfBackend()
    backend.open_document(pdfs["normal"])

    backend.add_image(0, Rect(300, 300, 480, 420), image_path)
    backend.add_annotation(
        0,
        AnnotationSpec(
            kind=AnnotationKind.RECTANGLE,
            rect=Rect(65, 75, 260, 105),
            color=(1.0, 0.2, 0.1),
            opacity=0.7,
        ),
    )
    backend.save_document(output)
    backend.close_document()

    document = pymupdf.open(output)
    assert len(document[0].get_images(full=True)) >= 1
    assert sum(1 for _ in document[0].annots()) == 1
    document.close()


def test_image_decode_and_inserted_pdf_are_resource_limited(pdfs, tmp_path) -> None:
    image_path = tmp_path / "too-many-pixels.png"
    Image.new("RGB", (11, 10), "red").save(image_path)
    backend = PyMuPdfBackend(limits=PdfResourceLimits(max_render_pixels=100))
    backend.create_document()

    with pytest.raises(PdfResourceLimitError, match="像素"):
        backend.add_image(0, Rect(10, 10, 100, 100), image_path)

    limited = PyMuPdfBackend(limits=PdfResourceLimits(max_source_bytes=100))
    limited.create_document()
    with pytest.raises(PdfResourceLimitError, match="大小限制"):
        limited.insert_pages(pdfs["normal"], 1)

    object_limited = PyMuPdfBackend(limits=PdfResourceLimits(max_xref_objects=1))
    with pytest.raises(PdfResourceLimitError, match="对象数量"):
        object_limited.open_document(pdfs["normal"])


def test_export_from_encrypted_pdf_keeps_password_protection(pdfs, tmp_path) -> None:
    restricted = PyMuPdfBackend()
    restricted.open_document(pdfs["encrypted"], password="flowpdf-test")
    with pytest.raises(PdfPermissionError, match="所有者密码"):
        restricted.export_pages([0], tmp_path / "restricted.pdf")

    modify_only_path = tmp_path / "modify-only.pdf"
    modify_only = pymupdf.open()
    modify_only.new_page()
    modify_only.save(
        modify_only_path,
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        owner_pw="owner",
        user_pw="user",
        permissions=pymupdf.PDF_PERM_MODIFY,
    )
    modify_only.close()
    user_session = PyMuPdfBackend()
    user_session.open_document(modify_only_path, password="user")
    with pytest.raises(PdfPermissionError, match="所有者密码"):
        user_session.export_pages([0], tmp_path / "must-not-escalate.pdf")

    owner = PyMuPdfBackend()
    owner.open_document(pdfs["encrypted"], password="flowpdf-owner")
    output = tmp_path / "encrypted-export.pdf"
    owner.export_pages([0], output)

    exported = pymupdf.open(output)
    try:
        assert bool(exported.needs_pass) is True
        assert exported.authenticate("flowpdf-owner") > 0
        assert exported.page_count == 1
    finally:
        exported.close()


def test_page_and_object_limits_cannot_be_crossed_by_editing(pdfs) -> None:
    page_limited = PyMuPdfBackend(limits=PdfResourceLimits(max_pages=2))
    page_limited.open_document(pdfs["normal"])
    with pytest.raises(PdfResourceLimitError, match="页数"):
        page_limited.insert_blank_page(1)
    with pytest.raises(PdfResourceLimitError, match="页数"):
        page_limited.duplicate_page(0)

    with pymupdf.open(pdfs["normal"]) as target, pymupdf.open(pdfs["landscape"]) as source:
        object_limit = max(target.xref_length(), source.xref_length()) + 16
    object_limited = PyMuPdfBackend(limits=PdfResourceLimits(max_xref_objects=object_limit))
    object_limited.open_document(pdfs["normal"])
    with pytest.raises(PdfResourceLimitError, match="对象数量"):
        object_limited.insert_pages(pdfs["landscape"], object_limited.page_count())


def test_export_is_atomic_and_never_overwrites_the_source(pdfs, tmp_path, monkeypatch) -> None:
    backend = PyMuPdfBackend()
    backend.open_document(pdfs["normal"])
    target = tmp_path / "existing.pdf"
    target.write_bytes(b"existing target")

    def fail_replace(source, destination):
        raise OSError("simulated replace failure")

    monkeypatch.setattr("flowpdf.backends.pymupdf_backend.os.replace", fail_replace)
    with pytest.raises(PdfSaveError, match="无法安全导出"):
        backend.export_pages([0], target)

    assert target.read_bytes() == b"existing target"
    assert list(tmp_path.glob(".flowpdf-export-*.tmp.pdf")) == []
    with pytest.raises(PdfSaveError, match="不能用页面导出覆盖"):
        backend.export_pages([0], pdfs["normal"])


def test_page_move_delete_rotate_insert_and_merge_round_trip(pdfs, tmp_path) -> None:
    output = tmp_path / "pages.pdf"
    backend = PyMuPdfBackend()
    backend.open_document(pdfs["mixed"])
    original_last_width = backend.page_size(2).width

    backend.move_page(2, 0)
    assert backend.page_size(0).width == original_last_width
    backend.rotate_pages([0], 90)
    assert backend.page_size(0).rotation == 90
    backend.delete_pages([1])
    backend.insert_blank_page(1, width=400, height=500)
    backend.insert_pages(pdfs["landscape"], backend.page_count())
    backend.save_document(output)

    reopened = PyMuPdfBackend()
    reopened.open_document(output)
    assert reopened.page_count() == 4
    assert reopened.page_size(1).width == pytest.approx(400)
