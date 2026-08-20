from __future__ import annotations

import io
import uuid
import warnings
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image, UnidentifiedImageError
from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox

from flowpdf.document_mode.export import (
    DocumentPdfExporter,
    PdfExportResult,
    ProjectBundle,
    ProjectReader,
    ProjectState,
    ProjectWriter,
)
from flowpdf.document_mode.importing import ImportReport, ImportResult, PdfImportService
from flowpdf.document_mode.models import FlowDocument, PageSetup
from flowpdf.document_mode.recovery_service import (
    DocumentRecoveryRecord,
    DocumentRecoveryService,
)
from flowpdf.document_mode.ui import PageSetupDialog
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
        recovery_service: DocumentRecoveryService,
    ) -> None:
        super().__init__(window)
        self.window = window
        self.tasks = task_service or TaskService(max_threads=1, parent=self)
        self._importer = PdfImportService()
        self._reader = ProjectReader()
        self._writer = ProjectWriter(artifact_registry=artifact_registry)
        self._exporter = DocumentPdfExporter(artifact_registry=artifact_registry)
        self.recovery_service = recovery_service
        self.recovery_tasks = TaskService(max_threads=1, parent=self)
        self.document: FlowDocument | None = None
        self.import_report: ImportReport | None = None
        self.project_path: Path | None = None
        self.is_dirty = False
        self.is_shutdown = False
        self._applying = False
        self._close_when_idle = False
        self._edit_revision = 0
        self._recovery_epoch = 0
        self._checkpoint_after_recovery = False
        self._session_id = uuid.uuid4().hex
        self._recovery_path: Path | None = None
        self._autosave = QTimer(self)
        self._autosave.setInterval(15_000)
        self._autosave.timeout.connect(self.flush_recovery)

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
        self.recovery_tasks.busy_changed.connect(self._on_recovery_busy_changed)
        toolbar = self.window.document_toolbar
        toolbar.insert_image_requested.connect(self.insert_image_dialog)
        toolbar.export_pdf_requested.connect(self.export_pdf)
        toolbar.find_replace_requested.connect(self.find_replace_dialog)
        toolbar.page_setup_requested.connect(self.page_setup_dialog)

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
                bundle.state.zoom_factor,
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

    def offer_recovery(self, *, on_none: Callable[[], None] | None = None) -> None:
        if self.document is not None or self.tasks.active_count or self.recovery_tasks.active_count:
            return

        def completed(records: list[tuple[Path, DocumentRecoveryRecord]]) -> None:
            if not records:
                if on_none is not None:
                    on_none()
                return
            path, record = records[0]
            while True:
                box = QMessageBox(self.window)
                box.setIcon(QMessageBox.Icon.Warning)
                box.setWindowTitle("发现未完成的文档编辑会话")
                shown_name = (
                    Path(record.project_path or record.source_pdf_path).name or "未命名文档"
                )
                box.setText(f"检测到“{shown_name}”的文档模式恢复记录。")
                box.setInformativeText("恢复后仍需保存 FlowPDF 工程，不会覆盖来源 PDF。")
                restore_button = box.addButton("恢复", QMessageBox.ButtonRole.AcceptRole)
                discard_button = box.addButton("放弃", QMessageBox.ButtonRole.DestructiveRole)
                details_button = box.addButton("查看详情", QMessageBox.ButtonRole.ActionRole)
                box.addButton(QMessageBox.StandardButton.Cancel)
                box.exec()
                clicked = box.clickedButton()
                if clicked is restore_button:
                    self._restore_record(path, record)
                    return
                if clicked is discard_button:
                    self.recovery_service.discard(path)
                    if on_none is not None:
                        on_none()
                    return
                if clicked is details_button:
                    QMessageBox.information(
                        self.window,
                        "文档恢复详情",
                        f"来源：{record.source_pdf_path or '无'}\n"
                        f"工程：{record.project_path or '尚未保存'}\n"
                        f"最后更新：{record.updated_at}\n"
                        f"字符数：{len(record.document.plain_text)}",
                    )
                    continue
                return

        self.recovery_tasks.submit(
            lambda _context: self.recovery_service.list_session_files(),
            on_success=completed,
            on_error=lambda error: self.window.set_saved_status(f"读取文档恢复记录失败：{error}"),
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
        saved_revision = self._edit_revision
        self._invalidate_recovery_tasks()

        def completed(output: Path) -> None:
            self.project_path = output
            self.window.setWindowTitle(f"{output.name} — FlowPDF")
            if self._edit_revision == saved_revision:
                self.document = document
                self.is_dirty = False
                self.window.set_saved_status(f"工程已安全保存：{output.name}")
                self._discard_recovery()
                if on_complete is not None:
                    on_complete()
            else:
                self.is_dirty = True
                self.window.set_saved_status("工程快照已保存，但保存期间有新修改，请再次保存")
                if self.recovery_tasks.active_count:
                    self._checkpoint_after_recovery = True
                else:
                    self.flush_recovery()

        def failed(error: Exception) -> None:
            self.window.show_error("工程保存失败", str(error))
            if self.is_dirty:
                if self.recovery_tasks.active_count:
                    self._checkpoint_after_recovery = True
                else:
                    self.flush_recovery()

        self.tasks.submit(
            lambda _context: self._writer.save(document, target, state=state),
            on_success=completed,
            on_error=failed,
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
        editor = self.window.document_editor_view.editor
        expected_pages = editor.refresh_pagination()
        document = editor.flow_document()
        exported_revision = self._edit_revision

        def perform(context: TaskContext) -> PdfExportResult:
            return self._exporter.export(
                document,
                target,
                expected_page_count=expected_pages,
                cancel_check=lambda: context.is_cancelled,
                progress=lambda value, message: _safe_progress(context, value, message),
            )

        def completed(result: PdfExportResult) -> None:
            if self._edit_revision == exported_revision:
                self.document = document
                status = f"已导出可搜索 PDF：{result.output_path.name}（{result.page_count} 页）"
                if not result.pagination_matches:
                    status += f"；编辑预览为 {result.preview_page_count} 页，请检查分页"
            else:
                status = "PDF 快照已导出，但导出期间有新修改；当前文档仍未导出"
            self.window.set_saved_status(status)
            if on_complete is not None:
                on_complete(result)

        self.tasks.submit(
            perform,
            on_success=completed,
            on_error=lambda error: self.window.show_error("PDF 导出失败", str(error)),
            priority=30,
        )

    def insert_image_dialog(self) -> None:
        if self.document is None or self.tasks.active_count:
            return
        selected, _filter = QFileDialog.getOpenFileName(
            self.window,
            "插入文档图片",
            "",
            "图片 (*.png *.jpg *.jpeg *.webp)",
        )
        if not selected:
            return
        source = Path(selected)

        def read_image(context: TaskContext) -> tuple[bytes, str, tuple[int, int]]:
            if source.stat().st_size > 128 * 1024 * 1024:
                raise ValueError("图片文件超过 128 MB 安全上限")
            data = source.read_bytes()
            context.report_progress(35, "正在后台验证图片")
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("error", Image.DecompressionBombWarning)
                    with Image.open(io.BytesIO(data)) as decoded:
                        size = decoded.size
                        decoded.verify()
            except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
                raise ValueError("图片解码资源异常") from exc
            except (OSError, UnidentifiedImageError) as exc:
                raise ValueError("图片内容损坏或格式不受支持") from exc
            if size[0] * size[1] > 80_000_000:
                raise ValueError("图片像素数量超过安全上限")
            media_type = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".webp": "image/webp",
            }.get(source.suffix.casefold(), "application/octet-stream")
            return data, media_type, size

        def insert(result: tuple[bytes, str, tuple[int, int]]) -> None:
            data, media_type, size = result
            self.window.document_editor_view.editor.insert_image(
                data,
                media_type=media_type,
                pixel_size=size,
                alt_text=source.stem,
            )
            self.window.set_saved_status(f"已插入图片：{source.name}")

        self.tasks.submit(
            read_image,
            on_success=insert,
            on_error=lambda error: self.window.show_error("无法插入图片", str(error)),
        )

    def find_replace_dialog(self) -> None:
        if self.document is None:
            return
        query, accepted = QInputDialog.getText(self.window, "查找替换", "查找内容：")
        if not accepted or not query:
            return
        replacement, accepted = QInputDialog.getText(self.window, "查找替换", "替换为：")
        if not accepted:
            return
        count = self.window.document_editor_view.editor.replace_all(query, replacement)
        self.window.set_saved_status(f"已替换 {count} 处")

    def page_setup_dialog(self) -> None:
        if self.document is None:
            return
        current = self.window.document_editor_view.editor.flow_document()
        dialog = PageSetupDialog(current.page_setup, self.window)
        if dialog.exec():
            try:
                self.set_page_setup(dialog.page_setup())
            except ValueError as error:
                self.window.show_error("页面设置无效", str(error))

    def set_page_setup(self, setup: PageSetup) -> None:
        if self.document is None:
            return
        editor = self.window.document_editor_view.editor
        document = editor.flow_document()
        cursor = editor.textCursor()
        position, anchor = cursor.position(), cursor.anchor()
        scroll = self.window.document_editor_view.scroll_y
        zoom = editor.zoom_factor
        document.page_setup = setup
        self._applying = True
        try:
            editor.set_flow_document(document)
            self.window.document_editor_view.restore_cursor(position, anchor, scroll, zoom)
            self.document = document
        finally:
            self._applying = False
        self.is_dirty = True
        self._edit_revision += 1
        self.window.update_document_mode_status(
            self.window.document_editor_view.current_page,
            editor.page_count,
        )
        self.window.set_saved_status("页面设置已修改")

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
            discard = True
        if discard:
            self._invalidate_recovery_tasks()
            self._discard_recovery()
        self._clear_document()
        return True

    def request_close(self) -> bool:
        if self.is_shutdown:
            return True
        if self.tasks.active_count or self.recovery_tasks.active_count:
            self.tasks.cancel_all()
            self.recovery_tasks.cancel_all()
            self._close_when_idle = True
            self.window.set_saved_status("正在取消文档模式后台任务，完成后将退出…")
            return False
        if not self.close_document():
            return False
        return self.shutdown()

    def shutdown(self) -> bool:
        if self.is_shutdown:
            return True
        self._autosave.stop()
        tasks_finished = self.tasks.shutdown()
        recovery_finished = self.recovery_tasks.shutdown()
        finished = tasks_finished and recovery_finished
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
        self._edit_revision = 0
        self._checkpoint_after_recovery = False
        self._session_id = uuid.uuid4().hex
        self._recovery_path = None
        self._autosave.start()

    def _clear_document(self) -> None:
        self._autosave.stop()
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
        self._edit_revision += 1
        self.window.set_saved_status("文档结构有未保存修改")
        self.window.update_document_word_count(
            len(self.window.document_editor_view.editor.toPlainText().replace("\n", ""))
        )

    def flush_recovery(self) -> None:
        if (
            self.document is None
            or not self.is_dirty
            or self.recovery_tasks.active_count
            or self.is_shutdown
        ):
            return
        document = self.window.document_editor_view.editor.flow_document()
        state = self._project_state()
        session_id = self._session_id
        recovery_epoch = self._recovery_epoch
        project_path = str(self.project_path or "")

        def completed(path: Path) -> None:
            if (
                recovery_epoch != self._recovery_epoch
                or session_id != self._session_id
                or self.document is None
            ):
                self.recovery_service.discard(path)
                return
            self._recovery_path = path
            self.window.set_saved_status("文档模式恢复检查点已更新")

        def write_checkpoint(context: TaskContext) -> Path:
            path = self.recovery_service.write(
                session_id=session_id,
                document=document,
                state=state,
                project_path=project_path,
                unexported=True,
            )
            if context.is_cancelled:
                self.recovery_service.discard(path)
            return path

        self.recovery_tasks.submit(
            write_checkpoint,
            on_success=completed,
            on_error=lambda error: self.window.set_saved_status(f"自动恢复记录失败：{error}"),
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
            scroll_y=self.window.document_editor_view.scroll_y,
            current_page=self.window.document_editor_view.current_page,
            zoom_factor=editor.zoom_factor,
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

    def _on_recovery_busy_changed(self, busy: bool) -> None:
        if not busy and self._checkpoint_after_recovery:
            self._checkpoint_after_recovery = False
            if self.is_dirty and not self.tasks.active_count and not self.is_shutdown:
                self.flush_recovery()
        if not busy and self._close_when_idle and not self.tasks.active_count:
            self._close_when_idle = False
            QTimer.singleShot(0, self.window.close)

    def _restore_record(self, path: Path, record: DocumentRecoveryRecord) -> None:
        self._apply_document(record.document)
        self._session_id = record.session_id
        self._recovery_path = path
        self.project_path = Path(record.project_path) if record.project_path else None
        self.window.document_editor_view.restore_cursor(
            record.state.cursor_position,
            record.state.selection_anchor,
            record.state.scroll_y,
            record.state.zoom_factor,
        )
        self.is_dirty = True
        self._edit_revision = 1
        self.window.set_saved_status("已恢复未保存文档；来源 PDF 未被覆盖")

    def _discard_recovery(self) -> None:
        self.recovery_service.discard_session(self._session_id)
        if self._recovery_path is not None:
            self.recovery_service.discard(self._recovery_path)
            self._recovery_path = None

    @property
    def edit_revision(self) -> int:
        return self._edit_revision

    def _invalidate_recovery_tasks(self) -> None:
        self._recovery_epoch += 1
        self.recovery_tasks.cancel_all()


def _safe_progress(context: TaskContext, value: int, message: str) -> None:
    if not context.is_cancelled:
        context.report_progress(value, message)
