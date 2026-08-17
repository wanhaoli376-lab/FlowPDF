from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from flowpdf.document_mode.models.assets import ImageAsset
from flowpdf.document_mode.models.blocks import BlockImage, Paragraph, SemanticRole, TextRun
from flowpdf.document_mode.models.document import (
    DocumentMetadata,
    FlowDocument,
    PageSetup,
    Section,
)
from flowpdf.document_mode.models.source_reference import SourceReference
from flowpdf.document_mode.models.styles import (
    ParagraphAlignment,
    ParagraphStyle,
    TextStyle,
)


class DocumentFormatError(ValueError):
    """Serialized FlowDocument data is unsupported or malformed."""


class DocumentSerializer:
    FORMAT_VERSION = 1
    MAX_JSON_BYTES = 64 * 1024 * 1024

    @classmethod
    def dumps(cls, document: FlowDocument) -> str:
        document.normalize()
        return json.dumps(cls.to_dict(document), ensure_ascii=False, indent=2, sort_keys=True)

    @classmethod
    def loads(cls, payload: str) -> FlowDocument:
        if len(payload.encode("utf-8")) > cls.MAX_JSON_BYTES:
            raise DocumentFormatError("文档模型超过安全大小上限")
        try:
            value = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise DocumentFormatError("文档模型 JSON 已损坏") from exc
        if not isinstance(value, dict):
            raise DocumentFormatError("文档模型根节点必须是对象")
        return cls.from_dict(value)

    @classmethod
    def to_dict(cls, document: FlowDocument) -> dict[str, Any]:
        return {
            "format": "FlowDocument",
            "format_version": cls.FORMAT_VERSION,
            "metadata": asdict(document.metadata),
            "page_setup": asdict(document.page_setup),
            "sections": [
                {"blocks": [cls._block_to_dict(block) for block in section.blocks]}
                for section in document.sections
            ],
            "headers": [cls._block_to_dict(block) for block in document.headers],
            "footers": [cls._block_to_dict(block) for block in document.footers],
            "assets": {
                asset_id: {
                    "asset_id": asset.asset_id,
                    "media_type": asset.media_type,
                    "width_px": asset.width_px,
                    "height_px": asset.height_px,
                    "file_name": asset.file_name,
                    "sha256": asset.sha256,
                }
                for asset_id, asset in sorted(document.assets.items())
            },
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> FlowDocument:
        if value.get("format") != "FlowDocument":
            raise DocumentFormatError("不是 FlowDocument 文档模型")
        if value.get("format_version") != cls.FORMAT_VERSION:
            raise DocumentFormatError("文档模型版本不兼容")
        assets_value = value.get("assets", {})
        if not isinstance(assets_value, dict):
            raise DocumentFormatError("文档模型图片资产字段无效")
        try:
            document = FlowDocument(
                metadata=DocumentMetadata(**value["metadata"]),
                page_setup=PageSetup(**value["page_setup"]),
                sections=[
                    Section(blocks=[cls._block_from_dict(item) for item in section["blocks"]])
                    for section in value["sections"]
                ],
                headers=[cls._paragraph_from_dict(item) for item in value.get("headers", [])],
                footers=[cls._paragraph_from_dict(item) for item in value.get("footers", [])],
                assets={
                    asset_id: ImageAsset(data=b"", **asset)
                    for asset_id, asset in assets_value.items()
                },
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise DocumentFormatError("文档模型字段无效") from exc
        document.normalize()
        return document

    @classmethod
    def _block_to_dict(cls, block: Paragraph | BlockImage) -> dict[str, Any]:
        if isinstance(block, Paragraph):
            return {
                "type": "paragraph",
                "runs": [
                    {
                        "text": run.text,
                        "style": asdict(run.style),
                        "source_ref": cls._source_to_dict(run.source_ref),
                    }
                    for run in block.runs
                ],
                "style": asdict(block.style),
                "semantic_role": block.semantic_role.value,
                "source_ref": cls._source_to_dict(block.source_ref),
            }
        if isinstance(block, BlockImage):
            return {
                "type": "image",
                "asset_id": block.asset_id,
                "width_pt": block.width_pt,
                "height_pt": block.height_pt,
                "alignment": block.alignment,
                "inline": block.inline,
                "alt_text": block.alt_text,
                "source_ref": cls._source_to_dict(block.source_ref),
            }
        raise DocumentFormatError(f"暂不支持序列化块类型：{type(block).__name__}")

    @classmethod
    def _block_from_dict(cls, value: dict[str, Any]) -> Paragraph | BlockImage:
        if value.get("type") == "paragraph":
            return cls._paragraph_from_dict(value)
        if value.get("type") == "image":
            return BlockImage(
                asset_id=str(value["asset_id"]),
                width_pt=float(value["width_pt"]),
                height_pt=float(value["height_pt"]),
                alignment=str(value.get("alignment", "center")),
                inline=bool(value.get("inline", False)),
                alt_text=str(value.get("alt_text", "")),
                source_ref=cls._source_from_dict(value.get("source_ref")),
            )
        raise DocumentFormatError("文档包含不受支持的块类型")

    @classmethod
    def _paragraph_from_dict(cls, value: dict[str, Any]) -> Paragraph:
        style_value = dict(value["style"])
        style_value["alignment"] = ParagraphAlignment(style_value["alignment"])
        return Paragraph(
            runs=[
                TextRun(
                    text=str(run["text"]),
                    style=TextStyle(**run["style"]),
                    source_ref=cls._source_from_dict(run.get("source_ref")),
                )
                for run in value["runs"]
            ],
            style=ParagraphStyle(**style_value),
            semantic_role=SemanticRole(value["semantic_role"]),
            source_ref=cls._source_from_dict(value.get("source_ref")),
        )

    @staticmethod
    def _source_to_dict(source: SourceReference | None) -> dict[str, Any] | None:
        return asdict(source) if source is not None else None

    @staticmethod
    def _source_from_dict(value: Any) -> SourceReference | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise DocumentFormatError("来源映射格式无效")
        data = dict(value)
        data["bbox"] = tuple(data["bbox"])
        return SourceReference(**data)
