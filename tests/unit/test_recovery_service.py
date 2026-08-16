from __future__ import annotations

import json

from flowpdf.services.recovery_service import RecoveryService


def test_recovery_log_round_trips_commands_without_passwords(tmp_path) -> None:
    service = RecoveryService(tmp_path / "恢复")
    commands = [
        {
            "type": "replace_text",
            "page": 2,
            "old_text": "2025",
            "new_text": "2026",
            "password": "never-write-me",
            "options": {"passphrase": "also-secret", "strategy": "wrap"},
        }
    ]

    path = service.write(
        document_id="中文-document-id",
        source_path="D:/文档/年度报告.pdf",
        commands=commands,
    )
    raw = path.read_text(encoding="utf-8")
    recovered = service.load(path)

    assert "never-write-me" not in raw
    assert "also-secret" not in raw
    assert recovered.document_id == "中文-document-id"
    assert recovered.source_path == "D:/文档/年度报告.pdf"
    assert recovered.commands[0]["new_text"] == "2026"
    assert "password" not in recovered.commands[0]
    assert "passphrase" not in recovered.commands[0]["options"]


def test_listing_skips_corrupt_logs_and_discard_is_scoped(tmp_path) -> None:
    service = RecoveryService(tmp_path)
    valid = service.write(document_id="valid", source_path="a.pdf", commands=[])
    (tmp_path / "recovery-corrupt.json").write_text("{", encoding="utf-8")
    unrelated = tmp_path / "notes.json"
    unrelated.write_text(json.dumps({"keep": True}), encoding="utf-8")

    sessions = service.list_sessions()
    session_files = service.list_session_files()

    assert [session.document_id for session in sessions] == ["valid"]
    assert session_files[0][0] == valid
    assert session_files[0][1].document_id == "valid"
    assert service.discard(valid) is True
    assert service.discard(unrelated) is False
    assert unrelated.exists()
