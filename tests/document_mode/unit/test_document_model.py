from __future__ import annotations

import json
import zipfile

import pytest

from flowpdf.document_mode.export import ProjectError, ProjectReader, ProjectState, ProjectWriter
from flowpdf.document_mode.models import (
    BlockImage,
    DocumentSerializer,
    FlowDocument,
    ImageAsset,
    PageBreak,
    Paragraph,
    SemanticRole,
    SourceReference,
    TextRun,
    TextStyle,
)


def test_flow_document_normalizes_runs_and_round_trips_chinese_json() -> None:
    style = TextStyle(font_family="Microsoft YaHei", font_size_pt=12)
    source = SourceReference(
        page_index=0,
        bbox=(72.0, 90.0, 320.0, 108.0),
        original_text="你好，FlowPDF",
        original_font="ABCDEE+MicrosoftYaHei",
        confidence=0.96,
    )
    document = FlowDocument.new(title="中文报告")
    document.append_block(
        Paragraph(
            runs=[TextRun("你好", style, source), TextRun("，FlowPDF", style, source)],
            semantic_role=SemanticRole.BODY,
            source_ref=source,
        )
    )

    document.normalize()
    restored = DocumentSerializer.loads(DocumentSerializer.dumps(document))

    paragraph = restored.sections[0].blocks[0]
    assert isinstance(paragraph, Paragraph)
    assert paragraph.text == "你好，FlowPDF"
    assert paragraph.runs == [TextRun("你好，FlowPDF", style, source)]
    assert restored == document


def test_flow_document_serializes_structural_page_break() -> None:
    document = FlowDocument.new()
    document.append_block(Paragraph(runs=[TextRun("分页前")]))
    document.append_block(PageBreak())
    document.append_block(Paragraph(runs=[TextRun("分页后")]))

    restored = DocumentSerializer.loads(DocumentSerializer.dumps(document))

    assert isinstance(restored.sections[0].blocks[1], PageBreak)
    assert restored.plain_text == "分页前\n分页后"


def test_project_round_trip_preserves_document_image_and_view_state(tmp_path) -> None:
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\rIDAT\x08\xd7c\xf8\xcf\xc0\xf0\x1f\x00\x05"
        b"\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    document = FlowDocument.new(title="带图片的工程")
    document.append_block(Paragraph(runs=[TextRun("第一段中文")]))
    asset = ImageAsset.create(png, media_type="image/png", width_px=1, height_px=1)
    document.add_asset(asset)
    document.append_block(
        BlockImage(
            asset_id=asset.asset_id,
            width_pt=144.0,
            height_pt=144.0,
            alignment="center",
            alt_text="蓝色示例图",
        )
    )
    state = ProjectState(
        cursor_position=5,
        selection_anchor=2,
        scroll_y=128,
        zoom_factor=1.25,
        current_page=1,
    )
    output = tmp_path / "中文工程.flowpdfproj"

    ProjectWriter().save(document, output, state=state)
    loaded = ProjectReader().load(output)

    assert loaded.document == document
    assert loaded.document.assets[asset.asset_id].data == png
    assert loaded.state == state


def test_project_reader_converts_malformed_document_fields_to_project_error(tmp_path) -> None:
    output = tmp_path / "损坏工程.flowpdfproj"
    manifest = {
        "format": "FlowPDF Project",
        "format_version": 1,
        "created_with": "FlowPDF",
        "source_pdf_path": "",
        "source_pdf_sha256": "",
        "document_file": "document.json",
        "assets_directory": "assets",
        "state": {},
    }
    malformed = DocumentSerializer.to_dict(FlowDocument.new())
    malformed["assets"] = "not-an-object"
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("document.json", json.dumps(malformed))

    with pytest.raises(ProjectError, match=r"损坏|无效"):
        ProjectReader().load(output)


def test_project_reader_rejects_zip_path_traversal(tmp_path) -> None:
    output = tmp_path / "越界工程.flowpdfproj"
    document_json = DocumentSerializer.dumps(FlowDocument.new())
    manifest = {
        "format": "FlowPDF Project",
        "format_version": 1,
        "created_with": "FlowPDF",
        "source_pdf_path": "",
        "source_pdf_sha256": "",
        "document_file": "document.json",
        "assets_directory": "assets",
        "state": {},
    }
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("document.json", document_json)
        archive.writestr("../outside.txt", "must not escape")

    with pytest.raises(ProjectError, match="路径"):
        ProjectReader().load(output)


def test_project_reader_reports_incompatible_version(tmp_path) -> None:
    output = tmp_path / "未来版本.flowpdfproj"
    manifest = {
        "format": "FlowPDF Project",
        "format_version": 999,
        "created_with": "FlowPDF",
        "source_pdf_path": "",
        "source_pdf_sha256": "",
        "document_file": "document.json",
        "assets_directory": "assets",
        "state": {},
    }
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("document.json", DocumentSerializer.dumps(FlowDocument.new()))

    with pytest.raises(ProjectError, match="版本不兼容"):
        ProjectReader().load(output)


def test_project_reader_reports_incompatible_document_model_version(tmp_path) -> None:
    output = tmp_path / "未来文档模型.flowpdfproj"
    manifest = {
        "format": "FlowPDF Project",
        "format_version": 1,
        "created_with": "FlowPDF",
        "source_pdf_path": "",
        "source_pdf_sha256": "",
        "document_file": "document.json",
        "assets_directory": "assets",
        "state": {},
    }
    document = DocumentSerializer.to_dict(FlowDocument.new())
    document["format_version"] = 999
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("document.json", json.dumps(document))

    with pytest.raises(ProjectError, match="版本不兼容"):
        ProjectReader().load(output)


def test_project_reader_reports_truncated_zip(tmp_path) -> None:
    output = tmp_path / "截断工程.flowpdfproj"
    output.write_bytes(b"PK\x03\x04truncated")

    with pytest.raises(ProjectError, match=r"损坏|无效"):
        ProjectReader().load(output)


def test_project_save_failure_preserves_existing_target(tmp_path, monkeypatch) -> None:
    target = tmp_path / "已有工程.flowpdfproj"
    target.write_bytes(b"existing project")

    def fail_replace(_source, _destination) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr("flowpdf.document_mode.export.project_writer.os.replace", fail_replace)

    with pytest.raises(ProjectError, match="无法安全保存"):
        ProjectWriter().save(FlowDocument.new(), target)

    assert target.read_bytes() == b"existing project"
    assert list(tmp_path.glob(".flowpdf-project-*.tmp")) == []
