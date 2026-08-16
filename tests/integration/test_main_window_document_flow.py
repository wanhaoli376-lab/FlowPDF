from __future__ import annotations

import hashlib

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QInputDialog
from tests.generate_test_pdfs import generate_test_pdfs

from flowpdf.application import create_application


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

    window.thumbnail_panel.delete_requested.emit([1])
    assert _wait_until(lambda: window.controller.tasks.active_count == 0)
    assert window.controller.session.page_count == 2

    output = tmp_path / "结果_已修改.pdf"
    window.controller.save_to(output)
    assert _wait_until(lambda: output.exists() and window.controller.tasks.active_count == 0)
    assert hashlib.sha256(source.read_bytes()).digest() == original_hash
    assert window.controller.session.is_dirty is False

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
