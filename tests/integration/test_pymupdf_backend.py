from __future__ import annotations

import pytest
from tests.generate_test_pdfs import generate_test_pdfs

from flowpdf.backends.base import InvalidPasswordError, PasswordRequiredError, PdfOpenError
from flowpdf.backends.pymupdf_backend import PyMuPdfBackend


@pytest.fixture
def pdfs(tmp_path):
    return generate_test_pdfs(tmp_path / "PDF 测试", include_stress=False)


def test_backend_opens_renders_extracts_and_searches_real_pdf(pdfs) -> None:
    backend = PyMuPdfBackend()
    backend.open_document(pdfs["normal"])

    assert backend.page_count() == 2
    assert backend.page_size(0).width == pytest.approx(595)
    assert any("FlowPDF normal" in span.text for span in backend.extract_text_spans(0))
    assert [hit.page_index for hit in backend.search_text("Searchable")] == [0]

    rendered = backend.render_page(0, scale=0.5)
    assert rendered.width == 298
    assert rendered.height == 421
    assert len(rendered.samples) == rendered.stride * rendered.height
    backend.close_document()


def test_backend_requires_password_and_never_accepts_wrong_password(pdfs) -> None:
    backend = PyMuPdfBackend()

    with pytest.raises(PasswordRequiredError):
        backend.open_document(pdfs["encrypted"])
    with pytest.raises(InvalidPasswordError):
        backend.open_document(pdfs["encrypted"], password="wrong")

    backend.open_document(pdfs["encrypted"], password="flowpdf-test")
    assert backend.page_count() == 1
    backend.close_document()


def test_backend_converts_malformed_pdf_errors_to_understandable_error(pdfs) -> None:
    backend = PyMuPdfBackend()

    with pytest.raises(PdfOpenError, match="无法打开 PDF"):
        backend.open_document(pdfs["corrupt"])


def test_scanned_page_detection_uses_missing_text_layer_and_images(pdfs) -> None:
    backend = PyMuPdfBackend()
    backend.open_document(pdfs["scanned"])

    assert backend.is_probably_scanned(0) is True
