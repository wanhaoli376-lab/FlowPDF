from __future__ import annotations

import time
from pathlib import Path
from threading import Event

import pymupdf
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QMessageBox

from flowpdf.application import create_application
from flowpdf.document_mode.export import ProjectReader
from flowpdf.document_mode.models import FlowDocument, Paragraph, TextRun


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
    editor.set_zoom_factor(1.3)
    assert controller.is_dirty
    assert editor.page_count >= 2
    canvas_scroll = window.document_editor_view.editor_canvas.verticalScrollBar()
    canvas_scroll.setValue(min(180, canvas_scroll.maximum()))
    saved_scroll_y = canvas_scroll.value()
    assert saved_scroll_y > 0

    controller.save_project_to(project)
    assert _wait_until(qapp, lambda: project.exists() and controller.tasks.active_count == 0)
    assert not controller.is_dirty

    assert controller.close_document(discard=True)
    controller.open_project(project)
    assert _wait_until(qapp, lambda: controller.document is not None)
    assert inserted in editor.toPlainText()
    assert editor.zoom_factor == 1.3
    assert window.document_editor_view.editor_canvas.verticalScrollBar().value() == saved_scroll_y

    controller.export_pdf_to(output)
    assert _wait_until(qapp, lambda: output.exists() and controller.tasks.active_count == 0)
    exported = pymupdf.open(output)
    try:
        assert exported.page_count == editor.page_count
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


def test_document_to_layout_switch_exports_validated_snapshot_and_cleans_it_on_exit(
    qapp, tmp_path, monkeypatch
) -> None:
    source = tmp_path / "切换来源.pdf"
    _single_column_pdf(source)
    data_root = tmp_path / "app-data"
    _app, window = create_application(["flowpdf-test"], data_root=data_root)
    controller = window.document_mode_controller
    controller.import_pdf(source)
    assert _wait_until(qapp, lambda: controller.document is not None)
    window.document_editor_view.editor.insertPlainText("切换前的修改")
    monkeypatch.setattr(
        "flowpdf.mode_coordinator.QMessageBox.warning",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )

    window.lifecycle_controller.switch_to_layout_mode()
    assert _wait_until(qapp, lambda: window.controller.session is not None)
    assert window.active_mode == "layout"
    assert controller.document is None
    snapshots = list((data_root / "temp").glob("flowpdf-*.pdf"))
    assert len(snapshots) == 1
    verify = pymupdf.open(snapshots[0])
    verify.close()

    window.close()
    assert not snapshots[0].exists()


def test_project_save_keeps_late_edits_dirty_and_requires_a_second_snapshot(
    qapp, tmp_path, monkeypatch
) -> None:
    source = tmp_path / "异步保存来源.pdf"
    project = tmp_path / "异步保存.flowpdfproj"
    _single_column_pdf(source)
    _app, window = create_application(["flowpdf-test"], data_root=tmp_path / "app-data")
    controller = window.document_mode_controller
    controller.import_pdf(source)
    assert _wait_until(qapp, lambda: controller.document is not None)
    editor = window.document_editor_view.editor
    editor.insertPlainText("保存快照之前")

    started = Event()
    release = Event()
    original_save = controller._writer.save

    def delayed_save(*args, **kwargs):
        started.set()
        if not release.wait(5):
            raise RuntimeError("测试未释放工程保存")
        return original_save(*args, **kwargs)

    monkeypatch.setattr(controller._writer, "save", delayed_save)
    controller.save_project_to(project)
    assert _wait_until(qapp, started.is_set)
    editor.insertPlainText("保存期间新增内容")
    release.set()
    assert _wait_until(qapp, lambda: controller.tasks.active_count == 0)

    assert controller.is_dirty
    assert "保存期间新增内容" not in ProjectReader().load(project).document.plain_text

    monkeypatch.setattr(controller._writer, "save", original_save)
    controller.save_project_to(project)
    assert _wait_until(qapp, lambda: controller.tasks.active_count == 0)
    assert not controller.is_dirty
    assert "保存期间新增内容" in ProjectReader().load(project).document.plain_text
    controller.close_document(discard=True)
    window.close()


def test_document_to_layout_switch_refuses_to_discard_edits_made_during_export(
    qapp, tmp_path, monkeypatch
) -> None:
    source = tmp_path / "切换竞态来源.pdf"
    _single_column_pdf(source)
    data_root = tmp_path / "app-data"
    _app, window = create_application(["flowpdf-test"], data_root=data_root)
    controller = window.document_mode_controller
    controller.import_pdf(source)
    assert _wait_until(qapp, lambda: controller.document is not None)
    editor = window.document_editor_view.editor
    editor.insertPlainText("导出前内容")

    started = Event()
    release = Event()
    original_export = controller._exporter.export

    def delayed_export(*args, **kwargs):
        started.set()
        if not release.wait(5):
            raise RuntimeError("测试未释放 PDF 导出")
        return original_export(*args, **kwargs)

    monkeypatch.setattr(controller._exporter, "export", delayed_export)
    monkeypatch.setattr(
        "flowpdf.mode_coordinator.QMessageBox.warning",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
    )
    window.lifecycle_controller.switch_to_layout_mode()
    assert _wait_until(qapp, started.is_set)
    editor.insertPlainText("导出期间新增内容")
    release.set()
    assert _wait_until(qapp, lambda: controller.tasks.active_count == 0)

    assert window.active_mode == "document"
    assert controller.document is not None
    assert controller.is_dirty
    assert "导出期间新增内容" in editor.toPlainText()
    assert list((data_root / "temp").glob("flowpdf-*.pdf")) == []
    controller.close_document(discard=True)
    window.close()


