from __future__ import annotations

from tests.generate_test_pdfs import generate_test_pdfs

from flowpdf.backends.pymupdf_backend import PyMuPdfBackend
from flowpdf.editing.document_session import DocumentSession
from flowpdf.editing.pdf_commands import PdfCommandType
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
