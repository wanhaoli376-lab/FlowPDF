from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QDialog, QFileDialog, QInputDialog, QLineEdit, QMessageBox

from flowpdf.backends.base import (
    AnnotationInfo,
    AnnotationKind,
    AnnotationSpec,
    InvalidPasswordError,
    PageInfo,
    PasswordRequiredError,
    PdfBackend,
    SearchHit,
    TextEditability,
    TextSpan,
    TextStyle,
)
from flowpdf.editing.document_session import DocumentSession
from flowpdf.editing.pdf_commands import PdfCommandType
from flowpdf.editing.tools import ToolMode
from flowpdf.rendering.render_scheduler import RenderSource
from flowpdf.services.recent_files import RecentFiles
from flowpdf.services.recovery_service import RecoveryService
from flowpdf.services.save_service import SafeSaveService
from flowpdf.services.task_service import TaskContext, TaskHandle, TaskService
from flowpdf.ui.dialogs.text_edit_dialog import TextEditDialog
from flowpdf.utils.coordinates import Point, Rect

if TYPE_CHECKING:
    from flowpdf.ui.main_window import MainWindow


@dataclass(frozen=True, slots=True)
class DocumentSnapshot:
    source: RenderSource
    page_infos: list[PageInfo]
    revision: int
    annotations: list[AnnotationInfo]


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
        backend_factory: Callable[[], PdfBackend],
        save_service: SafeSaveService | None = None,
        task_service: TaskService | None = None,
        connect_global_actions: bool = True,
    ) -> None:
        super().__init__(window)
        self.window = window
        self.recovery_service = recovery_service
        self.recent_files = recent_files
        self.backend_factory = backend_factory
        self.save_service = save_service or SafeSaveService()
        self.tasks = task_service or TaskService(max_threads=2, parent=self)
        self.session: DocumentSession | None = None
        self._search_hits: list[SearchHit] = []
        self._search_index: int | None = None
        self._search_handle: TaskHandle | None = None
        self._shutdown = False
        self._close_when_idle = False
        self._connect_global_actions = connect_global_actions
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
                self.backend_factory(),
                recovery_service=self.recovery_service,
                save_service=self.save_service,
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
                self.backend_factory(),
                recovery_service=self.recovery_service,
                save_service=self.save_service,
            )
            session.create_new()
            return LoadedSession(session, _snapshot(session, context))

        self.tasks.submit(create, on_success=self._apply_loaded, on_error=self._show_task_error)

    def offer_recovery(self) -> None:
        if self.session is not None or self.tasks.active_count:
            return
        sessions = self.recovery_service.list_session_files()
        if not sessions:
            return
        path, record = sessions[0]
        while True:
            box = QMessageBox(self.window)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("发现未完成的编辑会话")
            shown_name = Path(record.source_path).name if record.source_path else "未命名文档"
            box.setText(f"检测到“{shown_name}”的未保存修改。")
            box.setInformativeText("恢复操作不会覆盖原文件，保存时仍会创建副本。")
            restore_button = box.addButton("恢复", QMessageBox.ButtonRole.AcceptRole)
            discard_button = box.addButton("放弃", QMessageBox.ButtonRole.DestructiveRole)
            details_button = box.addButton("查看详情", QMessageBox.ButtonRole.ActionRole)
            box.addButton(QMessageBox.StandardButton.Cancel)
            box.exec()
            clicked = box.clickedButton()
            if clicked is restore_button:
                self.recover_path(path)
                return
            if clicked is discard_button:
                self.recovery_service.discard(path)
                return
            if clicked is details_button:
                QMessageBox.information(
                    self.window,
                    "恢复会话详情",
                    f"源文件：{record.source_path or '未命名文档'}\n"
                    f"最后更新：{record.updated_at}\n"
                    f"编辑命令：{len(record.commands)} 条",
                )
                continue
            return

    def recover_path(self, path: str | Path, *, password: str | None = None) -> None:
        if self.session is not None or self.tasks.active_count:
            return
        recovery_path = Path(path)

        def recover(context: TaskContext) -> LoadedSession:
            session = DocumentSession(
                self.backend_factory(),
                recovery_service=self.recovery_service,
                save_service=self.save_service,
            )
            session.recover(recovery_path, password=password)
            return LoadedSession(session, _snapshot(session, context))

        def failed(error: Exception) -> None:
            if isinstance(error, (PasswordRequiredError, InvalidPasswordError)):
                entered, accepted = QInputDialog.getText(
                    self.window,
                    "恢复加密 PDF",
                    "恢复日志不保存密码，请重新输入 PDF 密码：",
                    QLineEdit.EchoMode.Password,
                )
                if accepted:
                    self.recover_path(recovery_path, password=entered)
                return
            self.window.show_error("无法恢复编辑会话", str(error))

        def completed(loaded: LoadedSession) -> None:
            self._apply_loaded(loaded)
            self.window.set_saved_status("已恢复未保存修改；原文件仍未被改动")

        self.tasks.submit(recover, on_success=completed, on_error=failed, priority=25)

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

    def add_text(self, page_index: int, rect: Rect, text: str, style: TextStyle) -> None:
        self._mutate(
            PdfCommandType.ADD_TEXT,
            page_index=page_index,
            rect=rect,
            text=text,
            style=style,
        )

    def replace_text(
        self,
        page_index: int,
        rect: Rect,
        text: str,
        style: TextStyle,
    ) -> None:
        self._mutate(
            PdfCommandType.REPLACE_TEXT,
            page_index=page_index,
            rect=rect,
            text=text,
            style=style,
        )

    def add_image(self, page_index: int, rect: Rect, image_path: str | Path) -> None:
        self._mutate(
            PdfCommandType.ADD_IMAGE,
            page_index=page_index,
            rect=rect,
            image_path=str(image_path),
        )

    def add_annotation(self, page_index: int, annotation: AnnotationSpec) -> None:
        self._mutate(
            PdfCommandType.ADD_ANNOTATION,
            page_index=page_index,
            annotation=annotation,
        )

    def delete_annotation(self, page_index: int, xref: int) -> None:
        self._mutate(
            PdfCommandType.DELETE_ANNOTATION,
            page_index=page_index,
            xref=xref,
        )

    def permanent_delete(self, page_index: int, rect: Rect) -> None:
        self._mutate(
            PdfCommandType.DELETE_CONTENT,
            page_index=page_index,
            rect=rect,
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

    def merge_pdf_dialog(self) -> None:
        self.insert_pdf_dialog(self.session.page_count if self.session is not None else None)

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

    def split_pdf_dialog(self) -> None:
        directory = QFileDialog.getExistingDirectory(self.window, "选择拆分文件保存目录")
        if directory:
            self.split_to_directory(directory)

    def split_to_directory(self, directory: str | Path) -> None:
        if self.session is None or self.tasks.active_count:
            return
        destination = Path(directory)
        if not destination.is_dir():
            self.window.show_error("无法拆分 PDF", "所选保存目录不存在")
            return
        session = self.session
        source = session.saved_path or session.source_path
        stem = source.stem if source is not None else "未命名"

        def perform(context: TaskContext) -> list[Path]:
            outputs: list[Path] = []
            for index in range(session.page_count):
                context.raise_if_cancelled()
                output = _unique_page_path(destination, stem, index + 1)
                session.backend.export_pages([index], output)
                outputs.append(output)
                context.report_progress(
                    round((index + 1) * 100 / session.page_count),
                    f"正在导出第 {index + 1} 页",
                )
            return outputs

        self.tasks.submit(
            perform,
            on_success=lambda outputs: self.window.set_saved_status(
                f"已拆分为 {len(outputs)} 个 PDF"
            ),
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
            annotations=loaded.snapshot.annotations,
        )
        if path is not None:
            self.recent_files.add(path)
            self.window.set_recent_files(self.recent_files.paths())
        self.window.set_saved_status(
            "新建 PDF 尚未保存" if path is None else "原文件只读保护；首次保存将创建已修改副本"
        )
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
            annotations=snapshot.annotations,
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
            self.session.close(discard_recovery=True)
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

    def _handle_region(self, tool_value: str, page_index: int, rect: Rect) -> None:
        tool = ToolMode(tool_value)
        if tool is ToolMode.ADD_TEXT:
            dialog = TextEditDialog(parent=self.window)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                text, style = dialog.text_and_style()
                if text:
                    self.add_text(page_index, rect, text, style)
            return
        if tool is ToolMode.ADD_IMAGE:
            path, _filter = QFileDialog.getOpenFileName(
                self.window,
                "插入图片",
                "",
                "图片 (*.png *.jpg *.jpeg *.webp)",
            )
            if path:
                self.add_image(page_index, rect, path)
            return
        if tool is ToolMode.PERMANENT_DELETE:
            answer = QMessageBox.warning(
                self.window,
                "永久擦除",
                "这会真正删除框选区域内的文字、图片和矢量内容。保存后不能通过搜索或复制找回。继续吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer is QMessageBox.StandardButton.Yes:
                self.permanent_delete(page_index, rect)
            return

        kinds = {
            ToolMode.HIGHLIGHT: AnnotationKind.HIGHLIGHT,
            ToolMode.UNDERLINE: AnnotationKind.UNDERLINE,
            ToolMode.STRIKEOUT: AnnotationKind.STRIKEOUT,
            ToolMode.NOTE: AnnotationKind.NOTE,
            ToolMode.LINE: AnnotationKind.LINE,
            ToolMode.ARROW: AnnotationKind.ARROW,
            ToolMode.RECTANGLE: AnnotationKind.RECTANGLE,
            ToolMode.ELLIPSE: AnnotationKind.ELLIPSE,
        }
        kind = kinds.get(tool)
        if kind is None:
            return
        content = ""
        if kind is AnnotationKind.NOTE:
            content, accepted = QInputDialog.getMultiLineText(
                self.window,
                "添加便签",
                "便签内容：",
            )
            if not accepted:
                return
        points = ()
        if kind in {AnnotationKind.LINE, AnnotationKind.ARROW}:
            points = (Point(rect.x0, rect.y0), Point(rect.x1, rect.y1))
        color = (1.0, 0.82, 0.0)
        if kind not in {AnnotationKind.HIGHLIGHT, AnnotationKind.UNDERLINE}:
            color = (0.15, 0.39, 0.92)
        self.add_annotation(
            page_index,
            AnnotationSpec(
                kind=kind,
                rect=rect,
                color=color,
                opacity=0.45 if kind is AnnotationKind.HIGHLIGHT else 0.9,
                content=content,
                points=points,
            ),
        )

    def _edit_text_at(self, page_index: int, point: Point) -> None:
        if self.session is None or self.tasks.active_count:
            return
        session = self.session

        def locate(context: TaskContext) -> tuple[TextSpan | None, bool]:
            spans = session.backend.extract_text_spans(page_index)
            candidates = [span for span in spans if _contains(span.rect, point)]
            if candidates:
                return min(candidates, key=lambda span: span.rect.width * span.rect.height), False
            scanned_check = getattr(session.backend, "is_probably_scanned", None)
            scanned = bool(scanned_check and scanned_check(page_index))
            return None, scanned

        def selected(result: tuple[TextSpan | None, bool]) -> None:
            span, scanned = result
            if span is None:
                if scanned:
                    QMessageBox.information(
                        self.window,
                        "此页可能是扫描内容",
                        "未检测到可编辑文字层。可使用“识别此区域”或“识别当前页”；"
                        "当前版本尚未安装可选 OCR 组件。",
                    )
                else:
                    self.window.set_saved_status("双击位置没有可编辑文字块")
                return
            if span.editability is TextEditability.UNSUPPORTED:
                QMessageBox.information(
                    self.window,
                    "暂时无法编辑",
                    "此文字块使用了当前版本无法可靠处理的版式。",
                )
                return
            warning = ""
            if span.editability is TextEditability.FONT_SUBSTITUTION:
                warning = "原字体在本机不可用（黄色状态），保存时会使用相近字体替换。"
            dialog = TextEditDialog(
                text=span.text,
                style=_style_from_span(span),
                title="修改已有文字",
                warning=warning,
                parent=self.window,
            )
            if dialog.exec() == QDialog.DialogCode.Accepted:
                text, style = dialog.text_and_style()
                if text:
                    self.replace_text(page_index, span.rect, text, style)

        self.tasks.submit(locate, on_success=selected, on_error=self._show_task_error)

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
        if self._connect_global_actions:
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
        window.merge_pdf_action.triggered.connect(lambda _checked=False: self.merge_pdf_dialog())
        window.split_pdf_action.triggered.connect(lambda _checked=False: self.split_pdf_dialog())
        window.thumbnail_panel.page_move_requested.connect(self.move_page)
        window.thumbnail_panel.insert_pdf_requested.connect(self.insert_pdf)
        window.thumbnail_panel.delete_requested.connect(
            lambda pages: self._mutate(PdfCommandType.DELETE_PAGES, page_indices=pages)
        )
        window.thumbnail_panel.duplicate_requested.connect(self.duplicate_selected_pages)
        window.thumbnail_panel.rotate_requested.connect(self.rotate_selected_pages)
        window.thumbnail_panel.export_requested.connect(self.export_selected_pages)
        window.thumbnail_panel.insert_blank_requested.connect(self.insert_blank_page)
        window.document_view.region_selected.connect(self._handle_region)
        window.document_view.point_double_clicked.connect(self._edit_text_at)
        window.annotation_panel.annotation_activated.connect(
            lambda page, _xref: window.document_view.jump_to_page(page)
        )
        window.annotation_panel.delete_requested.connect(self.delete_annotation)


def _snapshot(session: DocumentSession, context: TaskContext) -> DocumentSnapshot:
    page_count = session.page_count
    infos: list[PageInfo] = []
    annotations: list[AnnotationInfo] = []
    for index in range(page_count):
        context.raise_if_cancelled()
        infos.append(session.backend.page_size(index))
        annotations.extend(session.backend.list_annotations(index))
        if page_count > 10 and index % 10 == 0:
            context.report_progress(35 + round(35 * index / page_count), "正在读取页面尺寸")
    context.report_progress(75, "正在建立安全工作快照")
    data, password = session.render_snapshot_data()
    return DocumentSnapshot(
        RenderSource(session.document_id, data, password),
        infos,
        session.revision,
        annotations,
    )


def _contains(rect: Rect, point: Point) -> bool:
    normalized = rect.normalized()
    return normalized.x0 <= point.x <= normalized.x1 and normalized.y0 <= point.y <= normalized.y1


def _style_from_span(span: TextSpan) -> TextStyle:
    color = span.color
    return TextStyle(
        font_family=span.font_family,
        font_size=span.font_size,
        color=(
            ((color >> 16) & 0xFF) / 255,
            ((color >> 8) & 0xFF) / 255,
            (color & 0xFF) / 255,
        ),
    )


def _unique_page_path(directory: Path, stem: str, page_number: int) -> Path:
    candidate = directory / f"{stem}_第{page_number}页.pdf"
    sequence = 2
    while candidate.exists():
        candidate = directory / f"{stem}_第{page_number}页 ({sequence}).pdf"
        sequence += 1
    return candidate
