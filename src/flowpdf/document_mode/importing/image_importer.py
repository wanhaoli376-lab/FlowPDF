from __future__ import annotations

import io
import warnings
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError

from flowpdf.document_mode.importing.extracted import ExtractedImage, ExtractedPage
from flowpdf.document_mode.models import (
    BlockImage,
    FlowDocument,
    ImageAsset,
    Paragraph,
    SemanticRole,
    SourceReference,
)

_MEDIA_TYPES = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp"}


@dataclass(frozen=True, slots=True)
class ImageImportResult:
    blocks: list[Paragraph | BlockImage]
    warnings: list[str]


def import_images_in_reading_order(
    document: FlowDocument,
    pages: list[ExtractedPage],
    paragraphs: list[Paragraph],
    *,
    max_image_bytes: int,
    max_image_pixels: int,
) -> ImageImportResult:
    positioned: list[tuple[int, float, int, Paragraph | BlockImage]] = []
    warnings_out: list[str] = []
    for paragraph in paragraphs:
        source = paragraph.source_ref
        if source is not None:
            positioned.append((source.page_index, source.bbox[1], 0, paragraph))
    for page in pages:
        for image in page.images:
            try:
                block = _image_block(
                    document,
                    image,
                    max_image_bytes=max_image_bytes,
                    max_image_pixels=max_image_pixels,
                )
            except ValueError as exc:
                warnings_out.append(f"第 {image.page_index + 1} 页图片未导入：{exc}")
                continue
            positioned.append((image.page_index, image.bbox[1], 1, block))
    positioned.sort(key=lambda item: (item[0], item[1], item[2]))
    blocks = [item[3] for item in positioned]
    _mark_captions(blocks)
    return ImageImportResult(blocks, warnings_out)


def _image_block(
    document: FlowDocument,
    image: ExtractedImage,
    *,
    max_image_bytes: int,
    max_image_pixels: int,
) -> BlockImage:
    if len(image.data) > max_image_bytes:
        raise ValueError("图片文件超过安全大小上限")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(image.data)) as decoded:
                width, height = decoded.size
                decoded.verify()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("图片解码资源异常") from exc
    except (OSError, UnidentifiedImageError) as exc:
        raise ValueError("图片内容损坏或格式不受支持") from exc
    if width <= 0 or height <= 0 or width * height > max_image_pixels:
        raise ValueError("图片像素数量超过安全上限")
    media_type = _MEDIA_TYPES[image.extension]
    asset = ImageAsset.create(
        image.data,
        media_type=media_type,
        width_px=width,
        height_px=height,
    )
    document.add_asset(asset)
    width_pt = max(1.0, image.bbox[2] - image.bbox[0])
    height_pt = max(1.0, image.bbox[3] - image.bbox[1])
    return BlockImage(
        asset_id=asset.asset_id,
        width_pt=width_pt,
        height_pt=height_pt,
        alignment="center",
        source_ref=SourceReference(
            page_index=image.page_index,
            bbox=image.bbox,
            original_text=None,
            original_font=None,
            confidence=0.95,
        ),
    )


def _mark_captions(blocks: list[Paragraph | BlockImage]) -> None:
    for index, block in enumerate(blocks[:-1]):
        following = blocks[index + 1]
        if not isinstance(block, BlockImage) or not isinstance(following, Paragraph):
            continue
        image_source = block.source_ref
        text_source = following.source_ref
        if image_source is None or text_source is None:
            continue
        same_page = image_source.page_index == text_source.page_index
        gap = text_source.bbox[1] - image_source.bbox[3]
        if same_page and -2.0 <= gap <= 48.0 and len(following.text.strip()) <= 120:
            following.semantic_role = SemanticRole.CAPTION
            block.alt_text = following.text.strip()
