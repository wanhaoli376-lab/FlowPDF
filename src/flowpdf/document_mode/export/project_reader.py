from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from flowpdf.document_mode.export.project_format import (
    ProjectBundle,
    ProjectError,
    ProjectManifest,
    ProjectState,
)
from flowpdf.document_mode.models import DocumentFormatError, DocumentSerializer, ImageAsset


class ProjectReader:
    MAX_PROJECT_BYTES = 256 * 1024 * 1024
    MAX_EXPANDED_BYTES = 512 * 1024 * 1024
    MAX_ENTRIES = 10_000
    MAX_COMPRESSION_RATIO = 200

    def load(self, path: str | Path) -> ProjectBundle:
        source = Path(path)
        try:
            size = source.stat().st_size
        except OSError as exc:
            raise ProjectError("FlowPDF 工程不存在或无法读取") from exc
        if size <= 0 or size > self.MAX_PROJECT_BYTES:
            raise ProjectError("FlowPDF 工程为空或超过安全大小上限")
        try:
            with zipfile.ZipFile(source, "r") as archive:
                members = self._validated_members(archive)
                manifest = self._read_manifest(archive, members)
                document_payload = self._read_member(archive, members[manifest.document_file])
                document = DocumentSerializer.loads(document_payload.decode("utf-8"))
                for asset_id, asset in tuple(document.assets.items()):
                    member_name = f"{manifest.assets_directory}/{asset.file_name}"
                    info = members.get(member_name)
                    if info is None:
                        raise ProjectError(f"工程缺少图片资产：{asset.file_name}")
                    data = self._read_member(archive, info)
                    if hashlib.sha256(data).hexdigest() != asset.sha256:
                        raise ProjectError(f"图片资产校验失败：{asset.file_name}")
                    document.assets[asset_id] = ImageAsset(
                        asset_id=asset.asset_id,
                        media_type=asset.media_type,
                        width_px=asset.width_px,
                        height_px=asset.height_px,
                        file_name=asset.file_name,
                        sha256=asset.sha256,
                        data=data,
                    )
                document.normalize()
                return ProjectBundle(document, manifest.state, manifest)
        except ProjectError:
            raise
        except (OSError, UnicodeError, ValueError, KeyError, zipfile.BadZipFile) as exc:
            raise ProjectError("FlowPDF 工程已损坏或格式无效") from exc
        except DocumentFormatError as exc:
            raise ProjectError(str(exc)) from exc

    def _validated_members(self, archive: zipfile.ZipFile) -> dict[str, zipfile.ZipInfo]:
        infos = archive.infolist()
        if len(infos) > self.MAX_ENTRIES:
            raise ProjectError("工程包含过多文件")
        members: dict[str, zipfile.ZipInfo] = {}
        expanded = 0
        for info in infos:
            name = self._validated_name(info.filename)
            if name in members:
                raise ProjectError("工程包含重复路径")
            unix_mode = info.external_attr >> 16
            if stat.S_ISLNK(unix_mode):
                raise ProjectError("工程不能包含符号链接")
            expanded += info.file_size
            if expanded > self.MAX_EXPANDED_BYTES:
                raise ProjectError("工程展开大小超过安全上限")
            if (
                info.file_size > 1_048_576
                and info.compress_size > 0
                and info.file_size / info.compress_size > self.MAX_COMPRESSION_RATIO
            ):
                raise ProjectError("工程压缩比例异常")
            members[name] = info
        if "manifest.json" not in members or "document.json" not in members:
            raise ProjectError("工程缺少 manifest.json 或 document.json")
        return members

    @staticmethod
    def _validated_name(name: str) -> str:
        if "\\" in name:
            raise ProjectError("工程 ZIP 路径格式无效")
        candidate = PurePosixPath(name)
        if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
            raise ProjectError("工程 ZIP 路径越界")
        normalized = candidate.as_posix()
        if normalized != name or ":" in candidate.parts[0]:
            raise ProjectError("工程 ZIP 路径格式无效")
        return normalized

    @classmethod
    def _read_member(cls, archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> bytes:
        if info.file_size > cls.MAX_EXPANDED_BYTES:
            raise ProjectError("工程成员超过安全大小上限")
        with archive.open(info, "r") as stream:
            data = stream.read(info.file_size + 1)
        if len(data) != info.file_size:
            raise ProjectError("工程成员长度校验失败")
        return data

    def _read_manifest(
        self,
        archive: zipfile.ZipFile,
        members: dict[str, zipfile.ZipInfo],
    ) -> ProjectManifest:
        try:
            value = json.loads(self._read_member(archive, members["manifest.json"]))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ProjectError("工程清单已损坏") from exc
        if not isinstance(value, dict):
            raise ProjectError("工程清单格式无效")
        if value.get("format") != "FlowPDF Project":
            raise ProjectError("不是 FlowPDF 工程文件")
        if value.get("format_version") != 1:
            raise ProjectError("FlowPDF 工程版本不兼容")
        try:
            state = ProjectState(**value.get("state", {}))
            manifest_data: dict[str, Any] = dict(value)
            manifest_data["state"] = state
            manifest = ProjectManifest(**manifest_data)
        except (TypeError, ValueError) as exc:
            raise ProjectError("工程清单字段无效") from exc
        if manifest.document_file != "document.json" or manifest.assets_directory != "assets":
            raise ProjectError("工程清单路径不受支持")
        return manifest
