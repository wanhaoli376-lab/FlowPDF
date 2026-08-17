from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from flowpdf.document_mode.models.source_reference import SourceReference
from flowpdf.document_mode.models.styles import ParagraphStyle, TextStyle


class SemanticRole(StrEnum):
    TITLE = "title"
    HEADING1 = "heading1"
    HEADING2 = "heading2"
    HEADING3 = "heading3"
    BODY = "body"
    CAPTION = "caption"
    QUOTE = "quote"
    LIST_ITEM = "list_item"
    HEADER = "header"
    FOOTER = "footer"
    PAGE_NUMBER = "page_number"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class TextRun:
    text: str
    style: TextStyle = field(default_factory=TextStyle)
    source_ref: SourceReference | None = None


@dataclass(slots=True)
class Paragraph:
    runs: list[TextRun] = field(default_factory=list)
    style: ParagraphStyle = field(default_factory=ParagraphStyle)
    semantic_role: SemanticRole = SemanticRole.BODY
    source_ref: SourceReference | None = None

    @property
    def text(self) -> str:
        return "".join(run.text for run in self.runs)

    def normalize(self) -> None:
        merged: list[TextRun] = []
        for run in self.runs:
            if not run.text:
                continue
            if merged and merged[-1].style == run.style and merged[-1].source_ref == run.source_ref:
                merged[-1].text += run.text
            else:
                merged.append(TextRun(run.text, run.style, run.source_ref))
        self.runs = merged


@dataclass(slots=True)
class BlockImage:
    asset_id: str
    width_pt: float
    height_pt: float
    alignment: str = "center"
    inline: bool = False
    alt_text: str = ""
    source_ref: SourceReference | None = None

    def __post_init__(self) -> None:
        if not self.asset_id:
            raise ValueError("图片块缺少资产标识")
        if self.width_pt <= 0 or self.height_pt <= 0:
            raise ValueError("图片显示尺寸必须大于零")
        if self.alignment not in {"left", "center", "right"}:
            raise ValueError("图片对齐方式无效")


@dataclass(frozen=True, slots=True)
class PageBreak:
    """A user-authored hard page break in the reflowable document."""


Block = Paragraph | BlockImage | PageBreak
