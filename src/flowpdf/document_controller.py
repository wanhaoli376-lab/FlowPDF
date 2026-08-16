from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QFileDialog, QInputDialog, QLineEdit, QMessageBox

from flowpdf.backends.base import (
    InvalidPasswordError,
    PageInfo,
    PasswordRequiredError,
    SearchHit,
)
from flowpdf.backends.pymupdf_backend import PyMuPdfBackend
from flowpdf.editing.document_session import DocumentSession
from flowpdf.editing.pdf_commands import PdfCommandType
from flowpdf.rendering.render_scheduler import RenderSource
from flowpdf.services.recent_files import RecentFiles
from flowpdf.services.recovery_service import RecoveryService
from flowpdf.services.task_service import TaskContext, TaskHandle, TaskService

if TYPE_CHECKING:
    from flowpdf.ui.main_window import MainWindow


@dataclass(frozen=True, slots=True)
class DocumentSnapshot:
    source: RenderSource
    page_infos: list[PageInfo]
    revision: int


@dataclass(frozen=True, slots=True)
class LoadedSession:
    session: DocumentSession
    snapshot: DocumentSnapshot


class DocumentController(QObject):
    """Coordinate UI intent, document sessions, and background application work."""

    def __init__(
        self,
        window: MainWindow,
        *,
        recovery_service: RecoveryService,
        recent_files: RecentFiles,
        task_service: TaskService | None = None,
    ) -> None:
        super().__init__(window)
        self.window = window
        self.recovery_service = recovery_service
        self.recent_files = recent_files
        self.tasks = task_service or TaskService(max_threads=2, parent=self)
        self.session: DocumentSession | None = None
        self._search_hits: list[SearchHit] = []
        self._search_index: int | None = None
        self._search_handle: TaskHandle | None = None
        self._shutdown = False
        self._close_when_idle = False
        self._autosave = QTimer(self)
        self._autosave.setInterval(15_000)
        self._autosave.timeout.connect(self._flush_recovery)

        self.tasks.busy_changed.connect(self._on_busy_changed)
        self.tasks.progress.connect(lambda _task_id, value, text: window.set_progress(value, text))
        self._connect_actions()
        self.window.attach_controller(self)
        self.window.set_recent_files(self.recent_files.paths())

    @property
    def is_shutdown(self) -> bool:
        return self._shutdown

    def open_dialog(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            self.window,
            "打开 PDF",
            "",
            "PDF 文件 (*.pdf)",
        )
        if path:
            self.open_path(path)

    def open_path(
        self,
        path: str | Path,
        *,
        password: str | None = None,
        confirmed: bool = False,
    ) -> None:
        source = Path(path)
        if not confirmed and not self._confirm_replace(
            lambda: self.open_path(source, password=password, confirmed=True)
        ):
            return
        if self.tasks.active_count:
            return

        def load(context: TaskContext) -> LoadedSession:
            context.report_progress(5, "正在打开 PDF")
            session = DocumentSession(
                PyMuPdfBackend(),
                recovery_service=self.recovery_service,
            )
            session.open(source, password=password)
            context.report_progress(35, "正在读取页面信息")
            snapshot = _snapshot(session, context)
            return LoadedSession(session, snapshot)

        def failed(error: Exception) -> None:
            if isinstance(error, (PasswordRequiredError, InvalidPasswordError)):
                self._request_password(source, invalid=isinstance(error, InvalidPasswordError))
                return
            self.window.show_error("无法打开 PDF", str(error))

        self.window.set_saved_status("正在打开，只读保护原文件…")
        self.tasks.submit(load, on_success=self._apply_loaded, on_error=failed, priority=20)

    def create_new(self, *, confirmed: bool = False) -> None:
        if not confirmed and not self._confirm_replace(lambda: self.create_new(confirmed=True)):
            return
        if self.tasks.active_count:
            return

        def create(context: TaskContext) -> LoadedSession:
            session = DocumentSession(
                PyMuPdfBackend(),
                recovery_service=self.recovery_service,
            )
            session.create_new()
            return LoadedSession(session, _snapshot(session, context))

        self.tasks.submit(create, on_success=self._apply_loaded, on_error=self._show_task_error)

    def search(self, query: str) -> None:
        needle = query.strip()
        if not needle or self.session is None:
            self._show_search_hits([])
            return
        if self._search_handle is not None:
            self._search_handle.cancel()
        session = self.session

        def perform(context: TaskContext) -> list[SearchHit]:
            context.report_progress(10, "正在搜索文字")
            hits = session.backend.search_text(needle)
            context.raise_if_cancelled()
            return hits

        self._search_handle = self.tasks.submit(
            perform,
            on_success=self._show_search_hits,
            on_error=self._show_task_error,
            priority=10,
        )

    def previous_search_result(self) -> None:
        if not self._search_hits:
            return
        current = self._search_index or 0
        self._search_index = (current - 1) % len(self._search_hits)
        self._display_search_position()

    def next_search_result(self) -> None:
        if not self._search_hits:
            return
        current = -1 if self._search_index is None else self._search_index
        self._search_index = (current + 1) % len(self._search_hits)
        self._display_search_position()

    def save(self, *, save_as: bool = False, on_complete=None) -> None:
        if self.session is None or self.tasks.active_count:
            return
        target = None if save_as else self.session.saved_path
        if target is None:
            suggested = self.session.suggested_save_path()
            initial = str(suggested or Path.cwd() / "未命名_已修改.pdf")
            selected, _filter = QFileDialog.getSaveFileName(
                self.window,
                "另存为安全副本",
                initial,
                "PDF 文件 (*.pdf)",
            )
            if not selected:
                return
            target = Path(selected)
        self.save_to(target, on_complete=on_complete)

    def save_to(self, path: str | Path, *, on_complete=None) -> None:
        if self.session is None or self.tasks.active_count:
            return
        session = self.session
        target = Path(path)

        def perform(context: TaskContext):
            return session.save(target, progress=context.report_progress)

        def completed(result) -> None:
            self.window.set_saved_status(f"已安全保存：{result.output_path.name}")
            self.window.setWindowTitle(f"{result.output_path.name} — FlowPDF")
            self._update_history_actions()
            if on_complete is not None:
                on_complete()

        self.tasks.submit(
            perform,
            on_success=completed,
            on_error=lambda error: self.window.show_error("保存失败", str(error)),
            priority=30,
        )

    def undo(self) -> None:
        self._history_operation(redo=False)

    def redo(self) -> None:
        self._history_operation(redo=True)

    def delete_selected_pages(self) -> None:
        pages = self.window.selected_pages()
        if not pages or self.session is None:
            return
        answer = QMessageBox.question(
            self.window,
            "删除页面",
            f"确定删除选中的 {len(pages)} 页吗？此操作可以撤销。",
        )
        if answer is QMessageBox.StandardButton.Yes:
            self._mutate(PdfCommandType.DELETE_PAGES, page_indices=pages)

    def rotate_selected_pages(self, pages: list[int] | None = None) -> None:
        selected = pages or self.window.selected_pages()
        if selected:
            self._mutate(PdfCommandType.ROTATE_PAGES, page_indices=selected, degrees=90)

    def duplicate_selected_pages(self, pages: list[int] | None = None) -> None:
        selected = sorted(pages or self.window.selected_pages(), reverse=True)
        if not selected:
            return
        commands = [
            (PdfCommandType.DUPLICATE_PAGE, {"page_index": page, "insert_index": page + 1})
            for page in selected
        ]
        self._mutate_many(commands)

    def insert_blank_page(self, insert_index: int | None = None) -> None:
        if self.session is None:
            return
        index = self.window.document_view.current_page + 1 if insert_index is None else insert_index
        self._mutate(PdfCommandType.INSERT_BLANK_PAGE, insert_index=index)

    def insert_pdf_dialog(self, insert_index: int | None = None) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            self.window,
            "插入另一个 PDF",
            "",
            "PDF 文件 (*.pdf)",
        )
        if path:
            self.insert_pdf(path, insert_index)

    def insert_pdf(self, path: str | Path, insert_index: int | None = None) -> None:
        if self.session is None:
            return
        index = self.session.page_count if insert_index is None else insert_index
        self._mutate(
            PdfCommandType.INSERT_PDF,
            source_path=str(path),
            insert_index=index,
        )

    def move_page(self, old_index: int, new_index: int) -> None:
        self._mutate(PdfCommandType.MOVE_PAGE, old_index=old_index, new_index=new_index)

    def export_selected_pages(self, pages: list[int] | None = None) -> None:
        selected = pages or self.window.selected_pages()
        if not selected or self.session is None or self.tasks.active_count:
            return
        path, _filter = QFileDialog.getSaveFileName(
            self.window,
            "导出所选页面",
            "所选页面.pdf",
            "PDF 文件 (*.pdf)",
        )
        if not path:
            return
        session = self.session

        def perform(context: TaskContext) -> Path:
            context.report_progress(10, "正在导出页面")
            session.backend.export_pages(selected, path)
            return Path(path)

        self.tasks.submit(
            perform,
            on_success=lambda output: self.window.set_saved_status(f"已导出：{output.name}"),
            on_error=self._show_task_error,
        )

    def close_document(self, *, discard: bool = False) -> bool:
        if self.session is None:
            return True
        if not discard and not self._confirm_replace(lambda: self.close_document(discard=True)):
            return False
        self._close_session()
        return True

    def request_close(self) -> bool:
        if self._shutdown:
            return True
        if self.tasks.active_count:
            self.tasks.cancel_all()
            self._close_when_idle = True
            self.window.set_saved_status("正在取消后台任务，完成后将退出…")
            return False
        if self.session is not None and self.session.is_dirty:
            answer = QMessageBox.warning(
                self.window,
                "尚未保存修改",
                "是否先把修改保存为副本？原文件不会被覆盖。",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )
            if answer is QMessageBox.StandardButton.Cancel:
                return False
            if answer is QMessageBox.StandardButton.Save:
                self.save(on_complete=self.window.force_close_after_save)
                return False
        self._close_session()
        return self.shutdown()

    def shutdown(self) -> bool:
        if self._shutdown:
            return True
        self._autosave.stop()
        finished = self.tasks.shutdown()
        self._shutdown = finished
        return finished

    def _apply_loaded(self, loaded: LoadedSession) -> None:
        self._close_session()
        self.session = loaded.session
        path = self.session.source_path
        title = path.name if path is not None else "未命名.pdf"
        self.window.show_document(
            loaded.snapshot.source,
            loaded.snapshot.page_infos,
            title=title,
            revision=loaded.snapshot.revision,
        )
        if path is not None:
            self.recent_files.add(path)
            self.window.set_recent_files(self.recent_files.paths())
        self.window.set_saved_status("原文件只读保护；首次保存将创建已修改副本")
        self._autosave.start()
        self._update_history_actions()

    def _mutate(self, command_type: PdfCommandType, **payload: object) -> None:
        self._mutate_many([(command_type, payload)])

    def _mutate_many(
        self,
        commands: list[tuple[PdfCommandType, dict[str, object]]],
    ) -> None:
        if self.session is None or self.tasks.active_count:
            return
        session = self.session

        def perform(context: TaskContext) -> DocumentSnapshot:
            for command_type, payload in commands:
                context.raise_if_cancelled()
                session.execute(command_type, **payload)
            session.flush_recovery()
            return _snapshot(session, context)

        self.tasks.submit(
            perform,
            on_success=self._apply_snapshot,
            on_error=self._show_task_error,
            priority=20,
        )

    def _history_operation(self, *, redo: bool) -> None:
        if self.session is None or self.tasks.active_count:
            return
        session = self.session

        def perform(context: TaskContext) -> DocumentSnapshot | None:
            changed = session.redo() if redo else session.undo()
            if not changed:
                return None
            session.flush_recovery()
            return _snapshot(session, context)

        self.tasks.submit(
            perform,
            on_success=lambda snapshot: self._apply_snapshot(snapshot) if snapshot else None,
            on_error=self._show_task_error,
            priority=20,
        )

    def _apply_snapshot(self, snapshot: DocumentSnapshot) -> None:
        self.window.refresh_document(
            snapshot.source,
            snapshot.page_infos,
            revision=snapshot.revision,
        )
        self.window.set_saved_status("有未保存修改；原文件未被改动")
        self._update_history_actions()

    def _show_search_hits(self, hits: list[SearchHit]) -> None:
        self._search_hits = list(hits)
        self._search_index = 0 if hits else None
        self._display_search_position()

    def _display_search_position(self) -> None:
        current = self._search_index
        self.window.search_panel.set_results(
            0 if current is None else current + 1,
            len(self._search_hits),
        )
        self.window.document_view.show_search_hits(self._search_hits, current)

    def _update_history_actions(self) -> None:
        stack = self.session.command_stack if self.session is not None else None
        self.window.set_history_state(
            can_undo=bool(stack and stack.can_undo),
            can_redo=bool(stack and stack.can_redo),
            undo_text=stack.undo_description if stack else None,
            redo_text=stack.redo_description if stack else None,
        )

    def _request_password(self, path: Path, *, invalid: bool) -> None:
        prompt = "密码不正确，请重试：" if invalid else "此 PDF 需要密码："
        password, accepted = QInputDialog.getText(
            self.window,
            "输入 PDF 密码",
            prompt,
            QLineEdit.EchoMode.Password,
        )
        if accepted:
            self.open_path(path, password=password, confirmed=True)

    def _confirm_replace(self, after_save) -> bool:
        if self.session is None or not self.session.is_dirty:
            return True
        answer = QMessageBox.warning(
            self.window,
            "尚未保存修改",
            "当前文档有未保存修改。要先保存为副本吗？",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer is QMessageBox.StandardButton.Discard:
            return True
        if answer is QMessageBox.StandardButton.Save:
            self.save(on_complete=after_save)
        return False

    def _close_session(self) -> None:
        self._autosave.stop()
        if self.session is not None:
            self.session.close()
            self.session = None
        self._search_hits.clear()
        self._search_index = None
        self.window.clear_document()

    def _flush_recovery(self) -> None:
        if self.session is not None and self.session.is_dirty and not self.tasks.active_count:
            try:
                self.session.flush_recovery()
            except Exception as error:
                self.window.set_saved_status(f"自动恢复记录失败：{error}")

    def _show_task_error(self, error: Exception) -> None:
        self.window.show_error("操作失败", str(error))

    def _on_busy_changed(self, busy: bool) -> None:
        self.window.set_busy(busy)
        self.window.set_document_enabled(not busy and self.session is not None)
        if not busy:
            self._update_history_actions()
            if self._close_when_idle:
                self._close_when_idle = False
                QTimer.singleShot(0, self.window.close)

    def _connect_actions(self) -> None:
        window = self.window
        window.open_action.triggered.connect(lambda _checked=False: self.open_dialog())
        window.new_action.triggered.connect(lambda _checked=False: self.create_new())
        window.save_action.triggered.connect(lambda _checked=False: self.save())
        window.save_as_action.triggered.connect(lambda _checked=False: self.save(save_as=True))
        window.close_action.triggered.connect(lambda _checked=False: self.close_document())
        window.undo_action.triggered.connect(lambda _checked=False: self.undo())
        window.redo_action.triggered.connect(lambda _checked=False: self.redo())
        window.pdf_dropped.connect(self.open_path)
        window.recent_file_requested.connect(self.open_path)
        window.search_panel.search_requested.connect(self.search)
        window.search_panel.previous_requested.connect(self.previous_search_result)
        window.search_panel.next_requested.connect(self.next_search_result)
        window.delete_pages_action.triggered.connect(
            lambda _checked=False: self.delete_selected_pages()
        )
        window.rotate_pages_action.triggered.connect(
            lambda _checked=False: self.rotate_selected_pages()
        )
        window.duplicate_pages_action.triggered.connect(
            lambda _checked=False: self.duplicate_selected_pages()
        )
        window.insert_blank_action.triggered.connect(
            lambda _checked=False: self.insert_blank_page()
        )
        window.insert_pdf_action.triggered.connect(lambda _checked=False: self.insert_pdf_dialog())
        window.export_pages_action.triggered.connect(
            lambda _checked=False: self.export_selected_pages()
        )
        window.thumbnail_panel.page_move_requested.connect(self.move_page)
        window.thumbnail_panel.insert_pdf_requested.connect(self.insert_pdf)
        window.thumbnail_panel.delete_requested.connect(
            lambda pages: self._mutate(PdfCommandType.DELETE_PAGES, page_indices=pages)
        )
        window.thumbnail_panel.duplicate_requested.connect(self.duplicate_selected_pages)
        window.thumbnail_panel.rotate_requested.connect(self.rotate_selected_pages)
        window.thumbnail_panel.export_requested.connect(self.export_selected_pages)
        window.thumbnail_panel.insert_blank_requested.connect(self.insert_blank_page)


def _snapshot(session: DocumentSession, context: TaskContext) -> DocumentSnapshot:
    page_count = session.page_count
    infos: list[PageInfo] = []
    for index in range(page_count):
        context.raise_if_cancelled()
        infos.append(session.backend.page_size(index))
        if page_count > 10 and index % 10 == 0:
            context.report_progress(35 + round(35 * index / page_count), "正在读取页面尺寸")
    context.report_progress(75, "正在建立安全工作快照")
    data = session.backend.document_bytes()
    return DocumentSnapshot(
        RenderSource(session.document_id, data),
        infos,
        session.revision,
    )
