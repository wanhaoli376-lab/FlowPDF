from __future__ import annotations

from threading import get_ident

from PySide6.QtCore import QEventLoop, QThread, QTimer

from flowpdf.services.task_service import TaskService


def test_task_service_runs_work_off_gui_thread_and_delivers_result(qapp) -> None:
    service = TaskService(max_threads=1)
    gui_thread = QThread.currentThread()
    results: list[tuple[int, int]] = []
    loop = QEventLoop()
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)

    service.submit(
        lambda context: (get_ident(), 42),
        on_success=lambda result: (results.append(result), loop.quit()),
    )
    timeout.start(3000)
    loop.exec()
    timeout.stop()

    assert results and results[0][1] == 42
    assert QThread.currentThread() is gui_thread
    assert service.active_count == 0
    assert service.shutdown()


def test_task_service_cancel_suppresses_callback(qapp) -> None:
    service = TaskService(max_threads=1)
    callbacks: list[object] = []
    handle = service.submit(
        lambda context: context.raise_if_cancelled(),
        on_success=callbacks.append,
        on_error=callbacks.append,
    )

    handle.cancel()
    assert service.shutdown()
    qapp.processEvents()
    assert callbacks == []
