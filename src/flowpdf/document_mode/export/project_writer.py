from __future__ import annotations

import json
import os
import uuid
import zipfile
from contextlib import suppress
from dataclasses import asdict
from pathlib import Path

from flowpdf.document_mode.export.project_format import ProjectError, ProjectManifest, ProjectState
from flowpdf.document_mode.export.project_reader import ProjectReader
from flowpdf.document_mode.models import DocumentSerializer, FlowDocument


class ProjectWriter:
    def save(
        self,
        document: FlowDocument,
        output_path: str | Path,
        *,
        state: ProjectState | None = None,
    ) -> Path:
        target = Path(output_path)
        if target.suffix.casefold() != ".flowpdfproj":
            target = target.with_suffix(".flowpdfproj")
        if not target.parent.is_dir():
            raise ProjectError("工程保存目录不存在")
        if target.is_symlink():
            raise ProjectError("为保护数据，不能保存到符号链接目标")
        document.normalize()
        manifest = ProjectManifest(
            source_pdf_path=document.metadata.source_pdf_path,
            source_pdf_sha256=document.metadata.source_pdf_sha256,
            state=state or ProjectState(),
        )
        temporary = target.parent / f".flowpdf-project-{uuid.uuid4().hex}.tmp"
        try:
            with zipfile.ZipFile(
                temporary,
                "x",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=6,
                allowZip64=True,
            ) as archive:
                archive.writestr(
                    "manifest.json",
                    json.dumps(asdict(manifest), ensure_ascii=False, indent=2, sort_keys=True),
                )
                archive.writestr("document.json", DocumentSerializer.dumps(document))
                for asset in document.assets.values():
                    if not asset.data:
                        raise ProjectError(f"图片资产内容为空：{asset.file_name}")
                    archive.writestr(f"assets/{asset.file_name}", asset.data)
            with temporary.open("r+b") as stream:
                os.fsync(stream.fileno())
            ProjectReader().load(temporary)
            os.replace(temporary, target)
        except ProjectError:
            raise
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            raise ProjectError(f"无法安全保存 FlowPDF 工程：{target.name}") from exc
        finally:
            if temporary.exists() and not temporary.is_symlink():
                with suppress(OSError):
                    temporary.unlink()
        return target
