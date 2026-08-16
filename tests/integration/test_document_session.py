from __future__ import annotations

import pymupdf
import pytest
from tests.generate_test_pdfs import generate_test_pdfs

from flowpdf.backends.pymupdf_backend import PyMuPdfBackend
from flowpdf.editing.document_session import DocumentSession
from flowpdf.editing.pdf_commands import PdfCommandType, PdfHistoryLimitError
from flowpdf.services.recovery_service import RecoveryService


def test_session_writes_compact_recovery_log_and_replays_commands(tmp_path) -> None:
    pdfs = generate_test_pdfs(tmp_path / "fixtures", include_stress=False)
    recovery = RecoveryService(tmp_path / "recovery")
    session = DocumentSession(PyMuPdfBackend(), recovery_service=recovery)
    session.open(pdfs["normal"])
    session.execute(PdfCommandType.MOVE_PAGE, old_index=1, new_index=0)
    session.execute(PdfCommandType.ROTATE_PAGES, page_indices=[0], degrees=90)

    recovery_path = session.flush_recovery()
    assert recovery_path is not None
    assert recovery_path.stat().st_size < pdfs["normal"].stat().st_size
    session.close()

    restored = DocumentSession(PyMuPdfBackend(), recovery_service=recovery)
    restored.recover(recovery_path)

    assert restored.page_count == 2
    assert restored.backend.page_size(0).rotation == 90
    assert "Second page" in "".join(span.text for span in restored.backend.extract_text_spans(0))
    assert restored.is_dirty is True


def test_undo_redo_and_successful_save_update_session_state(tmp_path) -> None:
    pdfs = generate_test_pdfs(tmp_path / "fixtures", include_stress=False)
    recovery = RecoveryService(tmp_path / "recovery")
    session = DocumentSession(PyMuPdfBackend(), recovery_service=recovery)
    session.open(pdfs["mixed"])
    session.execute(PdfCommandType.DELETE_PAGES, page_indices=[1])
    assert session.page_count == 2

    assert session.undo() is True
    assert session.page_count == 3
    assert session.redo() is True
    assert session.page_count == 2
    session.flush_recovery()

    target = tmp_path / "mixed_已修改.pdf"
    session.save(target)

    assert session.is_dirty is False
    assert session.saved_path == target
    assert recovery.list_sessions() == []


def test_new_document_is_dirty_until_first_safe_save(tmp_path) -> None:
    recovery = RecoveryService(tmp_path / "recovery")
    session = DocumentSession(PyMuPdfBackend(), recovery_service=recovery)

    session.create_new()

    assert session.is_dirty is True
    recovery_path = session.flush_recovery()
    assert recovery_path is not None
    output = tmp_path / "新建文档.pdf"
    session.save(output)
    assert session.is_dirty is False
    assert output.exists()
    assert recovery.list_sessions() == []


def test_edit_is_not_applied_when_snapshot_history_budget_is_too_small(tmp_path) -> None:
    session = DocumentSession(
        PyMuPdfBackend(),
        recovery_service=RecoveryService(tmp_path / "recovery"),
        max_history_bytes=1,
    )
    session.create_new()

    with pytest.raises(PdfHistoryLimitError, match="撤销内存预算"):
        session.execute(PdfCommandType.INSERT_BLANK_PAGE, insert_index=1)

    assert session.page_count == 1


def test_recovery_keeps_commands_evicted_from_undo_snapshots(tmp_path) -> None:
    pdfs = generate_test_pdfs(tmp_path / "fixtures", include_stress=False)
    recovery = RecoveryService(tmp_path / "recovery")
    session = DocumentSession(
        PyMuPdfBackend(),
        recovery_service=recovery,
        max_history=1,
    )
    session.open(pdfs["normal"])
    original_pages = session.page_count
    session.execute(PdfCommandType.ROTATE_PAGES, page_indices=[0], degrees=90)
    session.execute(PdfCommandType.INSERT_BLANK_PAGE, insert_index=1)

    recovery_path = session.flush_recovery()
    assert recovery_path is not None
    assert len(session.command_stack.serialize()) == 2

    restored = DocumentSession(
        PyMuPdfBackend(),
        recovery_service=recovery,
        max_history=1,
    )
    restored.recover(recovery_path)
    assert restored.page_count == original_pages + 1
    assert restored.backend.page_size(0).rotation == 90


def test_pristine_encrypted_document_uses_original_bytes_for_rendering(tmp_path) -> None:
    pdfs = generate_test_pdfs(tmp_path / "fixtures", include_stress=False)
    session = DocumentSession(
        PyMuPdfBackend(),
        recovery_service=RecoveryService(tmp_path / "recovery"),
    )
    session.open(pdfs["encrypted"], password="flowpdf-test")

    data, password = session.render_snapshot_data()

    assert data == pdfs["encrypted"].read_bytes()
    assert password == "flowpdf-test"


def test_encrypted_pdf_remains_encrypted_after_edit_undo_and_safe_save(tmp_path) -> None:
    pdfs = generate_test_pdfs(tmp_path / "fixtures", include_stress=False)
    session = DocumentSession(
        PyMuPdfBackend(),
        recovery_service=RecoveryService(tmp_path / "recovery"),
    )
    session.open(pdfs["encrypted"], password="flowpdf-owner")
    session.execute(PdfCommandType.ROTATE_PAGES, page_indices=[0], degrees=90)
    assert session.undo() is True
    output = tmp_path / "加密副本_已修改.pdf"

    session.save(output)

    saved = pymupdf.open(output)
    try:
        assert bool(saved.needs_pass) is True
        assert saved.authenticate("flowpdf-test") > 0
        assert saved.page_count == 1
    finally:
        saved.close()
