from __future__ import annotations

import hashlib
import json
import os
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class RecoveryError(RuntimeError):
    """A recovery record could not be read or safely written."""


@dataclass(frozen=True, slots=True)
class RecoveryRecord:
    document_id: str
    source_path: str
    commands: list[dict[str, Any]]
    updated_at: str
    output_path: str | None = None


class RecoveryService:
    """Atomically persist command logs without ever retaining a PDF password."""

    _prefix = "recovery-"
    _secret_keys = frozenset({"password", "passphrase", "pwd", "pdf_password"})

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.root = self.root.resolve(strict=True)

    def write(
        self,
        *,
        document_id: str,
        source_path: str,
        commands: list[dict[str, object]],
        output_path: str | None = None,
    ) -> Path:
        if not document_id:
            raise ValueError("恢复会话缺少文档标识")
        digest = hashlib.sha256(document_id.encode("utf-8")).hexdigest()[:24]
        destination = self.root / f"{self._prefix}{digest}.json"
        temporary = self.root / f".{self._prefix}{digest}.tmp"
        payload = {
            "version": 1,
            "document_id": document_id,
            "source_path": source_path,
            "output_path": output_path,
            "updated_at": datetime.now(UTC).isoformat(),
            "commands": self._sanitize(commands),
        }
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
        except OSError as exc:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)
            raise RecoveryError(f"无法写入恢复记录：{exc}") from exc
        return destination

    def load(self, path: str | Path) -> RecoveryRecord:
        candidate = self._validate_owned_path(path, must_exist=True)
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
            if data.get("version") != 1 or not isinstance(data.get("commands"), list):
                raise ValueError("版本或命令格式无效")
            return RecoveryRecord(
                document_id=str(data["document_id"]),
                source_path=str(data["source_path"]),
                output_path=(str(data["output_path"]) if data.get("output_path") else None),
                updated_at=str(data["updated_at"]),
                commands=list(data["commands"]),
            )
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise RecoveryError(f"恢复记录已损坏或无法读取：{candidate.name}") from exc

    def list_sessions(self) -> list[RecoveryRecord]:
        records: list[RecoveryRecord] = []
        for path in sorted(self.root.glob(f"{self._prefix}*.json")):
            try:
                records.append(self.load(path))
            except RecoveryError:
                continue
        return sorted(records, key=lambda record: record.updated_at, reverse=True)

    def discard(self, path: str | Path) -> bool:
        try:
            candidate = self._validate_owned_path(path, must_exist=True)
            candidate.unlink()
        except (OSError, RecoveryError):
            return False
        return True

    def _validate_owned_path(self, path: str | Path, *, must_exist: bool) -> Path:
        candidate = Path(path)
        if (
            candidate.is_symlink()
            or not candidate.name.startswith(self._prefix)
            or candidate.suffix.casefold() != ".json"
        ):
            raise RecoveryError("恢复记录路径不属于 FlowPDF")
        try:
            resolved = candidate.resolve(strict=must_exist)
        except OSError as exc:
            raise RecoveryError("恢复记录不存在或无法访问") from exc
        if resolved.parent != self.root:
            raise RecoveryError("恢复记录路径超出允许目录")
        return resolved

    @classmethod
    def _sanitize(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                str(key): cls._sanitize(item)
                for key, item in value.items()
                if str(key).casefold() not in cls._secret_keys
            }
        if isinstance(value, list):
            return [cls._sanitize(item) for item in value]
        if isinstance(value, tuple):
            return [cls._sanitize(item) for item in value]
        return value
