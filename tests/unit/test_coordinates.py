from __future__ import annotations

import pytest

from flowpdf.utils.coordinates import PageTransform, Point, Rect


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_pdf_scene_round_trip_handles_rotation_and_crop(rotation: int) -> None:
    transform = PageTransform(
        page_width=600,
        page_height=800,
        rotation=rotation,
        scale=1.75,
        scene_origin=Point(25, 40),
        crop_origin=Point(10, 20),
    )
    original = Point(123.5, 245.25)

    restored = transform.scene_to_pdf(transform.pdf_to_scene(original))

    assert restored.x == pytest.approx(original.x)
    assert restored.y == pytest.approx(original.y)


def test_transform_rect_returns_rotated_scene_bounds() -> None:
    transform = PageTransform(page_width=600, page_height=800, rotation=90, scale=2)

    result = transform.pdf_rect_to_scene(Rect(100, 200, 220, 260))

    assert result == Rect(1080, 200, 1200, 440)


def test_viewport_scene_conversion_accounts_for_scroll_zoom_and_dpi() -> None:
    transform = PageTransform(page_width=600, page_height=800)
    viewport_point = Point(400, 240)

    scene = transform.viewport_to_scene(
        viewport_point,
        scroll=Point(50, 20),
        view_scale=2,
        device_pixel_ratio=2,
    )

    assert scene == Point(125, 70)
    assert (
        transform.scene_to_viewport(
            scene,
            scroll=Point(50, 20),
            view_scale=2,
            device_pixel_ratio=2,
        )
        == viewport_point
    )
