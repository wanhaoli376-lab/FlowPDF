from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from threading import Event
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


class TaskCancelled(RuntimeError):
    """Internal control flow for work whose result is no longer useful."""


class TaskContext:
    def __init__(self, token: Event, report: Callable[[int, str], None]) -> None:
        self._token = token
        self._report = report

    @property
    def is_cancelled(self) -> bool:
        return self._token.is_set()

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise TaskCancelled

    def report_progress(self, value: int, message: str) -> None:
        self.raise_if_cancelled()
        self._report(max(0, min(100, int(value))), message)


class TaskHandle:
    def __init__(self, task_id: str, token: Event) -> None:
        self.task_id = task_id
        self._token = token

    @property
    def is_cancelled(self) -> bool:
        return self._token.is_set()

    def cancel(self) -> None:
        self._token.set()


class _TaskSignals(QObject):
    finished = Signal(str, object, object, object)
    progress = Signal(str, int, str, object)


class _TaskRunnable(QRunnable):
    def __init__(
        self,
        task_id: str,
        token: Event,
        function: Callable[[TaskContext], object],
    ) -> None:
        super().__init__()
        self.task_id = task_id
        self.token = token
        self.function = function
        self.signals = _TaskSignals()

    @Slot()
    def run(self) -> None:
        context = TaskContext(
            self.token,
            lambda value, message: self.signals.progress.emit(
                self.task_id, value, message, self.token
            ),
        )
        try:
            context.raise_if_cancelled()
            result = self.function(context)
            context.raise_if_cancelled()
        except TaskCancelled:
            result = None
            error: Exception | None = None
        except Exception as exc:
            result = None
            error = exc
        else:
            error = None
        self.signals.finished.emit(self.task_id, result, error, self.token)


@dataclass(slots=True)
class _ActiveTask:
    handle: TaskHandle
    runnable: _TaskRunnable
    on_success: Callable[[Any], None] | None
    on_error: Callable[[Exception], None] | None


class TaskService(QObject):
    """Run cancellable application work away from the Qt GUI thread."""

    busy_changed = Signal(bool)
    progress = Signal(str, int, str)

    def __init__(self, *, max_threads: int = 2, parent: QObject | None = None) -> None:
        super().__init__(parent)
        if max_threads <= 0:
            raise ValueError("后台任务线程数必须大于 0")
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(max_threads)
        self._active: dict[str, _ActiveTask] = {}
        self._closed = False

    @property
    def active_count(self) -> int:
        return len(self._active)

    def submit[T](
        self,
        function: Callable[[TaskContext], T],
        *,
        on_success: Callable[[T], None] | None = None,
        on_error: Callable[[Exception], None] | None = None,
        priority: int = 0,
    ) -> TaskHandle:
        if self._closed:
            raise RuntimeError("后台任务服务已关闭")
        task_id = uuid.uuid4().hex
        token = Event()
        handle = TaskHandle(task_id, token)
        runnable = _TaskRunnable(task_id, token, function)
        runnable.signals.finished.connect(self._on_finished)
        runnable.signals.progress.connect(self._on_progress)
        was_idle = not self._active
        self._active[task_id] = _ActiveTask(handle, runnable, on_success, on_error)
        if was_idle:
            self.busy_changed.emit(True)
        self._pool.start(runnable, priority)
        return handle

    def cancel_all(self) -> None:
        for active in self._active.values():
            active.handle.cancel()

    def shutdown(self, timeout_ms: int = 5000) -> bool:
        if self._closed:
            return True
        self._closed = True
        self.cancel_all()
        self._pool.clear()
        finished = self._pool.waitForDone(timeout_ms)
        self._active.clear()
        self.busy_changed.emit(False)
        return finished

    @Slot(str, object, object, object)
    def _on_finished(
        self,
        task_id: str,
        result: object,
        error: Exception | None,
        token: Event,
    ) -> None:
        active = self._active.pop(task_id, None)
        if active is None:
            return
        if not token.is_set():
            if error is not None and active.on_error is not None:
                active.on_error(error)
            elif error is None and active.on_success is not None:
                active.on_success(result)
        if not self._active:
            self.busy_changed.emit(False)

    @Slot(str, int, str, object)
    def _on_progress(self, task_id: str, value: int, message: str, token: Event) -> None:
        if task_id in self._active and not token.is_set():
            self.progress.emit(task_id, value, message)
