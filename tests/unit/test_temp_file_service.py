from __future__ import annotations

import os
import time

from flowpdf.services.temp_file_service import TempFileService


def test_cleanup_removes_only_old_flowpdf_temporary_files(tmp_path) -> None:
    service = TempFileService(tmp_path)
    stale = service.create(suffix=".pdf")
    active = service.create(suffix=".pdf")
    unrelated = tmp_path / "keep-me.pdf"
    unrelated.write_bytes(b"user")
    old = time.time() - 7200
    os.utime(stale, (old, old))

    removed = service.cleanup(older_than_seconds=3600, keep={active})

    assert removed == [stale]
    assert not stale.exists()
    assert active.exists()
    assert unrelated.read_bytes() == b"user"


def test_create_uses_unicode_safe_workspace_and_unique_names(tmp_path) -> None:
    root = tmp_path / "缓存目录"
    service = TempFileService(root)

    first = service.create(suffix=".pdf")
    second = service.create(suffix=".pdf")

    assert first.parent == root
    assert first != second
    assert first.exists() and second.exists()
