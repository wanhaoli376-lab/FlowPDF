from __future__ import annotations

import html
import io
import re
import warnings
from html.parser import HTMLParser
from typing import ClassVar

from PIL import Image, UnidentifiedImageError
from PySide6.QtCore import QMimeData, QSizeF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextDocumentFragment,
    QTextFormat,
    QTextImageFormat,
    QTextListFormat,
)
from PySide6.QtWidgets import QTextEdit

from flowpdf.document_mode.editing.document_mapper import BASE_FONT_SIZE_PT, DocumentMapper
from flowpdf.document_mode.layout import PageGeometry, PaginationSnapshot, Paginator
from flowpdf.document_mode.models import FlowDocument, ImageAsset


class PaginatedTextEdit(QTextEdit):
    """One continuous rich text editor whose QTextDocument paginates automatically."""

    pagination_changed = Signal(int)
    model_changed = Signal()
    zoom_changed = Signal(float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._mapper = DocumentMapper()
        self._geometry = PageGeometry.from_setup(FlowDocument.new().page_setup)
        self._page_count = 1
        self._zoom_factor = 1.0
        self._pagination_timer = QTimer(self)
        self._pagination_timer.setSingleShot(True)
        self._pagination_timer.setInterval(180)
        self._pagination_timer.timeout.connect(self._emit_pagination)
        self.setAcceptRichText(True)
        self.setUndoRedoEnabled(True)
        default_font = self.document().defaultFont()
        default_font.setPointSizeF(BASE_FONT_SIZE_PT)
        self.document().setDefaultFont(default_font)
        self.setFont(default_font)
        self.setLineWrapMode(QTextEdit.LineWrapMode.FixedPixelWidth)
        self.document().contentsChanged.connect(self._schedule_layout_update)
        self.setStyleSheet(
            "QTextEdit { background: #e5e7eb; color: #111827; border: 0; padding: 24px; }"
        )

    @property
    def page_geometry(self) -> PageGeometry:
        return self._geometry

    @property
    def page_count(self) -> int:
        return self.pagination_snapshot().page_count

    @property
    def zoom_factor(self) -> float:
        return self._zoom_factor

    def set_flow_document(self, document: FlowDocument) -> None:
        self.set_zoom_factor(1.0)
        self._geometry = PageGeometry.from_setup(document.page_setup)
        self._geometry = self._mapper.populate(self.document(), document)
        self._apply_zoom_geometry()
        self._page_count = self.page_count
        self.moveCursor(QTextCursor.MoveOperation.Start)

    def zoom_in(self) -> None:
        self.set_zoom_factor(self._zoom_factor + 0.1)

    def zoom_out(self) -> None:
        self.set_zoom_factor(self._zoom_factor - 0.1)

    def actual_size(self) -> None:
        self.set_zoom_factor(1.0)

    def set_zoom_factor(self, factor: float) -> None:
        selected = round(min(3.0, max(0.5, factor)), 1)
        if selected == self._zoom_factor:
            return
        self._zoom_factor = selected
        self.zoom_changed.emit(self.zoom_factor)

    def _apply_zoom_geometry(self) -> None:
        width = self._geometry.content_width_px
        height = self._geometry.content_height_px
        self.setLineWrapColumnOrWidth(round(width))
        self.document().setPageSize(QSizeF(width, height))
        self.setMinimumWidth(0)

    def flow_document(self) -> FlowDocument:
        return self._mapper.to_model(self.document())

    def pagination_snapshot(self) -> PaginationSnapshot:
        return Paginator.snapshot(
            self.document(),
            page_height_px=self._geometry.content_height_px,
        )

    def replace_all(self, query: str, replacement: str, *, case_sensitive: bool = False) -> int:
        if not query:
            return 0
        flags = QTextDocument.FindFlag(0)
        if case_sensitive:
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        cursor = self.document().find(query, 0, flags)
        replacements = 0
        cursor.beginEditBlock()
        while not cursor.isNull():
            cursor.insertText(replacement)
            replacements += 1
            cursor = self.document().find(query, cursor.position(), flags)
        cursor.endEditBlock()
        return replacements

    def find_text(
        self,
        query: str,
        *,
        backward: bool = False,
        case_sensitive: bool = False,
    ) -> bool:
        flags = QTextDocument.FindFlag(0)
        if backward:
            flags |= QTextDocument.FindFlag.FindBackward
        if case_sensitive:
            flags |= QTextDocument.FindFlag.FindCaseSensitively
        return self.find(query, flags)

    def set_font_family(self, family: str) -> None:
        if not family.strip():
            return
        value = QTextCharFormat()
        value.setFontFamilies([family])
        self._merge_character_format(value)

    def set_font_size(self, points: float) -> None:
        if not 1.0 <= points <= 512.0:
            raise ValueError("字号超出允许范围")
        value = QTextCharFormat()
        value.setFontPointSize(points)
        self._merge_character_format(value)

    def set_bold(self, enabled: bool) -> None:
        value = QTextCharFormat()
        value.setFontWeight(QFont.Weight.Bold if enabled else QFont.Weight.Normal)
        self._merge_character_format(value)

    def set_italic(self, enabled: bool) -> None:
        value = QTextCharFormat()
        value.setFontItalic(enabled)
        self._merge_character_format(value)

    def set_underline(self, enabled: bool) -> None:
        value = QTextCharFormat()
        value.setFontUnderline(enabled)
        self._merge_character_format(value)

    def set_strikeout(self, enabled: bool) -> None:
        value = QTextCharFormat()
        value.setFontStrikeOut(enabled)
        self._merge_character_format(value)

    def set_text_color(self, color: str | QColor) -> None:
        value = QTextCharFormat()
        value.setForeground(QColor(color))
        self._merge_character_format(value)

    def set_background_color(self, color: str | QColor | None) -> None:
        value = QTextCharFormat()
        if color is None:
            value.clearBackground()
        else:
            value.setBackground(QColor(color))
        self._merge_character_format(value)

    def set_superscript(self, enabled: bool) -> None:
        value = QTextCharFormat()
        value.setVerticalAlignment(
            QTextCharFormat.VerticalAlignment.AlignSuperScript
            if enabled
            else QTextCharFormat.VerticalAlignment.AlignNormal
        )
        self._merge_character_format(value)

    def set_subscript(self, enabled: bool) -> None:
        value = QTextCharFormat()
        value.setVerticalAlignment(
            QTextCharFormat.VerticalAlignment.AlignSubScript
            if enabled
            else QTextCharFormat.VerticalAlignment.AlignNormal
        )
        self._merge_character_format(value)

    def clear_character_format(self) -> None:
        cursor = self.textCursor()
        value = QTextCharFormat()
        value.setFontFamilies(["Microsoft YaHei"])
        value.setFontPointSize(BASE_FONT_SIZE_PT)
        if cursor.hasSelection():
            cursor.setCharFormat(value)
        else:
            self.setCurrentCharFormat(value)

    def set_paragraph_alignment(self, alignment: str) -> None:
        qt_alignment = {
            "left": Qt.AlignmentFlag.AlignLeft,
            "center": Qt.AlignmentFlag.AlignHCenter,
            "right": Qt.AlignmentFlag.AlignRight,
            "justify": Qt.AlignmentFlag.AlignJustify,
        }.get(alignment)
        if qt_alignment is None:
            raise ValueError("段落对齐方式无效")
        value = QTextBlockFormat()
        value.setAlignment(qt_alignment)
        self.textCursor().mergeBlockFormat(value)

    def set_line_spacing(self, multiplier: float) -> None:
        if not 0.5 <= multiplier <= 10.0:
            raise ValueError("行距倍数超出允许范围")
        value = QTextBlockFormat()
        value.setLineHeight(
            multiplier * 100,
            QTextBlockFormat.LineHeightTypes.ProportionalHeight.value,
        )
        self.textCursor().mergeBlockFormat(value)

    def set_paragraph_indents(
        self,
        *,
        first_line_pt: float | None = None,
        left_pt: float | None = None,
        right_pt: float | None = None,
    ) -> None:
        value = QTextBlockFormat()
        if first_line_pt is not None:
            value.setTextIndent(self._geometry.points_to_pixels(first_line_pt))
        if left_pt is not None:
            value.setLeftMargin(self._geometry.points_to_pixels(left_pt))
        if right_pt is not None:
            value.setRightMargin(self._geometry.points_to_pixels(right_pt))
        self.textCursor().mergeBlockFormat(value)

    def set_paragraph_spacing(
        self,
        *,
        before_pt: float | None = None,
        after_pt: float | None = None,
    ) -> None:
        value = QTextBlockFormat()
        if before_pt is not None:
            value.setTopMargin(self._geometry.points_to_pixels(before_pt))
        if after_pt is not None:
            value.setBottomMargin(self._geometry.points_to_pixels(after_pt))
        self.textCursor().mergeBlockFormat(value)

    def change_paragraph_indent(self, delta_pt: float) -> None:
        current_px = self.textCursor().blockFormat().leftMargin()
        current_pt = self._geometry.pixels_to_points(current_px)
        self.set_paragraph_indents(left_pt=max(0.0, current_pt + delta_pt))

    def set_keep_together(self, enabled: bool) -> None:
        value = QTextBlockFormat()
        value.setNonBreakableLines(enabled)
        self.textCursor().mergeBlockFormat(value)

    def set_list_style(self, kind: str | None) -> None:
        cursor = self.textCursor()
        current_list = cursor.currentList()
        if kind is None:
            if current_list is not None:
                block_format = cursor.blockFormat()
                block_format.setIndent(0)
                cursor.setBlockFormat(block_format)
            return
        styles = {
            "bullet": QTextListFormat.Style.ListDisc,
            "number": QTextListFormat.Style.ListDecimal,
        }
        if kind not in styles:
            raise ValueError("列表类型无效")
        value = QTextListFormat()
        value.setStyle(styles[kind])
        value.setIndent(max(1, cursor.blockFormat().indent() or 1))
        cursor.createList(value)

    def insert_page_break(self) -> None:
        cursor = self.textCursor()
        cursor.insertBlock()
        value = cursor.blockFormat()
        value.setPageBreakPolicy(QTextFormat.PageBreakFlag.PageBreak_AlwaysBefore)
        value.setProperty(int(QTextFormat.Property.UserProperty) + 104, True)
        cursor.setBlockFormat(value)
        cursor.insertBlock()
        self.setTextCursor(cursor)

    def insert_image(
        self,
        data: bytes,
        *,
        media_type: str,
        width_pt: float | None = None,
        alignment: str = "center",
        alt_text: str = "",
        pixel_size: tuple[int, int] | None = None,
    ) -> str:
        if pixel_size is None:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("error", Image.DecompressionBombWarning)
                    with Image.open(io.BytesIO(data)) as decoded:
                        width_px, height_px = decoded.size
                        decoded.verify()
            except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
                raise ValueError("图片解码资源异常") from exc
            except (OSError, UnidentifiedImageError) as exc:
                raise ValueError("图片内容损坏或格式不受支持") from exc
        else:
            width_px, height_px = pixel_size
            if width_px <= 0 or height_px <= 0:
                raise ValueError("图片尺寸无效")
        if width_px * height_px > 80_000_000:
            raise ValueError("图片像素数量超过安全上限")
        asset = ImageAsset.create(
            data,
            media_type=media_type,
            width_px=width_px,
            height_px=height_px,
        )
        self._mapper.register_asset(self.document(), asset)
        shown_width_pt = width_pt or min(
            width_px * 72.0 / 96.0,
            self._geometry.content_width_px * 72.0 / 96.0,
        )
        shown_height_pt = shown_width_pt * height_px / width_px
        cursor = self.textCursor()
        cursor.beginEditBlock()
        if cursor.block().text() or cursor.positionInBlock() > 0:
            cursor.insertBlock()
        block_format = cursor.blockFormat()
        block_format.setAlignment(_alignment(alignment))
        cursor.setBlockFormat(block_format)
        image_format = QTextImageFormat()
        image_format.setName(f"flowpdf-asset://{asset.asset_id}")
        image_format.setWidth(self._geometry.points_to_pixels(shown_width_pt))
        image_format.setHeight(self._geometry.points_to_pixels(shown_height_pt))
        image_format.setProperty(int(QTextFormat.Property.UserProperty) + 103, alt_text)
        cursor.insertImage(image_format)
        cursor.insertBlock()
        cursor.endEditBlock()
        self.setTextCursor(cursor)
        return asset.asset_id

    def update_image(
        self,
        asset_id: str,
        *,
        width_pt: float | None = None,
        alignment: str | None = None,
        alt_text: str | None = None,
    ) -> bool:
        cursor = self._image_cursor(asset_id)
        if cursor is None:
            return False
        image_format = cursor.charFormat().toImageFormat()
        if width_pt is not None:
            if width_pt <= 0:
                raise ValueError("图片宽度必须大于零")
            ratio = image_format.height() / max(1.0, image_format.width())
            width_px = self._geometry.points_to_pixels(width_pt)
            image_format.setWidth(width_px)
            image_format.setHeight(width_px * ratio)
        if alt_text is not None:
            image_format.setProperty(int(QTextFormat.Property.UserProperty) + 103, alt_text)
        cursor.setCharFormat(image_format)
        if alignment is not None:
            block_format = cursor.blockFormat()
            block_format.setAlignment(_alignment(alignment))
            cursor.setBlockFormat(block_format)
        return True

    def delete_image(self, asset_id: str) -> bool:
        cursor = self._image_cursor(asset_id)
        if cursor is None:
            return False
        cursor.beginEditBlock()
        cursor.removeSelectedText()
        if not cursor.block().text() and self.document().blockCount() > 1:
            cursor.deleteChar()
        cursor.endEditBlock()
        return True

    def insertFromMimeData(self, source: QMimeData) -> None:
        if source.hasHtml():
            clean = _sanitize_html(source.html())
            cursor = self.textCursor()
            cursor.beginEditBlock()
            cursor.insertFragment(QTextDocumentFragment.fromHtml(clean))
            cursor.endEditBlock()
            return
        super().insertFromMimeData(source)

    def _merge_character_format(self, value: QTextCharFormat) -> None:
        cursor = self.textCursor()
        cursor.mergeCharFormat(value)
        self.mergeCurrentCharFormat(value)

    def _image_cursor(self, asset_id: str) -> QTextCursor | None:
        block = self.document().begin()
        expected = f"flowpdf-asset://{asset_id}"
        while block.isValid():
            iterator = block.begin()
            while not iterator.atEnd():
                fragment = iterator.fragment()
                if fragment.isValid() and fragment.charFormat().isImageFormat():
                    image = fragment.charFormat().toImageFormat()
                    if image.name() == expected:
                        cursor = QTextCursor(self.document())
                        cursor.setPosition(fragment.position())
                        cursor.setPosition(
                            fragment.position() + fragment.length(),
                            QTextCursor.MoveMode.KeepAnchor,
                        )
                        return cursor
                iterator += 1
            block = block.next()
        return None

    def _schedule_layout_update(self) -> None:
        self.model_changed.emit()
        self._pagination_timer.start()

    def _emit_pagination(self) -> None:
        count = self.page_count
        if count != self._page_count:
            self._page_count = count
            self.pagination_changed.emit(count)


def _sanitize_html(value: str) -> str:
    parser = _SafeRichTextParser()
    parser.feed(value)
    parser.close()
    return "".join(parser.output)


class _SafeRichTextParser(HTMLParser):
    _ALLOWED_TAGS: ClassVar[set[str]] = {
        "p",
        "div",
        "span",
        "br",
        "b",
        "i",
        "u",
        "s",
        "sub",
        "sup",
        "ul",
        "ol",
        "li",
        "h1",
        "h2",
        "h3",
        "blockquote",
    }
    _DROP_CONTENT_TAGS: ClassVar[set[str]] = {
        "script",
        "style",
        "iframe",
        "object",
        "embed",
        "svg",
        "math",
    }
    _TAG_ALIASES: ClassVar[dict[str, str]] = {
        "strong": "b",
        "em": "i",
        "strike": "s",
        "a": "span",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.output: list[str] = []
        self._drop_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.casefold()
        if normalized in self._DROP_CONTENT_TAGS:
            self._drop_depth += 1
            return
        if self._drop_depth:
            return
        normalized = self._TAG_ALIASES.get(normalized, normalized)
        if normalized not in self._ALLOWED_TAGS:
            return
        style = next((value for name, value in attrs if name.casefold() == "style"), None)
        safe_style = _sanitize_style(style or "")
        attribute = f' style="{html.escape(safe_style, quote=True)}"' if safe_style else ""
        self.output.append(f"<{normalized}{attribute}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.casefold()
        if normalized in self._DROP_CONTENT_TAGS:
            self._drop_depth = max(0, self._drop_depth - 1)
            return
        if self._drop_depth:
            return
        normalized = self._TAG_ALIASES.get(normalized, normalized)
        if normalized in self._ALLOWED_TAGS and normalized != "br":
            self.output.append(f"</{normalized}>")

    def handle_data(self, data: str) -> None:
        if not self._drop_depth:
            self.output.append(html.escape(data))


_SAFE_CSS_NAMES = {
    "background-color",
    "color",
    "font-family",
    "font-size",
    "font-style",
    "font-weight",
    "line-height",
    "margin-left",
    "margin-right",
    "text-align",
    "text-decoration",
    "text-indent",
}
_SAFE_CSS_VALUE = re.compile(r"^[\w\s#.,'\"()%+-]+$", re.UNICODE)


def _sanitize_style(value: str) -> str:
    declarations: list[str] = []
    for declaration in value.split(";"):
        name, separator, raw_value = declaration.partition(":")
        name = name.strip().casefold()
        selected = raw_value.strip()
        if (
            separator
            and name in _SAFE_CSS_NAMES
            and selected
            and len(selected) <= 128
            and _SAFE_CSS_VALUE.fullmatch(selected)
            and "url" not in selected.casefold()
            and "expression" not in selected.casefold()
        ):
            declarations.append(f"{name}:{selected}")
    return ";".join(declarations)


def _alignment(value: str) -> Qt.AlignmentFlag:
    alignments = {
        "left": Qt.AlignmentFlag.AlignLeft,
        "center": Qt.AlignmentFlag.AlignHCenter,
        "right": Qt.AlignmentFlag.AlignRight,
    }
    try:
        return alignments[value]
    except KeyError as exc:
        raise ValueError("图片对齐方式无效") from exc
