from __future__ import annotations

from pathlib import Path

import pytest
from tests.generate_test_pdfs import generate_test_pdfs

from flowpdf.backends.base import PdfSaveError, TextStyle
from flowpdf.backends.pymupdf_backend import PyMuPdfBackend
from flowpdf.services.save_service import SafeSaveError, SafeSaveService
from flowpdf.utils.coordinates import Rect


def test_safe_save_writes_verified_copy_without_changing_source(tmp_path) -> None:
    pdfs = generate_test_pdfs(tmp_path / "fixtures", include_stress=False)
    source = pdfs["normal"]
    source_before = source.read_bytes()
    target = tmp_path / "报告_已修改.pdf"
    backend = PyMuPdfBackend()
    backend.open_document(source)
    backend.add_text(0, Rect(72, 200, 300, 240), "Safely saved", TextStyle())

    result = SafeSaveService().save(backend, target, source_path=source)

    assert result.output_path == target
    assert result.page_count == 2
    assert result.file_size > 0
    assert source.read_bytes() == source_before
    reopened = PyMuPdfBackend()
    reopened.open_document(target)
    assert reopened.search_text("Safely saved")
    assert list(tmp_path.glob("*.tmp.pdf")) == []


def test_save_failure_never_replaces_existing_target(tmp_path) -> None:
    class FailingBackend(PyMuPdfBackend):
        def save_document(self, output_path: str | Path) -> None:
            Path(output_path).write_bytes(b"partial")
            raise PdfSaveError("simulated failure")

    pdfs = generate_test_pdfs(tmp_path / "fixtures", include_stress=False)
    target = tmp_path / "existing.pdf"
    target.write_bytes(b"keep this exact content")
    backend = FailingBackend()
    backend.open_document(pdfs["normal"])

    with pytest.raises(SafeSaveError, match="保存失败"):
        SafeSaveService().save(backend, target, source_path=pdfs["normal"])

    assert target.read_bytes() == b"keep this exact content"
    assert not any(path.name.startswith(".flowpdf-save-") for path in tmp_path.iterdir())


def test_safe_save_refuses_source_overwrite_without_explicit_permission(tmp_path) -> None:
    pdfs = generate_test_pdfs(tmp_path / "fixtures", include_stress=False)
    backend = PyMuPdfBackend()
    backend.open_document(pdfs["normal"])

    with pytest.raises(SafeSaveError, match="原文件"):
        SafeSaveService().save(
            backend,
            pdfs["normal"],
            source_path=pdfs["normal"],
        )
