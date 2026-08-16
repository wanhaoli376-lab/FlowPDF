from __future__ import annotations

import time
import uuid
from pathlib import Path


class TempFileService:
    """Own and clean only FlowPDF-namespaced temporary files in one root."""

    _prefix = "flowpdf-"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.root = self.root.resolve(strict=True)

    def create(self, *, suffix: str = ".tmp") -> Path:
        if not suffix.startswith(".") or any(char in suffix for char in ("/", "\\")):
            raise ValueError("临时文件扩展名无效")
        for _ in range(10):
            candidate = self.root / f"{self._prefix}{uuid.uuid4().hex}{suffix}"
            try:
                candidate.touch(exist_ok=False)
                return candidate
            except FileExistsError:
                continue
        raise OSError("无法创建唯一的临时文件")

    def cleanup(
        self,
        *,
        older_than_seconds: float = 24 * 60 * 60,
        keep: set[Path] | None = None,
    ) -> list[Path]:
        if older_than_seconds < 0:
            raise ValueError("临时文件保留时间不能为负数")
        keep_paths = {path.resolve(strict=False) for path in (keep or set())}
        cutoff = time.time() - older_than_seconds
        removed: list[Path] = []
        for candidate in self.root.iterdir():
            if not candidate.name.startswith(self._prefix):
                continue
            if candidate.is_symlink() or not candidate.is_file():
                continue
            resolved = candidate.resolve(strict=True)
            if resolved.parent != self.root or resolved in keep_paths:
                continue
            try:
                if candidate.stat().st_mtime <= cutoff:
                    candidate.unlink()
                    removed.append(candidate)
            except OSError:
                # Locked files are intentionally left alone; callers can report
                # them on the next cleanup run without escalating deletion.
                continue
        return removed

    def discard(self, path: str | Path) -> bool:
        candidate = Path(path)
        if candidate.is_symlink() or not candidate.name.startswith(self._prefix):
            return False
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            return False
        if resolved.parent != self.root or not candidate.is_file():
            return False
        try:
            candidate.unlink()
        except OSError:
            return False
        return True
