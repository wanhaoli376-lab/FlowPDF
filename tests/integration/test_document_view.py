from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QPointF, Qt, QTimer
from PySide6.QtTest import QTest
from tests.generate_test_pdfs import generate_test_pdfs

from flowpdf.backends.base import PageInfo
from flowpdf.backends.pymupdf_backend import PyMuPdfBackend
from flowpdf.editing.tools import ToolMode
from flowpdf.rendering.render_scheduler import RenderScheduler, RenderSource
from flowpdf.ui.document_view import DocumentView
from flowpdf.utils.coordinates import Rect


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


def test_region_tool_emits_pdf_coordinates_and_escape_returns_to_select(qapp) -> None:
    scheduler = RenderScheduler(max_cache_bytes=1024 * 1024, max_threads=1)
    view = DocumentView(scheduler)
    view.resize(640, 480)
    view.page_scene.set_pages(
        [
            PageInfo(
                595,
                842,
                0,
                Rect(0, 0, 595, 842),
                Rect(0, 0, 595, 842),
            )
        ]
    )
    view.show()
    view.centerOn(view.page_scene.pages[0])
    qapp.processEvents()
    regions: list[tuple[str, int, Rect]] = []
    view.region_selected.connect(lambda tool, page, rect: regions.append((tool, page, rect)))
    page = view.page_scene.pages[0]
    start = view.mapFromScene(page.mapToScene(QPointF(80, 100)))
    end = view.mapFromScene(page.mapToScene(QPointF(260, 170)))

    view.set_tool(ToolMode.ADD_TEXT)
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(view.viewport(), end)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)

    assert len(regions) == 1
    tool, page_index, rect = regions[0]
    assert tool == ToolMode.ADD_TEXT.value
    assert page_index == 0
    assert rect.x0 == pytest.approx(80, abs=1)
    assert rect.y0 == pytest.approx(100, abs=1)
    assert rect.x1 == pytest.approx(260, abs=1)
    assert rect.y1 == pytest.approx(170, abs=1)

    QTest.keyClick(view, Qt.Key.Key_Escape)
    assert view.tool is ToolMode.SELECT
    view.close()
    assert scheduler.shutdown()
