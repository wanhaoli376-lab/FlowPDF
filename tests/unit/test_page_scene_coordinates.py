from __future__ import annotations

import pytest
from PySide6.QtWidgets import QGraphicsPixmapItem

from flowpdf.backends.base import PageInfo, RenderedPage
from flowpdf.rendering.tile_cache import TileKey
from flowpdf.ui.page_scene import PageScene
from flowpdf.utils.coordinates import Rect


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_page_item_uses_shared_transform_for_edit_regions(rotation: int, qapp) -> None:
    crop = Rect(10, 20, 610, 820)
    shown_width, shown_height = (800, 600) if rotation in (90, 270) else (600, 800)
    scene = PageScene()
    scene.set_pages(
        [
            PageInfo(
                shown_width,
                shown_height,
                rotation,
                crop,
                Rect(0, 0, 620, 840),
            )
        ]
    )
    page = scene.pages[0]
    original = Rect(110, 220, 260, 310)

    displayed = page.mapRectToScene(page.pdf_rect_to_local(original))
    restored = page.scene_rect_to_pdf(displayed).normalized()

    assert restored.x0 == pytest.approx(original.x0)
    assert restored.y0 == pytest.approx(original.y0)
    assert restored.x1 == pytest.approx(original.x1)
    assert restored.y1 == pytest.approx(original.y1)


def test_scene_releases_qt_pixmaps_outside_render_working_set(qapp) -> None:
    scene = PageScene()
    info = PageInfo(100, 100, 0, Rect(0, 0, 100, 100), Rect(0, 0, 100, 100))
    scene.set_pages([info, info])
    first = TileKey("doc", 0, 1.0, 0, None, 0, "page")
    second = TileKey("doc", 1, 1.0, 0, None, 0, "page")
    rendered = RenderedPage(1, 1, 3, b"\xff\xff\xff", Rect(0, 0, 1, 1), 1.0)
    scene.apply_render(first, rendered)
    scene.apply_render(second, rendered)

    scene.retain_rasters({second})

    assert scene.pages[0].raster_keys == frozenset()
    assert scene.pages[1].raster_keys == frozenset({second})


def test_reapplying_cached_tile_replaces_existing_qt_pixmap(qapp) -> None:
    scene = PageScene()
    info = PageInfo(100, 100, 0, Rect(0, 0, 100, 100), Rect(0, 0, 100, 100))
    scene.set_pages([info])
    key = TileKey("doc", 0, 3.0, 0, (0, 0, 50, 50), 0, "page")
    rendered = RenderedPage(1, 1, 3, b"\xff\xff\xff", Rect(0, 0, 1, 1), 3.0)

    scene.apply_render(key, rendered)
    scene.apply_render(key, rendered)

    pixmaps = [
        item for item in scene.pages[0].childItems() if isinstance(item, QGraphicsPixmapItem)
    ]
    assert len(pixmaps) == 1
