from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from flowpdf.document_mode.models.assets import ImageAsset
from flowpdf.document_mode.models.blocks import Block, BlockImage, Paragraph


@dataclass(slots=True)
class DocumentMetadata:
    title: str = "未命名文档"
    author: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    modified_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    source_pdf_path: str = ""
    source_pdf_sha256: str = ""


@dataclass(slots=True)
class PageSetup:
    width_pt: float = 595.28
    height_pt: float = 841.89
    margin_top_pt: float = 72.0
    margin_bottom_pt: float = 72.0
    margin_left_pt: float = 72.0
    margin_right_pt: float = 72.0
    page_number_position: str = "none"
    first_page_number_hidden: bool = False

    def __post_init__(self) -> None:
        if self.width_pt <= 0 or self.height_pt <= 0:
            raise ValueError("页面尺寸必须大于零")
        if (
            min(
                self.margin_top_pt,
                self.margin_bottom_pt,
                self.margin_left_pt,
                self.margin_right_pt,
            )
            < 0
        ):
            raise ValueError("页边距不能为负数")
        if self.margin_left_pt + self.margin_right_pt >= self.width_pt:
            raise ValueError("左右页边距超过页面宽度")
        if self.margin_top_pt + self.margin_bottom_pt >= self.height_pt:
            raise ValueError("上下页边距超过页面高度")
        if self.page_number_position not in {"none", "bottom_center", "bottom_right"}:
            raise ValueError("页码位置无效")


@dataclass(slots=True)
class Section:
    blocks: list[Block] = field(default_factory=list)


@dataclass(slots=True)
class FlowDocument:
    metadata: DocumentMetadata = field(default_factory=DocumentMetadata)
    page_setup: PageSetup = field(default_factory=PageSetup)
    sections: list[Section] = field(default_factory=lambda: [Section()])
    headers: list[Paragraph] = field(default_factory=list)
    footers: list[Paragraph] = field(default_factory=list)
    assets: dict[str, ImageAsset] = field(default_factory=dict)

    @classmethod
    def new(cls, *, title: str = "未命名文档") -> FlowDocument:
        return cls(metadata=DocumentMetadata(title=title))

    def append_block(self, block: Block, *, section_index: int = 0) -> None:
        if section_index < 0 or section_index >= len(self.sections):
            raise IndexError("文档节索引超出范围")
        self.sections[section_index].blocks.append(block)
        self.metadata.modified_at = datetime.now(UTC).isoformat()

    def add_asset(self, asset: ImageAsset) -> None:
        if asset.asset_id in self.assets:
            raise ValueError("图片资产标识重复")
        if not asset.data:
            raise ValueError("图片资产内容为空")
        self.assets[asset.asset_id] = asset
        self.metadata.modified_at = datetime.now(UTC).isoformat()

    def normalize(self) -> None:
        if not self.sections:
            self.sections.append(Section())
        for section in self.sections:
            for block in section.blocks:
                if isinstance(block, Paragraph):
                    block.normalize()
                elif isinstance(block, BlockImage) and block.asset_id not in self.assets:
                    raise ValueError(f"图片块引用了不存在的资产：{block.asset_id}")

    @property
    def plain_text(self) -> str:
        paragraphs = [
            block.text
            for section in self.sections
            for block in section.blocks
            if isinstance(block, Paragraph)
        ]
        return "\n".join(paragraphs)
