from __future__ import annotations

import json

from flowpdf.services.save_artifact_registry import SaveArtifactRegistry


def test_registry_cleans_only_exact_recorded_flowpdf_pdf_artifacts(tmp_path) -> None:
    registry = SaveArtifactRegistry(tmp_path / "app-data" / "pending-saves.json")
    output_dir = tmp_path / "documents"
    output_dir.mkdir()
    artifact = output_dir / ".flowpdf-save-0123456789abcdef0123456789abcdef.tmp.pdf"
    export_artifact = output_dir / ".flowpdf-export-fedcba9876543210fedcba9876543210.tmp.pdf"
    unrelated = output_dir / "important.pdf"
    artifact.write_bytes(b"partial")
    export_artifact.write_bytes(b"exported pages")
    unrelated.write_bytes(b"keep")
    registry.register(artifact)
    registry.register(export_artifact)

    restored = SaveArtifactRegistry(registry.path)
    assert set(restored.cleanup()) == {artifact, export_artifact}
    assert not artifact.exists()
    assert not export_artifact.exists()
    assert unrelated.read_bytes() == b"keep"
    assert json.loads(registry.path.read_text(encoding="utf-8")) == []
