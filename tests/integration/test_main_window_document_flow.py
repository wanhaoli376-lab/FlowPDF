from __future__ import annotations

import hashlib

from PIL import Image
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QInputDialog
from tests.generate_test_pdfs import generate_test_pdfs

from flowpdf.application import create_application
from flowpdf.backends.base import AnnotationKind, AnnotationSpec, TextStyle
from flowpdf.backends.pymupdf_backend import PyMuPdfBackend
from flowpdf.editing.document_session import DocumentSession
from flowpdf.editing.pdf_commands import PdfCommandType
from flowpdf.services.recovery_service import RecoveryService
from flowpdf.utils.coordinates import Rect


def _wait_until(predicate, timeout_ms: int = 5000) -> bool:
    loop = QEventLoop()
    poll = QTimer()
    timeout = QTimer()
    poll.setInterval(20)
    timeout.setSingleShot(True)
    ready = {"value": False}

    def check() -> None:
        if predicate():
            ready["value"] = True
            loop.quit()

    poll.timeout.connect(check)
    timeout.timeout.connect(loop.quit)
    poll.start()
    timeout.start(timeout_ms)
    loop.exec()
    poll.stop()
    timeout.stop()
    return ready["value"]


def test_main_window_opens_and_searches_real_pdf_in_background(tmp_path, qapp) -> None:
    pdfs = generate_test_pdfs(tmp_path / "fixtures", include_stress=False)
    _app, window = create_application(["flowpdf-test"], data_root=tmp_path / "app-data")
    window.resize(1000, 700)
    window.show()

    window.controller.open_path(pdfs["mixed"])
    assert _wait_until(lambda: window.controller.session is not None)
    assert window.document_view.page_scene.pages
    assert window.thumbnail_panel.count() == 3
    assert window.page_status.text() == "第 1 / 3 页"
    assert window.windowTitle().startswith(pdfs["mixed"].name)

    window.controller.search("Mixed page 1")
    assert _wait_until(lambda: window.search_panel.result_count == 1)
    assert window.document_view.current_page == 0

    window.close()
    assert window.controller.is_shutdown


def test_page_edit_undo_and_safe_save_leave_original_unchanged(tmp_path, qapp) -> None:
    pdfs = generate_test_pdfs(tmp_path / "fixtures", include_stress=False)
    source = pdfs["mixed"]
    original_hash = hashlib.sha256(source.read_bytes()).digest()
    _app, window = create_application(["flowpdf-test"], data_root=tmp_path / "app-data")
    window.show()

    window.controller.open_path(source)
    assert _wait_until(lambda: window.controller.session is not None)
    window.controller.rotate_selected_pages([0])
    assert _wait_until(lambda: window.controller.tasks.active_count == 0)
    assert window.controller.session.backend.page_size(0).rotation == 90
    assert window.undo_action.isEnabled()

    window.controller.undo()
    assert _wait_until(lambda: window.controller.tasks.active_count == 0)
    assert window.controller.session.backend.page_size(0).rotation == 0

    window.controller.insert_pdf(pdfs["normal"])
    assert _wait_until(lambda: window.controller.tasks.active_count == 0)
    assert window.controller.session.page_count == 5
    window.controller.undo()
    assert _wait_until(lambda: window.controller.tasks.active_count == 0)
    assert window.controller.session.page_count == 3

    window.thumbnail_panel.delete_requested.emit([1])
    assert _wait_until(lambda: window.controller.tasks.active_count == 0)
    assert window.controller.session.page_count == 2

    output = tmp_path / "结果_已修改.pdf"
    window.controller.save_to(output)
    assert _wait_until(lambda: output.exists() and window.controller.tasks.active_count == 0)
    assert hashlib.sha256(source.read_bytes()).digest() == original_hash
    assert window.controller.session.is_dirty is False

    split_directory = tmp_path / "拆分结果"
    split_directory.mkdir()
    window.controller.split_to_directory(split_directory)
    assert _wait_until(lambda: window.controller.tasks.active_count == 0)
    assert len(list(split_directory.glob("*.pdf"))) == 2

    window.close()
    assert window.controller.is_shutdown


