from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSizeF

from flowpdf.document_mode.layout import PageGeometry, PagePresentation
from flowpdf.document_mode.models import PageSetup


def test_page_presentation_separates_paper_and_round_trips_document_points() -> None:
    geometry = PageGeometry.from_setup(
        PageSetup(
            width_pt=300,
            height_pt=420,
            margin_top_pt=36,
            margin_bottom_pt=42,
            margin_left_pt=30,
            margin_right_pt=48,
        )
    )
    presentation = PagePresentation(
        geometry,
        page_count=3,
        page_gap_px=24,
        workspace_padding_px=16,
    )

    first_paper = presentation.paper_rect(0)
    second_paper = presentation.paper_rect(1)
    second_content = presentation.content_rect(1)
    assert second_paper.top() - first_paper.bottom() == 24
    assert second_content.left() - second_paper.left() == geometry.points_to_pixels(30)
    assert second_content.top() - second_paper.top() == geometry.points_to_pixels(36)

    logical = QPointF(64, geometry.content_height_px + 18)
    visual = presentation.document_to_visual(logical)
    restored = presentation.visual_to_document(visual)
    assert second_content.contains(visual)
    assert restored is not None
    assert abs(restored.x() - logical.x()) < 0.01
    assert abs(restored.y() - logical.y()) < 0.01

    gap_point = QPointF(first_paper.center().x(), first_paper.bottom() + 12)
    assert presentation.visual_to_document(gap_point) is None


def test_page_presentation_calculates_fit_width_and_single_page_zoom() -> None:
    geometry = PageGeometry.from_setup(PageSetup())
    presentation = PagePresentation(geometry, page_count=4)
    viewport = QSizeF(720, 540)

    fit_width = presentation.fit_width_factor(viewport)
    fit_page = presentation.fit_page_factor(viewport)

    assert abs(presentation.visual_size.width() * fit_width - viewport.width()) < 0.01
    assert presentation.paper_rect(0).height() * fit_page <= viewport.height()
    assert presentation.visual_size.width() * fit_page <= viewport.width()
    assert fit_page < fit_width


def test_page_presentation_returns_only_pages_intersecting_the_repaint_area() -> None:
    presentation = PagePresentation(
        PageGeometry.from_setup(PageSetup()),
        page_count=1_000,
    )
    target = presentation.paper_rect(500)

    visible = presentation.page_indices_intersecting(
        QRectF(target.left(), target.top() + 20, target.width(), 100)
    )

    assert visible == (500,)
