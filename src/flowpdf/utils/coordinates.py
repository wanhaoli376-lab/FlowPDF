"""One coordinate system module shared by every viewer and editing tool.

Qt uses device-independent logical pixels. PDF coordinates in this module use
PyMuPDF's top-left, unrotated page coordinates measured in points. Physical
viewport pixels are converted through ``device_pixel_ratio`` exactly once.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Point:
    x: float
    y: float


ZERO_POINT = Point(0.0, 0.0)


@dataclass(frozen=True, slots=True)
class Rect:
    x0: float
    y0: float
    x1: float
    y1: float

    def normalized(self) -> Rect:
        return Rect(
            min(self.x0, self.x1),
            min(self.y0, self.y1),
            max(self.x0, self.x1),
            max(self.y0, self.y1),
        )

    @property
    def width(self) -> float:
        rect = self.normalized()
        return rect.x1 - rect.x0

    @property
    def height(self) -> float:
        rect = self.normalized()
        return rect.y1 - rect.y0


@dataclass(frozen=True, slots=True)
class PageTransform:
    """Transform one cropped PDF page into its scene placement."""

    page_width: float
    page_height: float
    rotation: int = 0
    scale: float = 1.0
    scene_origin: Point = ZERO_POINT
    crop_origin: Point = ZERO_POINT

    def __post_init__(self) -> None:
        if self.rotation % 90:
            raise ValueError("页面旋转角度必须是 90 度的倍数")
        if self.scale <= 0:
            raise ValueError("缩放比例必须大于 0")
        if self.page_width <= 0 or self.page_height <= 0:
            raise ValueError("页面尺寸必须大于 0")
        object.__setattr__(self, "rotation", self.rotation % 360)

    @property
    def rotated_size(self) -> tuple[float, float]:
        if self.rotation in (90, 270):
            return self.page_height * self.scale, self.page_width * self.scale
        return self.page_width * self.scale, self.page_height * self.scale

    def pdf_to_scene(self, point: Point) -> Point:
        local_x = point.x - self.crop_origin.x
        local_y = point.y - self.crop_origin.y
        rotated = self._rotate(local_x, local_y)
        return Point(
            self.scene_origin.x + rotated.x * self.scale,
            self.scene_origin.y + rotated.y * self.scale,
        )

    def scene_to_pdf(self, point: Point) -> Point:
        local_x = (point.x - self.scene_origin.x) / self.scale
        local_y = (point.y - self.scene_origin.y) / self.scale
        unrotated = self._unrotate(local_x, local_y)
        return Point(
            unrotated.x + self.crop_origin.x,
            unrotated.y + self.crop_origin.y,
        )

    def pdf_rect_to_scene(self, rect: Rect) -> Rect:
        return _bounds(
            [
                self.pdf_to_scene(Point(rect.x0, rect.y0)),
                self.pdf_to_scene(Point(rect.x1, rect.y0)),
                self.pdf_to_scene(Point(rect.x1, rect.y1)),
                self.pdf_to_scene(Point(rect.x0, rect.y1)),
            ]
        )

    def scene_rect_to_pdf(self, rect: Rect) -> Rect:
        return _bounds(
            [
                self.scene_to_pdf(Point(rect.x0, rect.y0)),
                self.scene_to_pdf(Point(rect.x1, rect.y0)),
                self.scene_to_pdf(Point(rect.x1, rect.y1)),
                self.scene_to_pdf(Point(rect.x0, rect.y1)),
            ]
        )

    def viewport_to_scene(
        self,
        point: Point,
        *,
        scroll: Point = ZERO_POINT,
        view_scale: float = 1.0,
        device_pixel_ratio: float = 1.0,
    ) -> Point:
        _validate_view_factors(view_scale, device_pixel_ratio)
        logical_x = point.x / device_pixel_ratio
        logical_y = point.y / device_pixel_ratio
        return Point(
            (logical_x + scroll.x) / view_scale,
            (logical_y + scroll.y) / view_scale,
        )

    def scene_to_viewport(
        self,
        point: Point,
        *,
        scroll: Point = ZERO_POINT,
        view_scale: float = 1.0,
        device_pixel_ratio: float = 1.0,
    ) -> Point:
        _validate_view_factors(view_scale, device_pixel_ratio)
        return Point(
            (point.x * view_scale - scroll.x) * device_pixel_ratio,
            (point.y * view_scale - scroll.y) * device_pixel_ratio,
        )

    def _rotate(self, x: float, y: float) -> Point:
        if self.rotation == 0:
            return Point(x, y)
        if self.rotation == 90:
            return Point(self.page_height - y, x)
        if self.rotation == 180:
            return Point(self.page_width - x, self.page_height - y)
        return Point(y, self.page_width - x)

    def _unrotate(self, x: float, y: float) -> Point:
        if self.rotation == 0:
            return Point(x, y)
        if self.rotation == 90:
            return Point(y, self.page_height - x)
        if self.rotation == 180:
            return Point(self.page_width - x, self.page_height - y)
        return Point(self.page_width - y, x)


def _bounds(points: list[Point]) -> Rect:
    return Rect(
        min(point.x for point in points),
        min(point.y for point in points),
        max(point.x for point in points),
        max(point.y for point in points),
    )


def _validate_view_factors(view_scale: float, device_pixel_ratio: float) -> None:
    if view_scale <= 0 or device_pixel_ratio <= 0:
        raise ValueError("视图缩放比例和设备像素比必须大于 0")


def pdf_to_scene(point: Point, transform: PageTransform) -> Point:
    return transform.pdf_to_scene(point)


def scene_to_pdf(point: Point, transform: PageTransform) -> Point:
    return transform.scene_to_pdf(point)


def viewport_to_scene(point: Point, transform: PageTransform, **kwargs: object) -> Point:
    return transform.viewport_to_scene(point, **kwargs)  # type: ignore[arg-type]


def scene_to_viewport(point: Point, transform: PageTransform, **kwargs: object) -> Point:
    return transform.scene_to_viewport(point, **kwargs)  # type: ignore[arg-type]


def transform_rect(rect: Rect, transform: PageTransform) -> Rect:
    return transform.pdf_rect_to_scene(rect)


def transform_point(point: Point, transform: PageTransform) -> Point:
    return transform.pdf_to_scene(point)