def test_password_pdf_prompts_in_ui_and_keeps_password_in_memory_only(
    tmp_path, qapp, monkeypatch
) -> None:
    pdfs = generate_test_pdfs(tmp_path / "fixtures", include_stress=False)
    prompts: list[str] = []

    def password_dialog(*args, **kwargs):
        prompts.append("asked")
        return "flowpdf-test", True

    monkeypatch.setattr(QInputDialog, "getText", password_dialog)
    _app, window = create_application(["flowpdf-test"], data_root=tmp_path / "app-data")
    window.show()

    window.controller.open_path(pdfs["encrypted"])
    assert _wait_until(lambda: window.controller.session is not None)
    assert prompts == ["asked"]
    assert window.thumbnail_panel.count() == 1

    window.close()
    assert window.controller.is_shutdown


def test_editing_tools_share_history_and_persist_real_pdf_content(tmp_path, qapp) -> None:
    pdfs = generate_test_pdfs(tmp_path / "fixtures", include_stress=False)
    image_path = tmp_path / "图片.webp"
    Image.new("RGBA", (100, 60), (20, 130, 220, 180)).save(image_path)
    _app, window = create_application(["flowpdf-test"], data_root=tmp_path / "app-data")
    errors: list[tuple[str, str]] = []
    window.show_error = lambda title, message: errors.append((title, message))
    window.show()
    window.controller.open_path(pdfs["normal"])
    assert _wait_until(lambda: window.controller.session is not None)

    span = next(
        item
        for item in window.controller.session.backend.extract_text_spans(0)
        if "2025" in item.text
    )
    window.controller.replace_text(
        0,
        span.rect,
        "FlowPDF normal text 2026",
        TextStyle(font_family="Helvetica", font_size=14),
    )
    assert _wait_until(lambda: window.controller.tasks.active_count == 0)
    assert errors == []
    assert window.controller.session.backend.search_text("2025") == []

    window.controller.add_text(
        0,
        Rect(72, 180, 300, 230),
        "Added through controller",
        TextStyle(font_size=12, underline=True),
    )
    assert _wait_until(lambda: window.controller.tasks.active_count == 0)
    window.controller.add_image(0, Rect(320, 180, 480, 280), image_path)
    assert _wait_until(lambda: window.controller.tasks.active_count == 0)
    window.controller.add_annotation(
        0,
        AnnotationSpec(
            AnnotationKind.RECTANGLE,
            Rect(60, 165, 490, 290),
            color=(0.1, 0.4, 0.9),
        ),
    )
    assert _wait_until(lambda: window.controller.tasks.active_count == 0)
    assert window.annotation_panel.count() == 1
    annotation = window.controller.session.backend.list_annotations(0)[0]
    window.annotation_panel.delete_requested.emit(0, annotation.xref)
    assert _wait_until(lambda: window.controller.tasks.active_count == 0)
    assert window.annotation_panel.count() == 0
    window.controller.undo()
    assert _wait_until(lambda: window.controller.tasks.active_count == 0)
    assert window.annotation_panel.count() == 1

    output = tmp_path / "编辑工具结果.pdf"
    window.controller.save_to(output)
    assert _wait_until(lambda: output.exists() and window.controller.tasks.active_count == 0)
    verify = PyMuPdfBackend()
    verify.open_document(output)
    assert len(verify.search_text("FlowPDF normal text 2026")) == 1
    assert len(verify.search_text("Added through controller")) == 1
    assert verify.list_images(0)
    verify.close_document()
    assert errors == []

    window.close()
    assert window.controller.is_shutdown


def test_controller_recovers_command_log_without_overwriting_source(tmp_path, qapp) -> None:
    pdfs = generate_test_pdfs(tmp_path / "fixtures", include_stress=False)
    data_root = tmp_path / "app-data"
    recovery = RecoveryService(data_root / "recovery")
    interrupted = DocumentSession(PyMuPdfBackend(), recovery_service=recovery)
    interrupted.open(pdfs["normal"])
    interrupted.execute(PdfCommandType.ROTATE_PAGES, page_indices=[0], degrees=90)
    recovery_path = interrupted.flush_recovery()
    interrupted.close()
    assert recovery_path is not None

    _app, window = create_application(["flowpdf-test"], data_root=data_root)
    window.show()
    window.controller.recover_path(recovery_path)
    assert _wait_until(lambda: window.controller.session is not None)

    assert window.controller.session.backend.page_size(0).rotation == 90
    assert window.controller.session.is_dirty is True
    assert window.controller.session.saved_path is None
    assert pdfs["normal"].exists()

    assert window.controller.close_document(discard=True)
    assert not recovery_path.exists()
    window.close()
    assert window.controller.is_shutdown
