from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from flowpdf.editing.text_editor import OverflowStrategy
from flowpdf.utils.coordinates import Point, Rect

type Color = tuple[float, float, float]


class PdfError(RuntimeError):
    """Base class for user-facing PDF errors."""


class PdfOpenError(PdfError):
    pass


class PasswordRequiredError(PdfOpenError):
    pass


class InvalidPasswordError(PdfOpenError):
    pass


class PdfPermissionError(PdfError):
    pass


class PdfResourceLimitError(PdfError):
    pass


class PdfEditError(PdfError):
    pass


class PdfSaveError(PdfError):
    pass


@dataclass(frozen=True, slots=True)
class PdfResourceLimits:
    max_source_bytes: int = 1_000_000_000
    max_pages: int = 5_000
    max_page_dimension: float = 20_000.0
    max_render_pixels: int = 80_000_000
    max_image_bytes: int = 200_000_000


@dataclass(frozen=True, slots=True)
class PageInfo:
    width: float
    height: float
    rotation: int
    cropbox: Rect
    mediabox: Rect


@dataclass(frozen=True, slots=True)
class RenderedPage:
    width: int
    height: int
    stride: int
    samples: bytes
    clip: Rect
    scale: float

    @property
    def byte_size(self) -> int:
        return len(self.samples)


@dataclass(frozen=True, slots=True)
class DocumentValidation:
    page_count: int
    file_size: int
    repaired: bool


class TextEditability(StrEnum):
    RELIABLE = "reliable"
    FONT_SUBSTITUTION = "font_substitution"
    SCANNED = "scanned"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class TextSpan:
    page_index: int
    text: str
    rect: Rect
    font_size: float
    color: int
    font_family: str
    flags: int
    block_index: int
    line_index: int
    editability: TextEditability


@dataclass(frozen=True, slots=True)
class SearchHit:
    page_index: int
    rect: Rect


@dataclass(frozen=True, slots=True)
class ImageInfo:
    page_index: int
    rect: Rect
    xref: int
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class TextStyle:
    font_family: str = "Microsoft YaHei"
    font_size: float = 11.0
    color: Color = (0.0, 0.0, 0.0)
    background_color: Color | None = None
    opacity: float = 1.0
    bold: bool = False
    italic: bool = False
    underline: bool = False
    alignment: int = 0
    overflow: OverflowStrategy = OverflowStrategy.WRAP


class AnnotationKind(StrEnum):
    HIGHLIGHT = "highlight"
    UNDERLINE = "underline"
    STRIKEOUT = "strikeout"
    NOTE = "note"
    FREE_TEXT = "free_text"
    INK = "ink"
    LINE = "line"
    ARROW = "arrow"
    RECTANGLE = "rectangle"
    ELLIPSE = "ellipse"


@dataclass(frozen=True, slots=True)
class AnnotationSpec:
    kind: AnnotationKind
    rect: Rect
    color: Color = (1.0, 0.82, 0.0)
    fill_color: Color | None = None
    opacity: float = 0.5
    line_width: float = 1.5
    content: str = ""
    author: str = "FlowPDF"
    points: tuple[Point, ...] = ()


class PdfBackend(ABC):
    """Engine seam used by the UI, editing model, and persistence modules."""

    @property
    @abstractmethod
    def document_id(self) -> str:
        raise NotImplementedError

    @property
    @abstractmethod
    def revision(self) -> int:
        raise NotImplementedError

    @property
    @abstractmethod
    def source_path(self) -> Path | None:
        raise NotImplementedError

    @abstractmethod
    def open_document(self, path: str | Path, password: str | None = None) -> None:
        raise NotImplementedError

    @abstractmethod
    def create_document(self, *, width: float = 595, height: float = 842) -> None:
        raise NotImplementedError

    @abstractmethod
    def close_document(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def page_count(self) -> int:
        raise NotImplementedError

    @abstractmethod
    def page_size(self, page_index: int) -> PageInfo:
        raise NotImplementedError

    @abstractmethod
    def render_page(self, page_index: int, scale: float, clip: Rect | None = None) -> RenderedPage:
        raise NotImplementedError

    @abstractmethod
    def extract_text_spans(self, page_index: int) -> list[TextSpan]:
        raise NotImplementedError

    @abstractmethod
    def search_text(self, query: str) -> list[SearchHit]:
        raise NotImplementedError

    @abstractmethod
    def add_text(self, page_index: int, rect: Rect, text: str, style: TextStyle) -> Rect:
        raise NotImplementedError

    @abstractmethod
    def replace_text(self, page_index: int, rect: Rect, text: str, style: TextStyle) -> Rect:
        raise NotImplementedError

    @abstractmethod
    def add_image(self, page_index: int, rect: Rect, image_path: str | Path) -> None:
        raise NotImplementedError

    @abstractmethod
    def add_annotation(self, page_index: int, annotation: AnnotationSpec) -> None:
        raise NotImplementedError

    @abstractmethod
    def delete_content(self, page_index: int, rect: Rect) -> None:
        raise NotImplementedError

    @abstractmethod
    def move_page(self, old_index: int, new_index: int) -> None:
        raise NotImplementedError

    @abstractmethod
    def delete_pages(self, page_indices: list[int]) -> None:
        raise NotImplementedError

    @abstractmethod
    def insert_pages(
        self,
        source_path: str | Path,
        insert_index: int,
        *,
        password: str | None = None,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def save_document(self, output_path: str | Path) -> None:
        raise NotImplementedError

    @abstractmethod
    def validate_saved_document(self, path: str | Path) -> DocumentValidation:
        raise NotImplementedError

    @abstractmethod
    def document_bytes(self) -> bytes:
        raise NotImplementedError

    @abstractmethod
    def load_bytes(self, data: bytes) -> None:
        raise NotImplementedError
