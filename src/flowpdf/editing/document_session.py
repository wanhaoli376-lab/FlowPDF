from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from flowpdf.backends.base import (
    InvalidPasswordError,
    PasswordRequiredError,
    PdfBackend,
    PdfError,
)
from flowpdf.editing.command_stack import CommandStack
from flowpdf.editing.pdf_commands import (
    PdfCommandType,
    PdfHistoryLimitError,
    PdfMutationCommand,
)
from flowpdf.services.recovery_service import RecoveryService
from flowpdf.services.save_service import SafeSaveService, SaveResult
from flowpdf.utils.paths import suggest_edited_copy


class DocumentSessionError(RuntimeError):
    """A document session could not complete a user-level operation."""


class DocumentSession:
    """Own one working document, its history, safe save, and recovery lifecycle."""

    def __init__(
        self,
        backend: PdfBackend,
        *,
        recovery_service: RecoveryService,
        save_service: SafeSaveService | None = None,
        max_history: int = 100,
        max_history_bytes: int = 256 * 1024 * 1024,
    ) -> None:
        self.backend = backend
        self.recovery_service = recovery_service
        self.save_service = save_service or SafeSaveService()
        self.command_stack = CommandStack(
            max_depth=max_history,
            max_history_bytes=max_history_bytes,
        )
        self.max_history_bytes = max_history_bytes
        self.source_path: Path | None = None
        self.saved_path: Path | None = None
        self._recovery_path: Path | None = None
        self._needs_initial_save = False
        self._source_bytes: bytes | None = None
        self._source_size_bytes = 0
        self._password: str | None = None
        self._listeners: list[Callable[[], None]] = []
        self.command_stack.add_listener(self._notify)

    @property
    def is_open(self) -> bool:
        return bool(self.backend.document_id)

    @property
    def is_dirty(self) -> bool:
        return self._needs_initial_save or self.command_stack.is_dirty

    @property
    def page_count(self) -> int:
        return self.backend.page_count() if self.is_open else 0

    @property
    def document_id(self) -> str:
        return self.backend.document_id

    @property
    def revision(self) -> int:
        return self.command_stack.revision + self.backend.revision

    def add_listener(self, callback: Callable[[], None]) -> None:
        self._listeners.append(callback)

    def open(self, path: str | Path, *, password: str | None = None) -> None:
        self._guard_replace_session()
        try:
            self.backend.open_document(path, password=password)
            source_path = Path(path).resolve(strict=True)
            source_bytes = source_path.read_bytes()
        except PdfError:
            raise
        except OSError as exc:
            self.backend.close_document()
            raise DocumentSessionError("PDF 已打开，但无法建立只读工作副本") from exc
        self.source_path = source_path
        self.saved_path = None
        self.command_stack.clear()
        self.command_stack.mark_clean()
        self._recovery_path = None
        self._needs_initial_save = False
        self._source_bytes = source_bytes
        self._source_size_bytes = len(source_bytes)
        self._password = password
        self._notify()

    def create_new(self, *, width: float = 595, height: float = 842) -> None:
        self._guard_replace_session()
        self.backend.create_document(width=width, height=height)
        self.source_path = None
        self.saved_path = None
        self.command_stack.clear()
        self.command_stack.mark_clean()
        self._recovery_path = None
        self._needs_initial_save = True
        self._source_bytes = None
        self._source_size_bytes = 0
        self._password = None
        self._notify()

    def execute(self, command_type: PdfCommandType, **payload: object) -> None:
        if not self.is_open:
            raise DocumentSessionError("尚未打开 PDF")
        secrets: dict[str, object] = {}
        for key in ("password", "passphrase", "pdf_password"):
            if key in payload:
                secrets[key] = payload.pop(key)
        self.command_stack.push(
            PdfMutationCommand(
                self.backend,
                command_type,
                payload,
                secrets=secrets,
                max_history_bytes=self.max_history_bytes,
                source_size_bytes=self._source_size_bytes,
            )
        )
        self._source_bytes = None

    def undo(self) -> bool:
        return self.command_stack.undo()

    def redo(self) -> bool:
        return self.command_stack.redo()

    def flush_recovery(self) -> Path | None:
        if not self.is_open or not self.is_dirty:
            return None
        source = str(self.source_path) if self.source_path is not None else ""
        self._recovery_path = self.recovery_service.write(
            document_id=self.document_id,
            source_path=source,
            output_path=str(self.saved_path) if self.saved_path is not None else None,
            commands=self.command_stack.serialize(),
        )
        return self._recovery_path

    def recover(self, recovery_path: str | Path, *, password: str | None = None) -> None:
        self._guard_replace_session()
        record = self.recovery_service.load(recovery_path)
        initial: bytes | None = None
        try:
            if record.source_path:
                self.backend.open_document(record.source_path, password=password)
                self.source_path = Path(record.source_path).resolve(strict=True)
                self._source_bytes = self.source_path.read_bytes()
                self._source_size_bytes = len(self._source_bytes)
                self._password = password
            else:
                self.backend.create_document()
                self.source_path = None
                self._source_bytes = None
                self._source_size_bytes = 0
                self._password = None
            if (
                record.commands
                and self._source_bytes is not None
                and len(self._source_bytes) > self.max_history_bytes // 4
            ):
                raise PdfHistoryLimitError("源 PDF 超过安全恢复快照上限，请先拆分文档")
            initial = self.backend.document_bytes() if record.commands else None
            self.command_stack.clear()
            for command_record in record.commands:
                command = PdfMutationCommand.from_record(
                    self.backend,
                    command_record,
                    max_history_bytes=self.max_history_bytes,
                    source_size_bytes=self._source_size_bytes,
                )
                self.command_stack.push(command)
            if record.commands:
                self._source_bytes = None
        except (PasswordRequiredError, InvalidPasswordError):
            raise
        except (PdfError, OSError, ValueError, KeyError) as exc:
            if self.is_open:
                if initial is not None:
                    self.backend.load_bytes(initial)
                else:
                    self.backend.close_document()
                self.command_stack.clear()
            self._source_bytes = None
            self._source_size_bytes = 0
            self._password = None
            raise DocumentSessionError(f"无法恢复编辑会话：{exc}") from exc
        self.saved_path = Path(record.output_path) if record.output_path else None
        self._recovery_path = Path(recovery_path)
        self._needs_initial_save = not bool(record.source_path)
        self._notify()

    def suggested_save_path(self) -> Path | None:
        if self.saved_path is not None:
            return self.saved_path
        if self.source_path is None:
            return None
        return suggest_edited_copy(self.source_path)

    def render_snapshot_data(self) -> tuple[bytes, str | None]:
        """Return one immutable renderer input without reserializing a pristine source."""
        if self._source_bytes is not None and not self.command_stack.has_applied_commands:
            return self._source_bytes, self._password
        return self.backend.document_bytes(), self._password

    def save(
        self,
        output_path: str | Path | None = None,
        *,
        allow_source_overwrite: bool = False,
        progress: Callable[[int, str], None] | None = None,
    ) -> SaveResult:
        if not self.is_open:
            raise DocumentSessionError("尚未打开 PDF")
        target = Path(output_path) if output_path is not None else self.suggested_save_path()
        if target is None:
            raise DocumentSessionError("新建文档需要先选择保存位置")
        result = self.save_service.save(
            self.backend,
            target,
            source_path=self.source_path,
            allow_source_overwrite=allow_source_overwrite,
            progress=progress,
        )
        self.saved_path = result.output_path
        self.command_stack.mark_clean()
        self._needs_initial_save = False
        if self._recovery_path is not None:
            self.recovery_service.discard(self._recovery_path)
            self._recovery_path = None
        self._notify()
        return result

    def close(self, *, discard_recovery: bool = False) -> None:
        if discard_recovery and self._recovery_path is not None:
            self.recovery_service.discard(self._recovery_path)
        self.backend.close_document()
        self.source_path = None
        self.saved_path = None
        self.command_stack.clear()
        self._recovery_path = None
        self._needs_initial_save = False
        self._source_bytes = None
        self._source_size_bytes = 0
        self._password = None
        self._notify()

    def _guard_replace_session(self) -> None:
        if self.is_open and self.is_dirty:
            raise DocumentSessionError("当前文档有未保存修改，请先保存或放弃修改")
        if self.is_open:
            self.backend.close_document()

    def _notify(self) -> None:
        for callback in tuple(self._listeners):
            callback()
