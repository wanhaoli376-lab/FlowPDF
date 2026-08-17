from __future__ import annotations

import io

import pytest
from PIL import Image

from flowpdf.document_mode.export import ProjectState
from flowpdf.document_mode.models import BlockImage, FlowDocument, ImageAsset, Paragraph, TextRun
from flowpdf.document_mode.recovery_service import (
    DocumentRecoveryError,
    DocumentRecoveryService,
)


def _recoverable_document() -> FlowDocument:
    document = FlowDocument.new(title="恢复中的中文工程")
    document.metadata.source_pdf_path = "D:/文档/来源.pdf"
    document.append_block(Paragraph(runs=[TextRun("未保存的中文修改")]))
    image = Image.new("RGB", (24, 12), "#0ea5e9")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    asset = ImageAsset.create(
        buffer.getvalue(),
        media_type="image/png",
        width_px=24,
        height_px=12,
    )
    document.add_asset(asset)
    document.append_block(BlockImage(asset.asset_id, 72, 36, alt_text="恢复图片"))
    return document


def test_document_recovery_round_trips_model_assets_and_view_state(tmp_path) -> None:
    service = DocumentRecoveryService(tmp_path / "recovery")
    document = _recoverable_document()
    state = ProjectState(cursor_position=5, selection_anchor=2, scroll_y=88, current_page=1)

    path = service.write(
        session_id="文档-session",
        document=document,
        state=state,
        project_path="D:/工程/报告.flowpdfproj",
        unexported=True,
    )
    recovered = service.load(path)

    assert recovered.document.plain_text == document.plain_text
    assert next(iter(recovered.document.assets.values())).data
    assert recovered.state == state
    assert recovered.project_path.endswith("报告.flowpdfproj")
    assert recovered.unexported is True
    assert service.list_sessions()[0].session_id == "文档-session"
    assert service.discard(path)
    assert service.list_sessions() == []


def test_document_recovery_rejects_corrupt_and_out_of_scope_records(tmp_path) -> None:
    service = DocumentRecoveryService(tmp_path / "recovery")
    corrupt = service.root / "document-recovery-000000000000000000000000.json.gz"
    corrupt.write_bytes(b"not gzip")
    outside = tmp_path / "document-recovery-111111111111111111111111.json.gz"
    outside.write_bytes(b"outside")

    assert service.list_sessions() == []
    with pytest.raises(DocumentRecoveryError, match="不属于 FlowPDF"):
        service.load(outside)


def test_document_recovery_never_serializes_password_fields(tmp_path) -> None:
    service = DocumentRecoveryService(tmp_path)
    document = _recoverable_document()
    document.metadata.author = "password=should-not-be-treated-as-a-secret-field"

    path = service.write(
        session_id="safe",
        document=document,
        state=ProjectState(),
        project_path="",
        unexported=False,
    )

    raw = path.read_bytes()
    assert b"pdf_password" not in raw
    assert b"passphrase" not in raw
