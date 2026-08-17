from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QFileDialog, QInputDialog, QLineEdit, QMessageBox

from flowpdf.document_mode.importing import (
    ImportInvalidPassword,
    ImportPasswordRequired,
    ImportReport,
    ImportResult,
)
from flowpdf.document_mode.ui import ModeChoiceDialog
from flowpdf.services.temp_file_service import TempFileService


class ModeCoordinator(QObject):
    """Route global UI intent while keeping both document models independent."""

    def __init__(
        self,
        window,
        layout_controller,
        document_controller,
        *,
        temp_files: TempFileService,
    ) -> None:
        super().__init__(window)
        self.window = window
        self.layout_controller = layout_controller
        self.document_controller = document_controller
        self.temp_files = temp_files
        self.mode_selector: Callable[[ImportReport], str | None] = lambda report: (
            ModeChoiceDialog.choose(self.window, report)
        )
        self._mode_snapshots: set[Path] = set()
        self._connect_actions()

    def open_dialog(self) -> None:
        selected, _filter = QFileDialog.getOpenFileName(
            self.window,
            "打开 PDF 或 FlowPDF 工程",
            "",
            "支持的文档 (*.pdf *.flowpdfproj);;PDF 文件 (*.pdf);;FlowPDF 工程 (*.flowpdfproj)",
        )
        if selected:
            self.open_path(selected)

    def open_project_dialog(self) -> None:
        selected, _filter = QFileDialog.getOpenFileName(
            self.window,
            "打开 FlowPDF 工程",
            "",
            "FlowPDF 工程 (*.flowpdfproj)",
        )
        if selected:
            self.open_path(selected)

    def open_path(
        self,
        path: str | Path,
        *,
        password: str | None = None,
        confirmed: bool = False,
    ) -> None:
        source = Path(path)
        suffix = source.suffix.casefold()
        if suffix not in {".pdf", ".flowpdfproj"}:
            self.window.show_error("无法打开", "请选择 PDF 或 FlowPDF 工程文件")
            return
        if not confirmed and not self._confirm_replace(
            lambda: self.open_path(source, password=password, confirmed=True)
        ):
            return
        if self._is_busy():
            return
        if suffix == ".flowpdfproj":
            self.layout_controller.close_document(discard=True)
            self.document_controller.close_document(discard=True)
            self.document_controller.open_project(source)
            return

        self.document_controller.analyze_pdf(
            source,
            password=password,
            on_complete=lambda result: self._choose_import_mode(source, password, result),
            on_error=lambda error: self._handle_import_error(source, error),
        )

    def save(self, *, save_as: bool = False) -> None:
        if self.window.active_mode == "document":
            self.document_controller.save_project(save_as=save_as)
        else:
            self.layout_controller.save(save_as=save_as)

    def close_document(self) -> None:
        if self.window.active_mode == "document":
            self.document_controller.close_document()
        else:
            self.layout_controller.close_document()

    def undo(self) -> None:
        if self.window.active_mode == "document":
            self.document_controller.undo()
        else:
            self.layout_controller.undo()

    def redo(self) -> None:
        if self.window.active_mode == "document":
            self.document_controller.redo()
        else:
            self.layout_controller.redo()

    def switch_to_document_mode(self) -> None:
        if self.window.active_mode == "document":
            return
        session = self.layout_controller.session
        if session is None:
            self.window.document_mode_action.setChecked(False)
            return
        source = session.saved_path or session.source_path
        if source is None:
            self.window.show_error("无法切换模式", "请先保存当前 PDF，再进入文档编辑模式。")
            self.window.layout_mode_action.setChecked(True)
            return
        if session.is_dirty:
            answer = QMessageBox.warning(
                self.window,
                "先保存版面修改",
                "切换到文档编辑模式会重新分析当前 PDF。请先把版面修改保存为副本。",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )
            if answer is QMessageBox.StandardButton.Save:
                self.layout_controller.save(
                    on_complete=lambda: self.open_path(
                        self.layout_controller.session.saved_path,
                        confirmed=True,
                    )
                )
            else:
                self.window.layout_mode_action.setChecked(True)
            return
        answer = QMessageBox.warning(
            self.window,
            "重新构建文档",
            "切换到文档编辑模式需要重新分析当前 PDF，复杂版式可能发生变化。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        )
        if answer is QMessageBox.StandardButton.Yes:
            self.open_path(source, confirmed=True)
        else:
            self.window.layout_mode_action.setChecked(True)

    def switch_to_layout_mode(self) -> None:
        if self.window.active_mode == "layout":
            return
        if self.document_controller.document is None:
            self.window.document_mode_action.setChecked(False)
            return
        answer = QMessageBox.warning(
            self.window,
            "生成固定版式快照",
            "当前文档将先导出为固定版式 PDF。之后的版面修改不会自动同步回文档结构。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        )
        if answer is not QMessageBox.StandardButton.Yes:
            self.window.document_mode_action.setChecked(True)
            return
        snapshot = self.temp_files.create(suffix=".pdf")
        self._mode_snapshots.add(snapshot)

        def exported(_result) -> None:
            self.document_controller.close_document(discard=True)
            self.layout_controller.open_path(snapshot, confirmed=True)

        self.document_controller.export_pdf_to(snapshot, on_complete=exported)

    def search(self, query: str, *, backward: bool = False) -> None:
        if self.window.active_mode != "document":
            return
        editor = self.window.document_editor_view.editor
        found = editor.find_text(query, backward=backward)
        total = editor.toPlainText().casefold().count(query.casefold()) if query else 0
        self.window.search_panel.set_results(1 if found else 0, total)

    def request_close(self) -> bool:
        if self.window.active_mode == "document":
            if not self.document_controller.request_close():
                return False
            finished = self.layout_controller.shutdown()
        else:
            if not self.layout_controller.request_close():
                return False
            finished = self.document_controller.shutdown()
        if finished:
            self._discard_snapshots()
        return finished

    def _choose_import_mode(
        self,
        source: Path,
        password: str | None,
        result: ImportResult,
    ) -> None:
        choice = self.mode_selector(result.report)
        if choice == "document":
            self.layout_controller.close_document(discard=True)
            self.document_controller.apply_import_result(result, source)
            self.layout_controller.recent_files.add(source)
            self.window.set_recent_files(self.layout_controller.recent_files.paths())
        elif choice == "layout":
            self.document_controller.close_document(discard=True)
            self.layout_controller.open_path(source, password=password, confirmed=True)
        else:
            self.window.set_saved_status("已取消打开，当前文档未改变")
            if self.window.active_mode == "layout":
                self.window.layout_mode_action.setChecked(True)
            elif self.window.active_mode == "document":
                self.window.document_mode_action.setChecked(True)

    def _handle_import_error(self, source: Path, error: Exception) -> None:
        if isinstance(error, (ImportPasswordRequired, ImportInvalidPassword)):
            prompt = (
                "密码不正确，请重试："
                if isinstance(error, ImportInvalidPassword)
                else "此 PDF 需要密码："
            )
            password, accepted = QInputDialog.getText(
                self.window,
                "输入 PDF 密码",
                prompt,
                QLineEdit.EchoMode.Password,
            )
            if accepted:
                self.open_path(source, password=password, confirmed=True)
            return
        self.window.show_error("无法分析 PDF", str(error))

    def _confirm_replace(self, after_save) -> bool:
        if self.window.active_mode == "document" and self.document_controller.is_dirty:
            answer = QMessageBox.warning(
                self.window,
                "文档工程尚未保存",
                "要先保存 FlowPDF 工程吗？",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )
            if answer is QMessageBox.StandardButton.Discard:
                return True
            if answer is QMessageBox.StandardButton.Save:
                self.document_controller.save_project(on_complete=after_save)
            return False
        session = self.layout_controller.session
        if session is not None and session.is_dirty:
            answer = QMessageBox.warning(
                self.window,
                "版面修改尚未保存",
                "要先把当前修改保存为 PDF 副本吗？",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )
            if answer is QMessageBox.StandardButton.Discard:
                return True
            if answer is QMessageBox.StandardButton.Save:
                self.layout_controller.save(on_complete=after_save)
            return False
        return True

    def _is_busy(self) -> bool:
        return bool(
            self.layout_controller.tasks.active_count or self.document_controller.tasks.active_count
        )

    def _connect_actions(self) -> None:
        window = self.window
        window.open_action.triggered.connect(lambda _checked=False: self.open_dialog())
        window.open_project_action.triggered.connect(
            lambda _checked=False: self.open_project_dialog()
        )
        window.new_action.triggered.connect(
            lambda _checked=False: self.layout_controller.create_new()
        )
        window.save_action.triggered.connect(lambda _checked=False: self.save())
        window.save_as_action.triggered.connect(lambda _checked=False: self.save(save_as=True))
        window.close_action.triggered.connect(lambda _checked=False: self.close_document())
        window.undo_action.triggered.connect(lambda _checked=False: self.undo())
        window.redo_action.triggered.connect(lambda _checked=False: self.redo())
        window.pdf_dropped.connect(self.open_path)
        window.recent_file_requested.connect(self.open_path)
        window.document_mode_action.triggered.connect(
            lambda _checked=False: self.switch_to_document_mode()
        )
        window.layout_mode_action.triggered.connect(
            lambda _checked=False: self.switch_to_layout_mode()
        )
        window.search_panel.search_requested.connect(self.search)
        window.search_panel.previous_requested.connect(
            lambda: self.search(window.search_panel.query_edit.text(), backward=True)
        )
        window.search_panel.next_requested.connect(
            lambda: self.search(window.search_panel.query_edit.text())
        )

    def _discard_snapshots(self) -> None:
        for path in self._mode_snapshots:
            with suppress(OSError):
                self.temp_files.discard(path)
        self._mode_snapshots.clear()
