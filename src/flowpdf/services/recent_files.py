from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings


class RecentFiles:
    def __init__(self, settings: QSettings, *, limit: int = 10) -> None:
        if limit <= 0:
            raise ValueError("最近文件数量必须大于 0")
        self.settings = settings
        self.limit = limit

    def add(self, path: str | Path) -> None:
        resolved = Path(path).resolve(strict=False)
        paths = [item for item in self._stored_paths() if not _same_path(item, resolved)]
        paths.insert(0, resolved)
        self._write(paths[: self.limit])

    def paths(self) -> list[Path]:
        existing = [path for path in self._stored_paths() if path.is_file()]
        self._write(existing[: self.limit])
        return existing[: self.limit]

    def clear(self) -> None:
        self.settings.remove("recent/files")
        self.settings.sync()

    def _stored_paths(self) -> list[Path]:
        value = self.settings.value("recent/files", [])
        if value is None:
            return []
        if isinstance(value, str):
            value = [value]
        return [Path(str(item)) for item in value]

    def _write(self, paths: list[Path]) -> None:
        self.settings.setValue("recent/files", [str(path) for path in paths])
        self.settings.sync()


def _same_path(left: Path, right: Path) -> bool:
    return str(left.resolve(strict=False)).casefold() == str(right.resolve(strict=False)).casefold()
