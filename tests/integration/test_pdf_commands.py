from __future__ import annotations

import pytest
from tests.generate_test_pdfs import generate_test_pdfs

from flowpdf.backends.pymupdf_backend import PyMuPdfBackend
from flowpdf.editing.command_stack import CommandStack
from flowpdf.editing.pdf_commands import (
    PdfCommandType,
    PdfHistoryLimitError,
    PdfMutationCommand,
)


def _page_text(backend: PyMuPdfBackend, page: int) -> str:
    return "".join(span.text for span in backend.extract_text_spans(page))


def test_page_commands_share_one_history_and_restore_real_pdf_state(tmp_path) -> None:
    pdfs = generate_test_pdfs(tmp_path / "fixtures", include_stress=False)
    backend = PyMuPdfBackend()
    backend.open_document(pdfs["normal"])
    stack = CommandStack()

    stack.push(
        PdfMutationCommand(
            backend,
            PdfCommandType.MOVE_PAGE,
            {"old_index": 1, "new_index": 0},
        )
    )
    assert "Second page" in _page_text(backend, 0)

    stack.push(
        PdfMutationCommand(
            backend,
            PdfCommandType.DELETE_PAGES,
            {"page_indices": [1]},
        )
    )
    assert backend.page_count() == 1
    assert stack.undo() is True
    assert backend.page_count() == 2
    assert "FlowPDF normal" in _page_text(backend, 1)
    assert stack.undo() is True
    assert "FlowPDF normal" in _page_text(backend, 0)
    assert stack.redo() is True
    assert "Second page" in _page_text(backend, 0)


def test_command_serialization_contains_replay_data_but_no_pdf_snapshot(tmp_path) -> None:
    pdfs = generate_test_pdfs(tmp_path / "fixtures", include_stress=False)
    backend = PyMuPdfBackend()
    backend.open_document(pdfs["mixed"])
    command = PdfMutationCommand(
        backend,
        PdfCommandType.ROTATE_PAGES,
        {"page_indices": [0, 2], "degrees": 90},
    )

    command.execute()
    record = command.serialize()

    assert record == {
        "type": "rotate_pages",
        "page_indices": [0, 2],
        "degrees": 90,
    }
    assert all("snapshot" not in key for key in record)


def test_oversized_source_is_rejected_before_creating_any_snapshot(tmp_path) -> None:
    source = tmp_path / "large-source.pdf"
    source.write_bytes(b"x")

    class SnapshotTrap:
        def __init__(self, source_path):
            self.source_path = source_path

        def document_bytes(self):
            raise AssertionError("snapshot must not be allocated")

    command = PdfMutationCommand(
        SnapshotTrap(source),
        PdfCommandType.DELETE_PAGES,
        {"page_indices": [0]},
        max_history_bytes=3,
        source_size_bytes=1,
    )

    with pytest.raises(PdfHistoryLimitError, match="安全编辑快照上限"):
        command.execute()
