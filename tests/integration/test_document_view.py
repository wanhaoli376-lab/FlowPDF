from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QTimer
from tests.generate_test_pdfs import generate_test_pdfs

from flowpdf.backends.pymupdf_backend import PyMuPdfBackend
from flowpdf.rendering.render_scheduler import RenderScheduler, RenderSource
from flowpdf.ui.document_view import DocumentView


def _wait_until(predicate, timeout_ms: int = 5000) -> bool:
    loop = QEventLoop()
    timer = QTimer()
    timer.setInterval(20)
    timeout = QTimer()
    timeout.setSingleShot(True)
    result = {"ready": False}

    def poll() -> None:
        if predicate():
            result["ready"] = True
            loop.quit()

    timer.timeout.connect(poll)
    timeout.timeout.connect(loop.quit)
    timer.start()
    timeout.start(timeout_ms)
    loop.exec()
    timer.stop()
    timeout.stop()
    return result["ready"]


def test_view_virtualizes_pages_and_switches_to_tiles_at_high_zoom(tmp_path, qapp) -> None:
    pdfs = generate_test_pdfs(tmp_path / "fixtures", include_stress=False)
    backend = PyMuPdfBackend()
    backend.open_document(pdfs["mixed"])
    infos = [backend.page_size(index) for index in range(backend.page_count())]
    source = RenderSource(backend.document_id, backend.document_bytes())
    scheduler = RenderScheduler(max_cache_bytes=32 * 1024 * 1024, max_threads=2)
    view = DocumentView(scheduler)
    view.resize(640, 480)
    view.show()

    view.set_document(source, infos)
    assert _wait_until(lambda: bool(view.page_scene.pages[0].raster_keys))
    assert len(view.page_scene.pages) == 3
    assert not view.page_scene.pages[2].raster_keys

    view.jump_to_page(2)
    assert _wait_until(lambda: bool(view.page_scene.pages[2].raster_keys))
    view.set_zoom(3.0)
    assert _wait_until(
        lambda: any(key.tile is not None for key in view.page_scene.pages[2].raster_keys)
    )
    view.close()
    view.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert scheduler.shutdown()
    scheduler.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
