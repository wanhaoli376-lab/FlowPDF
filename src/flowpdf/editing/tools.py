from __future__ import annotations

from enum import StrEnum


class ToolMode(StrEnum):
    SELECT = "select"
    ADD_TEXT = "add_text"
    ADD_IMAGE = "add_image"
    HIGHLIGHT = "highlight"
    UNDERLINE = "underline"
    STRIKEOUT = "strikeout"
    NOTE = "note"
    LINE = "line"
    ARROW = "arrow"
    RECTANGLE = "rectangle"
    ELLIPSE = "ellipse"
    PERMANENT_DELETE = "permanent_delete"
