from __future__ import annotations

from flowpdf.utils.paths import suggest_edited_copy


def test_suggested_copy_preserves_chinese_name_and_avoids_existing_files(tmp_path) -> None:
    source = tmp_path / "年度报告.PDF"
    source.write_bytes(b"source")
    first = tmp_path / "年度报告_已修改.pdf"
    first.write_bytes(b"existing")

    suggestion = suggest_edited_copy(source)

    assert suggestion == tmp_path / "年度报告_已修改 (2).pdf"
    assert source.read_bytes() == b"source"


def test_suggested_copy_does_not_treat_source_as_available_target(tmp_path) -> None:
    source = tmp_path / "document.pdf"

    assert suggest_edited_copy(source) == tmp_path / "document_已修改.pdf"
