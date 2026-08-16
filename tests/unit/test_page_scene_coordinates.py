from __future__ import annotations

import pytest

from flowpdf.backends.base import PageInfo
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
