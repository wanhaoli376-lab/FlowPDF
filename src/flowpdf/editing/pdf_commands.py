from __future__ import annotations

import copy
from enum import StrEnum
from pathlib import Path
from typing import Any

from flowpdf.backends.base import AnnotationKind, AnnotationSpec, PdfBackend, TextStyle
from flowpdf.editing.command import EditCommand
from flowpdf.editing.text_editor import OverflowStrategy
from flowpdf.utils.coordinates import Point, Rect


class PdfCommandType(StrEnum):
    ADD_TEXT = "add_text"
    REPLACE_TEXT = "replace_text"
    ADD_IMAGE = "add_image"
    ADD_ANNOTATION = "add_annotation"
    DELETE_CONTENT = "delete_content"
    MOVE_PAGE = "move_page"
    DELETE_PAGES = "delete_pages"
    ROTATE_PAGES = "rotate_pages"
    INSERT_BLANK_PAGE = "insert_blank_page"
    INSERT_PDF = "insert_pdf"
    DUPLICATE_PAGE = "duplicate_page"


_DESCRIPTIONS = {
    PdfCommandType.ADD_TEXT: "添加文字",
    PdfCommandType.REPLACE_TEXT: "修改已有文字",
    PdfCommandType.ADD_IMAGE: "添加图片",
    PdfCommandType.ADD_ANNOTATION: "添加批注",
    PdfCommandType.DELETE_CONTENT: "永久擦除",
    PdfCommandType.MOVE_PAGE: "移动页面",
    PdfCommandType.DELETE_PAGES: "删除页面",
    PdfCommandType.ROTATE_PAGES: "旋转页面",
    PdfCommandType.INSERT_BLANK_PAGE: "插入空白页",
    PdfCommandType.INSERT_PDF: "插入 PDF",
    PdfCommandType.DUPLICATE_PAGE: "复制页面",
}


class PdfMutationCommand(EditCommand):
    """Transactional PDF mutation with snapshot-backed undo and compact recovery data."""

    _secret_keys = frozenset({"password", "passphrase", "pwd", "pdf_password"})

    def __init__(
        self,
        backend: PdfBackend,
        command_type: PdfCommandType,
        payload: dict[str, object],
        *,
        secrets: dict[str, object] | None = None,
    ) -> None:
        self.backend = backend
        self.command_type = command_type
        copied = copy.deepcopy(payload)
        self._secrets = dict(secrets or {})
        for key in tuple(copied):
            if key.casefold() in self._secret_keys:
                self._secrets[key] = copied.pop(key)
        self.payload = copied
        self._before: bytes | None = None
        self._after: bytes | None = None

    @property
    def description(self) -> str:
        return _DESCRIPTIONS[self.command_type]

    @property
    def history_bytes(self) -> int:
        return len(self._before or b"") + len(self._after or b"")

    def execute(self) -> None:
        if self._after is not None:
            self.backend.load_bytes(self._after)
            return
        before = self.backend.document_bytes()
        try:
            self._dispatch()
            after = self.backend.document_bytes()
        except Exception:
            self.backend.load_bytes(before)
            raise
        self._before = before
        self._after = after

    def undo(self) -> None:
        if self._before is None:
            raise RuntimeError("命令尚未执行，无法撤销")
        self.backend.load_bytes(self._before)

    def redo(self) -> None:
        if self._after is None:
            raise RuntimeError("命令尚未执行，无法重做")
        self.backend.load_bytes(self._after)

    def serialize(self) -> dict[str, object]:
        return {
            "type": self.command_type.value,
            **_json_object(self.payload),
        }

    @classmethod
    def from_record(
        cls,
        backend: PdfBackend,
        record: dict[str, object],
        *,
        secrets: dict[str, object] | None = None,
    ) -> PdfMutationCommand:
        data = dict(record)
        try:
            command_type = PdfCommandType(str(data.pop("type")))
        except (KeyError, ValueError) as exc:
            raise ValueError("恢复记录中的命令类型无效") from exc
        return cls(backend, command_type, data, secrets=secrets)

    def _dispatch(self) -> None:
        payload = self.payload
        if self.command_type is PdfCommandType.MOVE_PAGE:
            self.backend.move_page(int(payload["old_index"]), int(payload["new_index"]))
        elif self.command_type is PdfCommandType.DELETE_PAGES:
            self.backend.delete_pages(_int_list(payload["page_indices"]))
        elif self.command_type is PdfCommandType.ROTATE_PAGES:
            _backend_method(self.backend, "rotate_pages")(
                _int_list(payload["page_indices"]), int(payload.get("degrees", 90))
            )
        elif self.command_type is PdfCommandType.INSERT_BLANK_PAGE:
            _backend_method(self.backend, "insert_blank_page")(
                int(payload["insert_index"]),
                width=float(payload.get("width", 595)),
                height=float(payload.get("height", 842)),
            )
        elif self.command_type is PdfCommandType.INSERT_PDF:
            self.backend.insert_pages(
                Path(str(payload["source_path"])),
                int(payload["insert_index"]),
                password=_optional_secret(self._secrets, "password"),
            )
        elif self.command_type is PdfCommandType.DUPLICATE_PAGE:
            insert_value = payload.get("insert_index")
            _backend_method(self.backend, "duplicate_page")(
                int(payload["page_index"]),
                None if insert_value is None else int(insert_value),
            )
        elif self.command_type is PdfCommandType.ADD_TEXT:
            self.backend.add_text(
                int(payload["page_index"]),
                _payload_rect(payload["rect"]),
                str(payload["text"]),
                _payload_text_style(payload.get("style", {})),
            )
        elif self.command_type is PdfCommandType.REPLACE_TEXT:
            self.backend.replace_text(
                int(payload["page_index"]),
                _payload_rect(payload["rect"]),
                str(payload["text"]),
                _payload_text_style(payload.get("style", {})),
            )
        elif self.command_type is PdfCommandType.ADD_IMAGE:
            self.backend.add_image(
                int(payload["page_index"]),
                _payload_rect(payload["rect"]),
                Path(str(payload["image_path"])),
            )
        elif self.command_type is PdfCommandType.ADD_ANNOTATION:
            self.backend.add_annotation(
                int(payload["page_index"]),
                _payload_annotation(payload["annotation"]),
            )
        elif self.command_type is PdfCommandType.DELETE_CONTENT:
            self.backend.delete_content(int(payload["page_index"]), _payload_rect(payload["rect"]))
        else:
            raise ValueError(f"不支持的 PDF 命令：{self.command_type}")


