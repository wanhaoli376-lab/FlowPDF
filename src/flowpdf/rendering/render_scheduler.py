from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import IntEnum
from threading import Event, RLock

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal, Slot

from flowpdf.backends.base import RenderedPage
from flowpdf.rendering.tile_cache import MemoryBoundLruCache, TileKey
from flowpdf.rendering.tile_renderer import RenderCancelled, render_pdf_snapshot


@dataclass(frozen=True, slots=True)
class RenderSource:
    document_id: str
    data: bytes
    password: str | None = field(default=None, repr=False)


class RenderPriority(IntEnum):
    PRELOAD = 0
    THUMBNAIL = 20
    ADJACENT = 50
    CURRENT_PAGE = 75
    VISIBLE = 100


class CancellationToken:
    def __init__(self) -> None:
        self._event = Event()

    def cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()


class _TaskSignals(QObject):
    finished = Signal(object, object, object, object)


class _RenderTask(QRunnable):
    def __init__(
        self,
        source: RenderSource,
        key: TileKey,
        token: CancellationToken,
        renderer: Callable[[RenderSource, TileKey, CancellationToken], RenderedPage],
    ) -> None:
        super().__init__()
        self.source = source
        self.key = key
        self.token = token
        self.renderer = renderer
        self.signals = _TaskSignals()

    @Slot()
    def run(self) -> None:
        if self.token.is_cancelled():
            self.signals.finished.emit(self.key, None, None, self.token)
            return
        try:
            result = self.renderer(self.source, self.key, self.token)
        except RenderCancelled:
            result = None
            error: Exception | None = None
        except Exception as exc:
            result = None
            error = exc
        else:
            error = None
        self.signals.finished.emit(self.key, result, error, self.token)


@dataclass(slots=True)
class _Pending:
    token: CancellationToken
    owners: set[str]
    task: _RenderTask


class RenderScheduler(QObject):
    """Priority rendering, owner-scoped cancellation, and hard-bounded caching."""

    tile_ready = Signal(object, object)
    tile_failed = Signal(object, str)
    queue_changed = Signal(int)

    def __init__(
        self,
        *,
        max_cache_bytes: int = 512 * 1024 * 1024,
        max_threads: int | None = None,
        renderer: Callable[
            [RenderSource, TileKey, CancellationToken], RenderedPage
        ] = render_pdf_snapshot,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._cache = MemoryBoundLruCache[TileKey, RenderedPage](
            max_bytes=max_cache_bytes,
            size_of=lambda rendered: rendered.byte_size,
        )
        self._renderer = renderer
        self._pool = QThreadPool(self)
        cpu_count = os.cpu_count() or 2
        thread_count = max_threads if max_threads is not None else 1
        self._pool.setMaxThreadCount(max(1, min(thread_count, cpu_count)))
        self._pending: dict[TileKey, _Pending] = {}
        self._inflight: dict[CancellationToken, _RenderTask] = {}
        self._lock = RLock()
        self._closed = False
        self._shutdown_complete = False

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)

    @property
    def cache_bytes(self) -> int:
        return self._cache.current_bytes

    @property
    def cache_limit_bytes(self) -> int:
        return self._cache.max_bytes

    def request(
        self,
        source: RenderSource,
        key: TileKey,
        *,
        owner: str,
        priority: RenderPriority = RenderPriority.ADJACENT,
    ) -> bool:
        if self._closed:
            return False
        cached = self._cache.get(key)
        if cached is not None:
            QTimer.singleShot(0, lambda: self.tile_ready.emit(key, cached))
            return False
        with self._lock:
            pending = self._pending.get(key)
            if pending is not None:
                pending.owners.add(owner)
                return False
            token = CancellationToken()
            task = _RenderTask(source, key, token, self._renderer)
            task.signals.finished.connect(self._on_finished)
            self._pending[key] = _Pending(token, {owner}, task)
            self._inflight[token] = task
            count = len(self._pending)
        self.queue_changed.emit(count)
        self._pool.start(task, int(priority))
        return True

    def cancel_owner_obsolete(self, owner: str, desired_keys: set[TileKey]) -> int:
        cancelled = 0
        with self._lock:
            for key, pending in tuple(self._pending.items()):
                if owner not in pending.owners or key in desired_keys:
                    continue
                pending.owners.discard(owner)
                if not pending.owners:
                    pending.token.cancel()
                    self._pending.pop(key, None)
                    cancelled += 1
            count = len(self._pending)
        if cancelled:
            self.queue_changed.emit(count)
        return cancelled

    def cancel_all(self) -> None:
        with self._lock:
            for pending in self._pending.values():
                pending.token.cancel()
            self._pending.clear()
        self._pool.clear()
        self.queue_changed.emit(0)

    def clear_cache(self) -> None:
        self._cache.clear()

    def set_cache_limit(self, max_bytes: int) -> None:
        self._cache.resize(max_bytes)

    def shutdown(self, timeout_ms: int = 5000) -> bool:
        if self._shutdown_complete:
            return True
        self._closed = True
        self.cancel_all()
        finished = self._pool.waitForDone(timeout_ms)
        if finished:
            with self._lock:
                self._inflight.clear()
            self._shutdown_complete = True
        return finished

    @Slot(object, object, object, object)
    def _on_finished(
        self,
        key: TileKey,
        rendered: RenderedPage | None,
        error: Exception | None,
        token: CancellationToken,
    ) -> None:
        with self._lock:
            self._inflight.pop(token, None)
            pending = self._pending.get(key)
            if pending is None or pending.token is not token:
                return
            self._pending.pop(key, None)
            count = len(self._pending)
        self.queue_changed.emit(count)
        if token.is_cancelled():
            return
        if error is not None:
            self.tile_failed.emit(key, str(error))
            return
        if rendered is not None:
            self._cache.put(key, rendered)
            self.tile_ready.emit(key, rendered)
