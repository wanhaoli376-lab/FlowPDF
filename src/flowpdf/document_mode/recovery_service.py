from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import uuid
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePath

from flowpdf.document_mode.export import ProjectState
from flowpdf.document_mode.models import (
    DocumentFormatError,
    DocumentSerializer,
    FlowDocument,
    ImageAsset,
)

_RECORD_NAME = re.compile(r"document-recovery-[0-9a-f]{24}\.json\.gz")


class DocumentRecoveryError(RuntimeError):
    """A document-mode checkpoint is unsafe, damaged, or unsupported."""


@dataclass(frozen=True, slots=True)
class DocumentRecoveryRecord:
    session_id: str
    document: FlowDocument
    state: ProjectState
    project_path: str
    source_pdf_path: str
    updated_at: str
    unexported: bool
    path: Path


class DocumentRecoveryService:
    """Store compressed model checkpoints and content-addressed assets atomically."""

    MAX_COMPRESSED_BYTES = 96 * 1024 * 1024
    MAX_EXPANDED_BYTES = 256 * 1024 * 1024
    MAX_ASSET_BYTES = 128 * 1024 * 1024

    def __init__(self, root: str | Path) -> None:
        requested = Path(root)
        requested.mkdir(parents=True, exist_ok=True)
        self.root = requested.resolve(strict=True)
        assets = self.root / "assets"
        assets.mkdir(exist_ok=True)
        self.assets_root = assets.resolve(strict=True)
        self._cleanup_temporary_files()

    def write(
        self,
        *,
        session_id: str,
        document: FlowDocument,
        state: ProjectState,
        project_path: str,
        unexported: bool,
    ) -> Path:
        if not session_id:
            raise ValueError("文档恢复会话缺少标识")
        document.normalize()
        asset_files: dict[str, str] = {}
        for asset_id, asset in document.assets.items():
            asset_files[asset_id] = self._store_asset(asset)
        digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:24]
        destination = self.root / f"document-recovery-{digest}.json.gz"
        temporary = self.root / f".{destination.name}.{uuid.uuid4().hex}.tmp"
        payload = {
            "format": "FlowPDF Document Recovery",
            "version": 1,
            "session_id": session_id,
            "project_path": project_path,
            "source_pdf_path": document.metadata.source_pdf_path,
            "updated_at": datetime.now(UTC).isoformat(),
            "unexported": bool(unexported),
            "state": asdict(state),
            "document": DocumentSerializer.to_dict(document),
            "asset_files": asset_files,
        }
        try:
            encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            if len(encoded) > self.MAX_EXPANDED_BYTES:
                raise DocumentRecoveryError("文档恢复模型超过安全大小上限")
            with temporary.open("xb") as raw:
                with gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=6, mtime=0) as stream:
                    stream.write(encoded)
                raw.flush()
                os.fsync(raw.fileno())
            if temporary.stat().st_size > self.MAX_COMPRESSED_BYTES:
                raise DocumentRecoveryError("文档恢复记录超过安全大小上限")
            os.replace(temporary, destination)
        except DocumentRecoveryError:
            raise
        except OSError as exc:
            raise DocumentRecoveryError("无法安全写入文档模式恢复记录") from exc
        finally:
            if temporary.exists() and not temporary.is_symlink():
                with suppress(OSError):
                    temporary.unlink()
        return destination

    def load(self, path: str | Path) -> DocumentRecoveryRecord:
        source = self._validate_record_path(path, must_exist=True)
        try:
            if source.stat().st_size > self.MAX_COMPRESSED_BYTES:
                raise DocumentRecoveryError("文档恢复记录超过安全大小上限")
            with source.open("rb") as raw, gzip.GzipFile(fileobj=raw, mode="rb") as stream:
                encoded = stream.read(self.MAX_EXPANDED_BYTES + 1)
            if len(encoded) > self.MAX_EXPANDED_BYTES:
                raise DocumentRecoveryError("文档恢复记录展开大小超过安全上限")
            value = json.loads(encoded.decode("utf-8"))
            if value.get("format") != "FlowPDF Document Recovery" or value.get("version") != 1:
                raise DocumentRecoveryError("文档恢复记录版本不兼容")
            document = DocumentSerializer.from_dict(value["document"])
            asset_files = value.get("asset_files", {})
            if not isinstance(asset_files, dict):
                raise DocumentRecoveryError("文档恢复资产清单无效")
            for asset_id, asset in tuple(document.assets.items()):
                file_name = asset_files.get(asset_id)
                data = self._load_asset(file_name, asset.sha256)
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
            return DocumentRecoveryRecord(
                session_id=str(value["session_id"]),
                document=document,
                state=ProjectState(**value.get("state", {})),
                project_path=str(value.get("project_path", "")),
                source_pdf_path=str(value.get("source_pdf_path", "")),
                updated_at=str(value["updated_at"]),
                unexported=bool(value.get("unexported", True)),
                path=source,
            )
        except DocumentRecoveryError:
            raise
        except (
            OSError,
            EOFError,
            gzip.BadGzipFile,
            UnicodeError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
            DocumentFormatError,
        ) as exc:
            raise DocumentRecoveryError(f"文档恢复记录已损坏：{source.name}") from exc

    def list_sessions(self) -> list[DocumentRecoveryRecord]:
        return [record for _path, record in self.list_session_files()]

    def list_session_files(self) -> list[tuple[Path, DocumentRecoveryRecord]]:
        records: list[tuple[Path, DocumentRecoveryRecord]] = []
        for path in self.root.glob("document-recovery-*.json.gz"):
            try:
                records.append((path, self.load(path)))
            except DocumentRecoveryError:
                continue
        return sorted(records, key=lambda item: item[1].updated_at, reverse=True)

    def discard(self, path: str | Path) -> bool:
        try:
            record = self._validate_record_path(path, must_exist=True)
            record.unlink()
        except (OSError, DocumentRecoveryError):
            return False
        self._prune_unreferenced_assets()
        return True

    def _store_asset(self, asset: ImageAsset) -> str:
        if not asset.data or len(asset.data) > self.MAX_ASSET_BYTES:
            raise DocumentRecoveryError("文档恢复图片为空或超过安全大小上限")
        if hashlib.sha256(asset.data).hexdigest() != asset.sha256:
            raise DocumentRecoveryError("文档恢复图片校验失败")
        suffix = Path(asset.file_name).suffix.casefold()
        if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
            suffix = ".bin"
        name = f"asset-{asset.sha256}{suffix}"
        destination = self.assets_root / name
        if (
            destination.exists()
            and not destination.is_symlink()
            and hashlib.sha256(destination.read_bytes()).hexdigest() == asset.sha256
        ):
            return name
        temporary = self.assets_root / f".{name}.{uuid.uuid4().hex}.tmp"
        try:
            with temporary.open("xb") as stream:
                stream.write(asset.data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        except OSError as exc:
            raise DocumentRecoveryError("无法写入文档恢复图片资产") from exc
        finally:
            if temporary.exists() and not temporary.is_symlink():
                with suppress(OSError):
                    temporary.unlink()
        return name

    def _load_asset(self, file_name: object, expected_sha256: str) -> bytes:
        if not isinstance(file_name, str) or PurePath(file_name).name != file_name:
            raise DocumentRecoveryError("文档恢复资产路径无效")
        if not file_name.startswith(f"asset-{expected_sha256}"):
            raise DocumentRecoveryError("文档恢复资产名称校验失败")
        source = self.assets_root / file_name
        if source.is_symlink() or not source.is_file():
            raise DocumentRecoveryError("文档恢复资产缺失")
        if source.stat().st_size > self.MAX_ASSET_BYTES:
            raise DocumentRecoveryError("文档恢复资产超过安全大小上限")
        data = source.read_bytes()
        if hashlib.sha256(data).hexdigest() != expected_sha256:
            raise DocumentRecoveryError("文档恢复资产内容校验失败")
        return data

    def _validate_record_path(self, path: str | Path, *, must_exist: bool) -> Path:
        candidate = Path(path)
        if candidate.is_symlink() or _RECORD_NAME.fullmatch(candidate.name) is None:
            raise DocumentRecoveryError("恢复记录路径不属于 FlowPDF")
        try:
            resolved = candidate.resolve(strict=must_exist)
        except OSError as exc:
            raise DocumentRecoveryError("文档恢复记录不存在") from exc
        if resolved.parent != self.root:
            raise DocumentRecoveryError("恢复记录路径不属于 FlowPDF")
        return resolved

    def _prune_unreferenced_assets(self) -> None:
        referenced_hashes: set[str] = set()
        for path in self.root.glob("document-recovery-*.json.gz"):
            try:
                record = self.load(path)
            except DocumentRecoveryError:
                continue
            referenced_hashes.update(asset.sha256 for asset in record.document.assets.values())
        for candidate in self.assets_root.glob("asset-*"):
            digest = candidate.name.removeprefix("asset-")[:64]
            if (
                digest not in referenced_hashes
                and candidate.is_file()
                and not candidate.is_symlink()
            ):
                with suppress(OSError):
                    candidate.unlink()

    def _cleanup_temporary_files(self) -> None:
        for root in (self.root, self.assets_root):
            for candidate in root.glob(".*.tmp"):
                if candidate.is_file() and not candidate.is_symlink():
                    with suppress(OSError):
                        candidate.unlink()
