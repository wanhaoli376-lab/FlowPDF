from __future__ import annotations

import json
import os
import re
from contextlib import suppress
from pathlib import Path
from threading import RLock

_SAVE_ARTIFACT = re.compile(r"\.flowpdf-(?:save|export)-[0-9a-f]{32}\.tmp\.pdf")


class SaveArtifactRegistry:
    """Remember exact PDF artifacts so a later launch can clean them."""

    def __init__(self, registry_path: str | Path) -> None:
        requested = Path(registry_path)
        requested.parent.mkdir(parents=True, exist_ok=True)
        root = requested.parent.resolve(strict=True)
        self.path = root / requested.name
        self._lock = RLock()

    def register(self, artifact: str | Path) -> None:
        candidate = self._validated_candidate(artifact)
        with self._lock:
            paths = self._read()
            paths.add(str(candidate))
            self._write(paths)

    def unregister(self, artifact: str | Path) -> None:
        candidate = self._validated_candidate(artifact)
        with self._lock:
            paths = self._read()
            paths.discard(str(candidate))
            self._write(paths)

    def cleanup(self) -> list[Path]:
        removed: list[Path] = []
        with self._lock:
            remaining: set[str] = set()
            for raw in self._read():
                try:
                    candidate = self._validated_candidate(raw)
                except ValueError:
                    continue
                if not candidate.exists():
                    continue
                if candidate.is_symlink() or not candidate.is_file():
                    remaining.add(str(candidate))
                    continue
                try:
                    candidate.unlink()
                except OSError:
                    remaining.add(str(candidate))
                else:
                    removed.append(candidate)
            self._write(remaining)
        return removed

    def _validated_candidate(self, artifact: str | Path) -> Path:
        candidate = Path(artifact)
        if _SAVE_ARTIFACT.fullmatch(candidate.name) is None:
            raise ValueError("不是 FlowPDF 已知的 PDF 临时文件")
        try:
            parent = candidate.parent.resolve(strict=True)
        except OSError as exc:
            raise ValueError("临时文件目录不存在") from exc
        return parent / candidate.name

    def _read(self) -> set[str]:
        if not self.path.exists() or self.path.is_symlink():
            return set()
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return set()
        if not isinstance(value, list):
            return set()
        return {item for item in value if isinstance(item, str)}

    def _write(self, paths: set[str]) -> None:
        temporary = self.path.with_name(f".{self.path.name}.tmp")
        payload = json.dumps(sorted(paths), ensure_ascii=False, indent=2)
        try:
            temporary.write_text(payload, encoding="utf-8")
            os.replace(temporary, self.path)
        except OSError:
            if temporary.exists() and not temporary.is_symlink():
                with suppress(OSError):
                    temporary.unlink()
            raise
