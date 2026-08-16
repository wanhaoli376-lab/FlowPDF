from __future__ import annotations

import os
import uuid
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from threading import Event

from flowpdf.backends.base import PdfBackend, PdfError
from flowpdf.services.save_artifact_registry import SaveArtifactRegistry


class SafeSaveError(RuntimeError):
    """A save did not reach the validated atomic-replace point."""


@dataclass(frozen=True, slots=True)
class SaveResult:
    output_path: Path
    page_count: int
    file_size: int


class SafeSaveService:
    """Write, reopen, validate, and only then atomically replace the target."""

    def __init__(self, artifact_registry: SaveArtifactRegistry | None = None) -> None:
        self.artifact_registry = artifact_registry

    def save(
        self,
        backend: PdfBackend,
        output_path: str | Path,
        *,
        source_path: str | Path | None = None,
        allow_source_overwrite: bool = False,
        cancel_event: Event | None = None,
        progress: Callable[[int, str], None] | None = None,
    ) -> SaveResult:
        target = Path(output_path)
        if target.suffix.casefold() != ".pdf":
            target = target.with_suffix(".pdf")
        if not target.parent.is_dir():
            raise SafeSaveError("保存目录不存在")
        if target.is_symlink():
            raise SafeSaveError("为保护数据，不能保存到符号链接目标")
        if (
            source_path is not None
            and _same_path(target, Path(source_path))
            and not allow_source_overwrite
        ):
            raise SafeSaveError("默认不覆盖原文件，请另存为已修改副本")

        expected_pages = backend.page_count()
        temporary = target.parent / f".flowpdf-save-{uuid.uuid4().hex}.tmp.pdf"
        self._check_cancel(cancel_event)
        self._report(progress, 5, "正在准备安全保存")
        try:
            if self.artifact_registry is not None:
                self.artifact_registry.register(temporary)
            backend.save_document(temporary)
            self._report(progress, 65, "正在重新打开并验证")
            self._check_cancel(cancel_event)
            validation = backend.validate_saved_document(temporary)
            if validation.page_count != expected_pages:
                raise SafeSaveError(
                    f"保存验证失败：页数从 {expected_pages} 变为 {validation.page_count}"
                )
            if validation.file_size <= 0:
                raise SafeSaveError("保存验证失败：输出文件为空")
            self._check_cancel(cancel_event)
            self._report(progress, 90, "正在完成原子替换")
            os.replace(temporary, target)
        except SafeSaveError:
            raise
        except (OSError, PdfError) as exc:
            raise SafeSaveError(f"保存失败，原文件未被修改：{exc}") from exc
        finally:
            if temporary.exists() and not temporary.is_symlink():
                with suppress(OSError):
                    temporary.unlink()
            if self.artifact_registry is not None and not temporary.exists():
                with suppress(OSError, ValueError):
                    self.artifact_registry.unregister(temporary)

        self._report(progress, 100, "保存完成")
        return SaveResult(target, validation.page_count, validation.file_size)

    @staticmethod
    def _check_cancel(cancel_event: Event | None) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise SafeSaveError("保存已取消，原文件未被修改")

    @staticmethod
    def _report(
        progress: Callable[[int, str], None] | None,
        value: int,
        message: str,
    ) -> None:
        if progress is not None:
            progress(value, message)


def _same_path(left: Path, right: Path) -> bool:
    try:
        if left.exists() and right.exists():
            return os.path.samefile(left, right)
    except OSError:
        pass
    try:
        return (
            str(left.resolve(strict=False)).casefold()
            == str(right.resolve(strict=False)).casefold()
        )
    except OSError:
        return str(left.absolute()).casefold() == str(right.absolute()).casefold()