def _backend_method(backend: PdfBackend, name: str) -> Any:
    method = getattr(backend, name, None)
    if method is None:
        raise TypeError(f"当前 PDF 后端不支持 {name}")
    return method


def _payload_rect(value: object) -> Rect:
    if isinstance(value, Rect):
        return value
    if isinstance(value, (list, tuple)) and len(value) == 4:
        return Rect(*(float(item) for item in value))
    if isinstance(value, dict):
        return Rect(*(float(value[key]) for key in ("x0", "y0", "x1", "y1")))
    raise ValueError("命令中的区域坐标无效")


def _payload_text_style(value: object) -> TextStyle:
    if isinstance(value, TextStyle):
        return value
    if not isinstance(value, dict):
        raise ValueError("命令中的文字样式无效")
    data = dict(value)
    if "overflow" in data:
        data["overflow"] = OverflowStrategy(str(data["overflow"]))
    for key in ("color", "background_color"):
        if isinstance(data.get(key), list):
            data[key] = tuple(data[key])
    return TextStyle(**data)


def _payload_annotation(value: object) -> AnnotationSpec:
    if isinstance(value, AnnotationSpec):
        return value
    if not isinstance(value, dict):
        raise ValueError("命令中的批注参数无效")
    data = dict(value)
    data["kind"] = AnnotationKind(str(data["kind"]))
    data["rect"] = _payload_rect(data["rect"])
    for key in ("color", "fill_color"):
        if isinstance(data.get(key), list):
            data[key] = tuple(data[key])
    if "points" in data:
        data["points"] = tuple(Point(*point) for point in data["points"])
    return AnnotationSpec(**data)


def _int_list(value: object) -> list[int]:
    if not isinstance(value, (list, tuple)):
        raise ValueError("命令中的页码列表无效")
    return [int(item) for item in value]


def _optional_secret(secrets: dict[str, object], key: str) -> str | None:
    value = secrets.get(key)
    return None if value is None else str(value)


def _json_object(value: dict[str, object]) -> dict[str, object]:
    return {key: _json_value(item) for key, item in value.items()}


def _json_value(value: object) -> object:
    if isinstance(value, Rect):
        return [value.x0, value.y0, value.x1, value.y1]
    if isinstance(value, Point):
        return [value.x, value.y]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, StrEnum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        fields = value.__dataclass_fields__
        return {name: _json_value(getattr(value, name)) for name in fields}
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value
