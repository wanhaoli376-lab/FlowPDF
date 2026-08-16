from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, QTimer
from PySide6.QtWidgets import QAbstractItemView
from tests.generate_test_pdfs import generate_test_pdfs

from flowpdf.backends.pymupdf_backend import PyMuPdfBackend
from flowpdf.rendering.render_scheduler import RenderScheduler, RenderSource
from flowpdf.ui.thumbnail_panel import ThumbnailPanel


def test_thumbnail_panel_renders_visible_items_and_supports_multi_selection(tmp_path, qapp) -> None:
    pdfs = generate_test_pdfs(tmp_path / "fixtures", include_stress=False)
    backend = PyMuPdfBackend()
    backend.open_document(pdfs["mixed"])
    infos = [backend.page_size(index) for index in range(backend.page_count())]
    source = RenderSource(backend.document_id, backend.document_bytes())
    scheduler = RenderScheduler(max_cache_bytes=8 * 1024 * 1024, max_threads=2)
    panel = ThumbnailPanel(scheduler)
    panel.resize(190, 420)
    panel.show()
    panel.set_document(source, infos)

    loop = QEventLoop()
    poll = QTimer()
    timeout = QTimer()
    timeout.setSingleShot(True)
    poll.setInterval(20)
    poll.timeout.connect(lambda: loop.quit() if not panel.item(0).icon().isNull() else None)
    timeout.timeout.connect(loop.quit)
    poll.start()
    timeout.start(5000)
    loop.exec()
    poll.stop()
    timeout.stop()

    assert panel.count() == 3
    assert not panel.item(0).icon().isNull()
    assert panel.selectionMode() is QAbstractItemView.SelectionMode.ExtendedSelection
    panel.item(0).setSelected(True)
    panel.item(2).setSelected(True)
    assert panel.selected_pages() == [0, 2]

    panel.close()
    panel.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert scheduler.shutdown()
    scheduler.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
