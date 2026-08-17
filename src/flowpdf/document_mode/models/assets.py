from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass

_ASSET_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_EXTENSIONS = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/webp": "webp",
}


@dataclass(slots=True)
class ImageAsset:
    asset_id: str
    media_type: str
    width_px: int
    height_px: int
    file_name: str
    sha256: str
    data: bytes

    @classmethod
    def create(
        cls,
        data: bytes,
        *,
        media_type: str,
        width_px: int,
        height_px: int,
        asset_id: str | None = None,
    ) -> ImageAsset:
        identifier = asset_id or uuid.uuid4().hex
        extension = _EXTENSIONS.get(media_type)
        if extension is None:
            raise ValueError("工程仅支持 PNG、JPEG 和 WEBP 图片资产")
        return cls(
            asset_id=identifier,
            media_type=media_type,
            width_px=width_px,
            height_px=height_px,
            file_name=f"{identifier}.{extension}",
            sha256=hashlib.sha256(data).hexdigest(),
            data=bytes(data),
        )

    def __post_init__(self) -> None:
        if _ASSET_ID.fullmatch(self.asset_id) is None:
            raise ValueError("图片资产标识无效")
        if self.media_type not in _EXTENSIONS:
            raise ValueError("图片资产格式不受支持")
        expected_name = f"{self.asset_id}.{_EXTENSIONS[self.media_type]}"
        if self.file_name != expected_name:
            raise ValueError("图片资产文件名无效")
        if self.width_px <= 0 or self.height_px <= 0:
            raise ValueError("图片像素尺寸必须大于零")
        if len(self.sha256) != 64:
            raise ValueError("图片资产摘要无效")
        if self.data and hashlib.sha256(self.data).hexdigest() != self.sha256:
            raise ValueError("图片资产内容与摘要不一致")
