from __future__ import annotations

from dataclasses import dataclass

from flowpdf.document_mode.models import PageSetup

POINTS_TO_PIXELS = 96.0 / 72.0


@dataclass(frozen=True, slots=True)
class PageGeometry:
    page_width_pt: float
    page_height_pt: float
    margin_top_pt: float
    margin_bottom_pt: float
    margin_left_pt: float
    margin_right_pt: float

    @classmethod
    def from_setup(cls, setup: PageSetup) -> PageGeometry:
        return cls(
            page_width_pt=setup.width_pt,
            page_height_pt=setup.height_pt,
            margin_top_pt=setup.margin_top_pt,
            margin_bottom_pt=setup.margin_bottom_pt,
            margin_left_pt=setup.margin_left_pt,
            margin_right_pt=setup.margin_right_pt,
        )

    @property
    def content_width_px(self) -> float:
        return (self.page_width_pt - self.margin_left_pt - self.margin_right_pt) * POINTS_TO_PIXELS

    @property
    def content_height_px(self) -> float:
        return (self.page_height_pt - self.margin_top_pt - self.margin_bottom_pt) * POINTS_TO_PIXELS

    @property
    def page_width_px(self) -> float:
        return self.page_width_pt * POINTS_TO_PIXELS

    @property
    def page_height_px(self) -> float:
        return self.page_height_pt * POINTS_TO_PIXELS

    @staticmethod
    def points_to_pixels(value: float) -> float:
        return value * POINTS_TO_PIXELS

    @staticmethod
    def pixels_to_points(value: float) -> float:
        return value / POINTS_TO_PIXELS
