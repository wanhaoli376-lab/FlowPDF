from __future__ import annotations

import os
from threading import Event

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer
from tests.generate_test_pdfs import generate_test_pdfs

from flowpdf.backends.base import RenderedPage
from flowpdf.rendering.render_scheduler import (
    RenderPriority,
    RenderScheduler,
    RenderSource,
)
from flowpdf.rendering.tile_cache import TileKey
from flowpdf.utils.coordinates import Rect


def test_scheduler_renders_real_pdf_off_main_thread_and_caches_result(tmp_path, qapp) -> None:
    pdfs = generate_test_pdfs(tmp_path / "fixtures", include_stress=False)
    source = RenderSource("doc", pdfs["normal"].read_bytes())
    key = TileKey("doc", 0, 0.5, 0, None, 0)
    scheduler = RenderScheduler(max_cache_bytes=4 * 1024 * 1024, max_threads=2)
    received: list[RenderedPage] = []
    loop = QEventLoop()
    timeout = QTimer()
    timeout.setSingleShot(True)
    scheduler.tile_ready.connect(lambda _key, page: (received.append(page), loop.quit()))

    assert scheduler.request(source, key, owner="view", priority=RenderPriority.VISIBLE)
    timeout.timeout.connect(loop.quit)
    timeout.start(5000)
    loop.exec()
    timeout.stop()

    assert received and received[0].width == 298
    assert scheduler.pending_count == 0
    assert scheduler.cache_bytes == received[0].byte_size

    cached: list[RenderedPage] = []
    scheduler.tile_ready.connect(lambda _key, page: cached.append(page))
    assert scheduler.request(source, key, owner="view") is False
    qapp.processEvents()
    assert cached
    assert scheduler.shutdown()


def test_obsolete_owner_task_is_cancelled_before_result_delivery(qapp) -> None:
    started = Event()
    release = Event()

    def delayed_renderer(source, key, token):
        started.set()
        release.wait(2)
        return RenderedPage(1, 1, 3, b"\xff\xff\xff", Rect(0, 0, 1, 1), key.scale)

    scheduler = RenderScheduler(
        max_cache_bytes=1024,
        max_threads=1,
        renderer=delayed_renderer,
    )
    delivered: list[TileKey] = []
    scheduler.tile_ready.connect(lambda key, _page: delivered.append(key))
    source = RenderSource("doc", b"not-read-by-test-renderer")
    key = TileKey("doc", 10, 1.0, 0, None, 0)
    scheduler.request(source, key, owner="view")
    assert started.wait(1)

    scheduler.cancel_owner_obsolete("view", set())
    release.set()
    loop = QEventLoop()
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    timeout.start(200)
    loop.exec()

    assert delivered == []
    assert scheduler.pending_count == 0
    assert scheduler.shutdown()