def test_project_save_cancels_inflight_recovery_without_reviving_checkpoint(
    qapp, tmp_path, monkeypatch
) -> None:
    source = tmp_path / "恢复竞态来源.pdf"
    project = tmp_path / "恢复竞态.flowpdfproj"
    _single_column_pdf(source)
    _app, window = create_application(["flowpdf-test"], data_root=tmp_path / "app-data")
    controller = window.document_mode_controller
    controller.import_pdf(source)
    assert _wait_until(qapp, lambda: controller.document is not None)
    window.document_editor_view.editor.insertPlainText("需要保存的修改")

    started = Event()
    release = Event()
    original_write = controller.recovery_service.write

    def delayed_write(*args, **kwargs):
        started.set()
        if not release.wait(5):
            raise RuntimeError("测试未释放恢复写入")
        return original_write(*args, **kwargs)

    monkeypatch.setattr(controller.recovery_service, "write", delayed_write)
    controller.flush_recovery()
    assert _wait_until(qapp, started.is_set)
    controller.save_project_to(project)
    assert _wait_until(qapp, lambda: controller.tasks.active_count == 0)
    release.set()
    assert _wait_until(qapp, lambda: controller.recovery_tasks.active_count == 0)

    assert not controller.is_dirty
    assert controller.recovery_service.list_sessions() == []
    controller.close_document(discard=True)
    window.close()


def test_reimport_after_discard_removes_previous_document_recovery(
    qapp, tmp_path, monkeypatch
) -> None:
    first = tmp_path / "旧文档.pdf"
    second = tmp_path / "新文档.pdf"
    _single_column_pdf(first)
    _single_column_pdf(second)
    _app, window = create_application(["flowpdf-test"], data_root=tmp_path / "app-data")
    coordinator = window.lifecycle_controller
    coordinator.mode_selector = lambda _report: "document"
    coordinator.open_path(first)
    assert _wait_until(qapp, lambda: window.active_mode == "document")
    controller = window.document_mode_controller
    window.document_editor_view.editor.insertPlainText("旧文档未保存修改")
    controller.flush_recovery()
    assert _wait_until(qapp, lambda: controller.recovery_tasks.active_count == 0)
    assert len(controller.recovery_service.list_sessions()) == 1

    monkeypatch.setattr(
        "flowpdf.mode_coordinator.QMessageBox.warning",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Discard,
    )
    coordinator.open_path(second)
    assert _wait_until(
        qapp,
        lambda: (
            controller.document is not None
            and controller.document.metadata.source_pdf_path == str(second.resolve())
        ),
    )

    assert controller.recovery_service.list_sessions() == []
    controller.close_document(discard=True)
    window.close()


def test_main_window_routes_fit_actions_to_the_active_document_editor(qapp, tmp_path) -> None:
    _app, window = create_application(["flowpdf-test"], data_root=tmp_path / "app-data")
    document = FlowDocument.new()
    document.append_block(Paragraph(runs=[TextRun("适应页面与适应宽度")]))
    window.resize(1600, 720)
    window.show_document_editor(document)
    window.show()
    qapp.processEvents()

    assert window.fit_width_action.isEnabled()
    assert window.fit_page_action.isEnabled()
    window.fit_width_action.trigger()
    width_factor = window.document_editor_view.editor.zoom_factor
    assert width_factor == window.document_editor_view.editor_canvas.transform().m11()

    window.fit_page_action.trigger()
    page_factor = window.document_editor_view.editor.zoom_factor
    assert page_factor == window.document_editor_view.editor_canvas.transform().m11()
    assert page_factor < width_factor
    window.document_mode_controller.close_document(discard=True)
    window.close()


def test_document_page_navigation_debounces_live_thumbnails(qapp, tmp_path) -> None:
    _app, window = create_application(["flowpdf-test"], data_root=tmp_path / "app-data")
    document = FlowDocument.new()
    for index in range(24):
        document.append_block(Paragraph(runs=[TextRun(f"第 {index + 1} 段缩略图内容。" * 8)]))
    window.show_document_editor(document)
    window.show()

    page_list = window.document_page_list
    assert _wait_until(
        qapp,
        lambda: (
            page_list.count() == window.document_editor_view.editor.page_count
            and page_list.count() > 1
            and not page_list.item(0).icon().isNull()
        ),
    )
    previous_key = page_list.item(0).icon().cacheKey()
    editor = window.document_editor_view.editor
    editor.moveCursor(QTextCursor.MoveOperation.Start)
    editor.insertPlainText("缩略图应该在防抖后更新。" * 20)

    assert _wait_until(
        qapp,
        lambda: (
            page_list.count() == editor.page_count
            and not page_list.item(0).icon().isNull()
            and page_list.item(0).icon().cacheKey() != previous_key
        ),
    )
    page_list.setCurrentRow(1)
    assert _wait_until(qapp, lambda: window.document_editor_view.current_page == 1)
    window.document_mode_controller.close_document(discard=True)
    window.close()
