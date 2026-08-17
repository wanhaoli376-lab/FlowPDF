from __future__ import annotations

import time
from pathlib import Path

import pymupdf
from PySide6.QtGui import QTextCursor

from flowpdf.application import create_application


def _wait_until(qapp, predicate, timeout: float = 8.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _single_column_pdf(path: Path) -> None:
    document = pymupdf.open()
    for page_index in range(2):
        page = document.new_page(width=320, height=360)
        page.insert_textbox(
            pymupdf.Rect(36, 32, 284, 70),
            "FlowPDF Document Mode" if page_index == 0 else "Second Page",
            fontname="helv",
            fontsize=17,
            align=pymupdf.TEXT_ALIGN_CENTER,
        )
        for paragraph_index in range(4):
            y = 84 + paragraph_index * 56
            page.insert_textbox(
                pymupdf.Rect(42, y, 278, y + 46),
                f"Paragraph {page_index + 1}-{paragraph_index + 1} keeps flowing after edits.",
                fontname="helv",
                fontsize=11,
            )
    document.save(path)
    document.close()


def test_application_document_mode_closed_edit_project_export_loop(qapp, tmp_path) -> None:
    source = tmp_path / "单栏报告.pdf"
    project = tmp_path / "单栏报告.flowpdfproj"
    output = tmp_path / "单栏报告_文档模式.pdf"
    _single_column_pdf(source)
    _app, window = create_application(["flowpdf-test"], data_root=tmp_path / "app-data")
    controller = window.document_mode_controller

    controller.import_pdf(source)
    assert _wait_until(qapp, lambda: controller.document is not None)
    assert window.active_mode == "document"
    assert window.document_editor_view.editor.toPlainText().startswith("FlowPDF")
    assert controller.import_report is not None
    assert controller.import_report.score >= 60

    editor = window.document_editor_view.editor
    cursor = QTextCursor(editor.document())
    cursor.setPosition(len("FlowPDF"))
    inserted = "新增中文内容会推动后续段落并自动跨页。" * 20
    cursor.insertText(inserted)
    assert controller.is_dirty
    assert editor.page_count >= 2

    controller.save_project_to(project)
    assert _wait_until(qapp, lambda: project.exists() and controller.tasks.active_count == 0)
    assert not controller.is_dirty

    assert controller.close_document(discard=True)
    controller.open_project(project)
    assert _wait_until(qapp, lambda: controller.document is not None)
    assert inserted in editor.toPlainText()

    controller.export_pdf_to(output)
    assert _wait_until(qapp, lambda: output.exists() and controller.tasks.active_count == 0)
    exported = pymupdf.open(output)
    try:
        extracted = "".join(page.get_text() for page in exported)
        assert inserted[:12] in extracted.replace(" ", "").replace("\n", "")
        assert any(page.search_for(inserted[:8]) for page in exported)
    finally:
        exported.close()

    window.close()
    assert controller.is_shutdown


def test_mode_coordinator_uses_analysis_choice_and_document_toolbar(qapp, tmp_path) -> None:
    source = tmp_path / "推荐模式.pdf"
    _single_column_pdf(source)
    _app, window = create_application(["flowpdf-test"], data_root=tmp_path / "app-data")
    coordinator = window.lifecycle_controller
    coordinator.mode_selector = lambda _report: "document"

    coordinator.open_path(source)
    assert _wait_until(qapp, lambda: window.active_mode == "document")
    assert window.document_mode_action.isChecked()
    assert window.document_toolbar.isVisibleTo(window)
    assert not window.page_menu.isEnabled()

    editor = window.document_editor_view.editor
    cursor = editor.textCursor()
    cursor.setPosition(0)
    cursor.setPosition(7, QTextCursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor)
    window.document_toolbar.bold_action.trigger()
    paragraph = editor.flow_document().sections[0].blocks[0]
    assert paragraph.runs[0].style.bold

    assert window.document_mode_controller.close_document(discard=True)
    window.close()


def test_mode_coordinator_can_keep_original_layout_after_analysis(qapp, tmp_path) -> None:
    source = tmp_path / "保持版式.pdf"
    _single_column_pdf(source)
    _app, window = create_application(["flowpdf-test"], data_root=tmp_path / "app-data")
    coordinator = window.lifecycle_controller
    coordinator.mode_selector = lambda _report: "layout"

    coordinator.open_path(source)
    assert _wait_until(qapp, lambda: window.controller.session is not None)
    assert window.active_mode == "layout"
    assert window.layout_mode_action.isChecked()
    assert not window.document_toolbar.isVisibleTo(window)

    window.close()


def test_document_controller_checkpoints_dirty_model_and_clears_after_project_save(
    qapp, tmp_path
) -> None:
    source = tmp_path / "恢复来源.pdf"
    project = tmp_path / "恢复工程.flowpdfproj"
    _single_column_pdf(source)
    _app, window = create_application(["flowpdf-test"], data_root=tmp_path / "app-data")
    controller = window.document_mode_controller
    controller.import_pdf(source)
    assert _wait_until(qapp, lambda: controller.document is not None)
    editor = window.document_editor_view.editor
    editor.moveCursor(QTextCursor.MoveOperation.End)
    editor.insertPlainText("需要恢复的中文修改")

    controller.flush_recovery()
    assert _wait_until(qapp, lambda: controller.recovery_tasks.active_count == 0)
    records = controller.recovery_service.list_sessions()
    assert len(records) == 1
    assert "需要恢复的中文修改" in records[0].document.plain_text

    controller.save_project_to(project)
    assert _wait_until(qapp, lambda: project.exists() and controller.tasks.active_count == 0)
    assert controller.recovery_service.list_sessions() == []

    window.close()
