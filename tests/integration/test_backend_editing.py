from __future__ import annotations

import pymupdf
import pytest
from PIL import Image
from tests.generate_test_pdfs import generate_test_pdfs

from flowpdf.backends.base import AnnotationKind, AnnotationSpec, TextStyle
from flowpdf.backends.pymupdf_backend import PyMuPdfBackend
from flowpdf.utils.coordinates import Rect


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
