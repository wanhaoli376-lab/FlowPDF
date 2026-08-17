from __future__ import annotations

import io
import re
import warnings

from PIL import Image, UnidentifiedImageError
from PySide6.QtCore import QMimeData, Qt, QTimer, Signal
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

from flowpdf.document_mode.editing.document_mapper import DocumentMapper
from flowpdf.document_mode.layout import PageGeometry, PaginationSnapshot, Paginator
from flowpdf.document_mode.models import FlowDocument, ImageAsset


class PaginatedTextEdit(QTextEdit):
    """One continuous rich text editor whose QTextDocument paginates automatically."""

    pagination_changed = Signal(int)
    model_changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._mapper = DocumentMapper()
        self._geometry = PageGeometry.from_setup(FlowDocument.new().page_setup)
        self._page_count = 1
        self._pagination_timer = QTimer(self)
        self._pagination_timer.setSingleShot(True)
        self._pagination_timer.setInterval(180)
        self._pagination_timer.timeout.connect(self._emit_pagination)
        self.setAcceptRichText(True)
        self.setUndoRedoEnabled(True)
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

    def set_flow_document(self, document: FlowDocument) -> None:
        self._geometry = PageGeometry.from_setup(document.page_setup)
        self.setLineWrapColumnOrWidth(round(self._geometry.content_width_px))
        self._geometry = self._mapper.populate(self.document(), document)
        self.setMinimumWidth(round(self._geometry.content_width_px + 72))
        self._page_count = self.page_count
        self.moveCursor(QTextCursor.MoveOperation.Start)

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
        value.setFontPointSize(11.0)
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
        cursor.setBlockFormat(value)

    def insert_image(
        self,
        data: bytes,
        *,
        media_type: str,
        width_pt: float | None = None,
        alignment: str = "center",
        alt_text: str = "",
    ) -> str:
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
            self.textCursor().insertFragment(QTextDocumentFragment.fromHtml(clean))
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
    cleaned = re.sub(
        r"<(script|style|iframe|object|embed)\b[^>]*>.*?</\1\s*>",
        "",
        value,
        flags=re.IGNORECASE | re.DOTALL,
    )
    cleaned = re.sub(r"\s+on[a-z]+\s*=\s*(['\"]).*?\1", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"\s+(?:src|href)\s*=\s*(['\"])javascript:.*?\1",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned


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
