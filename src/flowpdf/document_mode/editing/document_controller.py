from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QFileDialog, QMessageBox

from flowpdf.document_mode.export import (
    DocumentPdfExporter,
    PdfExportResult,
    ProjectBundle,
    ProjectReader,
    ProjectState,
    ProjectWriter,
)
from flowpdf.document_mode.importing import ImportReport, ImportResult, PdfImportService
from flowpdf.document_mode.models import FlowDocument
from flowpdf.services.task_service import TaskContext, TaskService

if TYPE_CHECKING:
    from flowpdf.ui.main_window import MainWindow


class DocumentModeController(QObject):
    """Own the reflowable session; layout-mode PDF state never enters this module."""

    def __init__(
        self,
        window: MainWindow,
        *,
        artifact_registry=None,
        task_service: TaskService | None = None,
    ) -> None:
        super().__init__(window)
        self.window = window
        self.tasks = task_service or TaskService(max_threads=1, parent=self)
        self._importer = PdfImportService()
        self._reader = ProjectReader()
        self._writer = ProjectWriter()
        self._exporter = DocumentPdfExporter(artifact_registry=artifact_registry)
        self.document: FlowDocument | None = None
        self.import_report: ImportReport | None = None
        self.project_path: Path | None = None
        self.is_dirty = False
        self.is_shutdown = False
        self._applying = False
        self._close_when_idle = False

        editor = self.window.document_editor_view.editor
        editor.model_changed.connect(self._mark_dirty)
        editor.undoAvailable.connect(self._history_changed)
        editor.redoAvailable.connect(self._history_changed)
        self.window.document_editor_view.page_status_changed.connect(
            self.window.update_document_mode_status
        )
        self.tasks.busy_changed.connect(self._on_busy_changed)
        self.tasks.progress.connect(
            lambda _task_id, value, message: self.window.set_progress(value, message)
        )

    def import_pdf(
        self,
        path: str | Path,
        *,
        password: str | None = None,
        on_complete: Callable[[ImportResult], None] | None = None,
    ) -> None:
        source = Path(path)

        def completed(result: ImportResult) -> None:
            self.apply_import_result(result, source)
            if on_complete is not None:
                on_complete(result)

        self.analyze_pdf(
            source,
            password=password,
            on_complete=completed,
            on_error=lambda error: self.window.show_error("无法导入文档模式", str(error)),
        )

    def analyze_pdf(
        self,
        path: str | Path,
        *,
        password: str | None = None,
        on_complete: Callable[[ImportResult], None],
        on_error: Callable[[Exception], None],
    ) -> None:
        if self.tasks.active_count:
            return
        source = Path(path)

        def perform(context: TaskContext) -> ImportResult:
            return self._importer.import_file(
                source,
                password=password,
                cancel_check=lambda: context.is_cancelled,
                progress=lambda value, message: _safe_progress(context, value, message),
            )

        self.tasks.submit(
            perform,
            on_success=on_complete,
            on_error=on_error,
            priority=25,
        )

    def apply_import_result(self, result: ImportResult, source: str | Path) -> None:
        path = Path(source)
        self._apply_document(result.document, report=result.report)
        self.project_path = None
        self.window.setWindowTitle(f"{path.name}（文档编辑）— FlowPDF")
        self.window.set_saved_status("已重构为可流动文档；请保存 FlowPDF 工程")

    def open_project(self, path: str | Path) -> None:
        if self.tasks.active_count:
            return
        source = Path(path)

        def completed(bundle: ProjectBundle) -> None:
            self._apply_document(bundle.document)
            self.project_path = source
            self.window.document_editor_view.restore_cursor(
                bundle.state.cursor_position,
                bundle.state.selection_anchor,
                bundle.state.scroll_y,
            )
            self.is_dirty = False
            self.window.setWindowTitle(f"{source.name} — FlowPDF")
            self.window.set_saved_status("FlowPDF 工程已打开")

        self.tasks.submit(
            lambda _context: self._reader.load(source),
            on_success=completed,
            on_error=lambda error: self.window.show_error("无法打开工程", str(error)),
            priority=25,
        )

    def save_project(self, *, save_as: bool = False, on_complete=None) -> None:
        if self.document is None or self.tasks.active_count:
            return
        target = None if save_as else self.project_path
        if target is None:
            suggested = self._suggested_project_path()
            selected, _filter = QFileDialog.getSaveFileName(
                self.window,
                "保存 FlowPDF 工程",
                str(suggested),
                "FlowPDF 工程 (*.flowpdfproj)",
            )
            if not selected:
                return
            target = Path(selected)
        self.save_project_to(target, on_complete=on_complete)

    def save_project_to(self, path: str | Path, *, on_complete=None) -> None:
        if self.document is None or self.tasks.active_count:
            return
        target = Path(path)
        document = self.window.document_editor_view.editor.flow_document()
        state = self._project_state()

        def completed(output: Path) -> None:
            self.document = document
            self.project_path = output
            self.is_dirty = False
            self.window.setWindowTitle(f"{output.name} — FlowPDF")
            self.window.set_saved_status(f"工程已安全保存：{output.name}")
            if on_complete is not None:
                on_complete()

        self.tasks.submit(
            lambda _context: self._writer.save(document, target, state=state),
            on_success=completed,
            on_error=lambda error: self.window.show_error("工程保存失败", str(error)),
            priority=30,
        )

    def export_pdf(self) -> None:
        if self.document is None or self.tasks.active_count:
            return
        initial = self._suggested_pdf_path()
        selected, _filter = QFileDialog.getSaveFileName(
            self.window,
            "导出可搜索 PDF",
            str(initial),
            "PDF 文件 (*.pdf)",
        )
        if selected:
            self.export_pdf_to(selected)

    def export_pdf_to(
        self,
        path: str | Path,
        *,
        on_complete: Callable[[PdfExportResult], None] | None = None,
    ) -> None:
        if self.document is None or self.tasks.active_count:
            return
        target = Path(path)
        document = self.window.document_editor_view.editor.flow_document()

        def perform(context: TaskContext) -> PdfExportResult:
            return self._exporter.export(
                document,
                target,
                cancel_check=lambda: context.is_cancelled,
                progress=lambda value, message: _safe_progress(context, value, message),
            )

        def completed(result: PdfExportResult) -> None:
            self.document = document
            self.window.set_saved_status(
                f"已导出可搜索 PDF：{result.output_path.name}（{result.page_count} 页）"
            )
            if on_complete is not None:
                on_complete(result)

        self.tasks.submit(
            perform,
            on_success=completed,
            on_error=lambda error: self.window.show_error("PDF 导出失败", str(error)),
            priority=30,
        )

    def undo(self) -> None:
        if self.document is not None:
            self.window.document_editor_view.editor.undo()

    def redo(self) -> None:
        if self.document is not None:
            self.window.document_editor_view.editor.redo()

    def close_document(self, *, discard: bool = False) -> bool:
        if self.document is None:
            return True
        if not discard and self.is_dirty:
            answer = QMessageBox.warning(
                self.window,
                "文档工程尚未保存",
                "要先保存 FlowPDF 工程吗？PDF 导出不能代替可继续编辑的工程。",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )
            if answer is QMessageBox.StandardButton.Cancel:
                return False
            if answer is QMessageBox.StandardButton.Save:
                self.save_project(on_complete=self.window.force_close_after_save)
                return False
        self._clear_document()
        return True

    def request_close(self) -> bool:
        if self.is_shutdown:
            return True
        if self.tasks.active_count:
            self.tasks.cancel_all()
            self._close_when_idle = True
            self.window.set_saved_status("正在取消文档模式后台任务，完成后将退出…")
            return False
        if not self.close_document():
            return False
        return self.shutdown()

    def shutdown(self) -> bool:
        if self.is_shutdown:
            return True
        finished = self.tasks.shutdown()
        self.is_shutdown = finished
        return finished

    def _apply_document(
        self,
        document: FlowDocument,
        *,
        report: ImportReport | None = None,
    ) -> None:
        self._applying = True
        try:
            self.document = document
            self.import_report = report
            self.window.show_document_editor(document, report)
            self.is_dirty = False
        finally:
            self._applying = False
        self._history_changed()

    def _clear_document(self) -> None:
        self._applying = True
        try:
            self.window.clear_document_editor()
            self.document = None
            self.import_report = None
            self.project_path = None
            self.is_dirty = False
        finally:
            self._applying = False

    def _mark_dirty(self) -> None:
        if self._applying or self.document is None:
            return
        self.is_dirty = True
        self.window.set_saved_status("文档结构有未保存修改")
        self.window.update_document_word_count(
            len(self.window.document_editor_view.editor.toPlainText().replace("\n", ""))
        )

    def _history_changed(self, _available: bool | None = None) -> None:
        if self.window.active_mode != "document":
            return
        editor = self.window.document_editor_view.editor
        self.window.set_history_state(
            can_undo=editor.document().isUndoAvailable(),
            can_redo=editor.document().isRedoAvailable(),
        )

    def _project_state(self) -> ProjectState:
        editor = self.window.document_editor_view.editor
        cursor = editor.textCursor()
        return ProjectState(
            cursor_position=cursor.position(),
            selection_anchor=cursor.anchor(),
            scroll_y=editor.verticalScrollBar().value(),
            current_page=self.window.document_editor_view.current_page,
        )

    def _suggested_project_path(self) -> Path:
        source = Path(self.document.metadata.source_pdf_path) if self.document else None
        if source and source.name:
            return source.with_suffix(".flowpdfproj")
        return Path.cwd() / "未命名文档.flowpdfproj"

    def _suggested_pdf_path(self) -> Path:
        if self.project_path is not None:
            return self.project_path.with_suffix(".pdf")
        source = Path(self.document.metadata.source_pdf_path) if self.document else None
        if source and source.name:
            return source.with_name(f"{source.stem}_文档模式.pdf")
        return Path.cwd() / "未命名文档_文档模式.pdf"

    def _on_busy_changed(self, busy: bool) -> None:
        self.window.set_busy(busy, "正在处理文档模式任务…")
        if not busy:
            self._history_changed()
            if self._close_when_idle:
                self._close_when_idle = False
                QTimer.singleShot(0, self.window.close)


def _safe_progress(context: TaskContext, value: int, message: str) -> None:
    if not context.is_cancelled:
        context.report_progress(value, message)
