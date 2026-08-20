from __future__ import annotations

import html
import io
import re
import warnings
from html.parser import HTMLParser
from typing import ClassVar

from PIL import Image, UnidentifiedImageError
from PySide6.QtCore import QMimeData, QPointF, QRectF, QSize, QSizeF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAbstractTextDocumentLayout,
    QColor,
    QFont,
    QImage,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPalette,
    QPen,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextDocumentFragment,
    QTextFormat,
    QTextImageFormat,
    QTextListFormat,
    QWheelEvent,
)
from PySide6.QtWidgets import QFrame, QTextEdit

from flowpdf.document_mode.editing.document_mapper import BASE_FONT_SIZE_PT, DocumentMapper
from flowpdf.document_mode.layout import (
    PageGeometry,
    PagePresentation,
    PaginationSnapshot,
    Paginator,
)
from flowpdf.document_mode.models import FlowDocument, ImageAsset


class PaginatedTextEdit(QTextEdit):
    """One continuous rich text editor whose QTextDocument paginates automatically."""

    pagination_changed = Signal(int)
    presentation_changed = Signal()
    cursor_visibility_requested = Signal(QRectF)
    wheel_scroll_requested = Signal(int, int)
    model_changed = Signal()
    zoom_changed = Signal(float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._mapper = DocumentMapper()
        self._geometry = PageGeometry.from_setup(FlowDocument.new().page_setup)
        self._page_count = 1
        self._presentation = PagePresentation(self._geometry, 1)
        self._active_page = 0
        self._document_active = False
        self._zoom_factor = 1.0
        self._pagination_timer = QTimer(self)
        self._pagination_timer.setSingleShot(True)
        self._pagination_timer.setInterval(180)
        self._pagination_timer.timeout.connect(self._emit_pagination)
        self.setAcceptRichText(True)
        self.setUndoRedoEnabled(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        default_font = self.document().defaultFont()
        default_font.setPointSizeF(BASE_FONT_SIZE_PT)
        self.document().setDefaultFont(default_font)
        self.setFont(default_font)
        self.setLineWrapMode(QTextEdit.LineWrapMode.FixedPixelWidth)
        self.document().contentsChanged.connect(self._schedule_layout_update)
        self.cursorPositionChanged.connect(self._cursor_position_changed)
        self.setStyleSheet("QTextEdit { background: #e5e7eb; color: #111827; border: 0; }")

    @property
    def page_geometry(self) -> PageGeometry:
        return self._geometry

    @property
    def page_count(self) -> int:
        return self._page_count

    @property
    def active_page(self) -> int:
        return self._active_page

    @property
    def has_flow_document(self) -> bool:
        return self._document_active

    @property
    def page_presentation(self) -> PagePresentation:
        return self._presentation

    @property
    def zoom_factor(self) -> float:
        return self._zoom_factor

    def set_flow_document(self, document: FlowDocument) -> None:
        self._document_active = False
        self._pagination_timer.stop()
        self.set_zoom_factor(1.0)
        self._geometry = PageGeometry.from_setup(document.page_setup)
        self._geometry = self._mapper.populate(self.document(), document)
        self._apply_zoom_geometry()
        self._document_active = True
        self._page_count = self.pagination_snapshot().page_count
        self._refresh_presentation(self._page_count)
        self.set_active_page(0)
        self.moveCursor(QTextCursor.MoveOperation.Start)

    def clear_flow_document(self) -> None:
        self._document_active = False
        self._pagination_timer.stop()
        self.clear()
        self._page_count = 1
        self._active_page = 0
        selected = PagePresentation(self._geometry, 1)
        if selected != self._presentation:
            self._presentation = selected
            self.presentation_changed.emit()
        self.viewport().update()

    def zoom_in(self) -> None:
        self.set_zoom_factor(self._zoom_factor + 0.1)

    def zoom_out(self) -> None:
        self.set_zoom_factor(self._zoom_factor - 0.1)

    def actual_size(self) -> None:
        self.set_zoom_factor(1.0)

    def set_zoom_factor(self, factor: float) -> None:
        selected = round(min(3.0, max(0.2, factor)), 2)
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

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.fillRect(event.rect(), QColor("#e5e7eb"))
        context = self._paint_context()
        active_page = self._active_page
        layout = self.document().documentLayout()
        repaint_rect = QRectF(event.rect())
        for page_index in self._presentation.page_indices_intersecting(repaint_rect):
            paper = self._presentation.paper_rect(page_index)
            painter.fillRect(paper.translated(3, 4), QColor("#c4c9d0"))
            painter.fillRect(paper, QColor("#ffffff"))
            border = QColor("#3b82f6") if page_index == active_page else QColor("#cbd5e1")
            painter.setPen(QPen(border, 1.5 if page_index == active_page else 1.0))
            painter.drawRect(paper)

            content = self._presentation.content_rect(page_index)
            painter.save()
            painter.setClipRect(content)
            logical_top = page_index * self._geometry.content_height_px
            painter.translate(content.left(), content.top() - logical_top)
            context.clip = QRectF(
                0,
                logical_top,
                self._geometry.content_width_px,
                self._geometry.content_height_px,
            )
            layout.draw(painter, context)
            painter.restore()
        painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        mapped = self._mapped_mouse_event(event)
        if mapped is None:
            event.ignore()
            return
        super().mousePressEvent(mapped)
        self.viewport().update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        mapped = self._mapped_mouse_event(event)
        if mapped is None:
            event.ignore()
            return
        super().mouseMoveEvent(mapped)
        self.viewport().update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        mapped = self._mapped_mouse_event(event)
        if mapped is None:
            event.ignore()
            return
        super().mouseReleaseEvent(mapped)
        self.viewport().update()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        mapped = self._mapped_mouse_event(event)
        if mapped is None:
            event.ignore()
            return
        super().mouseDoubleClickEvent(mapped)
        self.viewport().update()

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.pixelDelta() if not event.pixelDelta().isNull() else event.angleDelta()
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            if delta.y() > 0:
                self.zoom_in()
            elif delta.y() < 0:
                self.zoom_out()
            event.accept()
            return
        self.wheel_scroll_requested.emit(delta.x(), delta.y())
        event.accept()

    def visual_cursor_rect(self, cursor: QTextCursor | None = None) -> QRectF:
        logical = self.document_cursor_rect(cursor)
        return self._presentation.document_to_visual_rect(logical)

    def document_cursor_rect(self, cursor: QTextCursor | None = None) -> QRectF:
        return QRectF(super().cursorRect(cursor or self.textCursor()))

    @property
    def current_page(self) -> int:
        return self._presentation.page_for_document_y(self.document_cursor_rect().center().y())

    def set_active_page(self, page_index: int) -> None:
        selected = max(0, min(self._presentation.page_count - 1, page_index))
        if selected == self._active_page:
            return
        self._active_page = selected
        self.viewport().update()

    def render_page_thumbnail(self, page_index: int, size: QSize) -> QImage:
        if not 0 <= page_index < self._presentation.page_count:
            raise IndexError("页面索引超出范围")
        if size.width() <= 0 or size.height() <= 0:
            raise ValueError("缩略图尺寸必须大于零")
        image = QImage(size, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(QColor("#e5e7eb"))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        available_width = max(1.0, size.width() - 6.0)
        available_height = max(1.0, size.height() - 6.0)
        scale = min(
            available_width / self._geometry.page_width_px,
            available_height / self._geometry.page_height_px,
        )
        shown_width = self._geometry.page_width_px * scale
        shown_height = self._geometry.page_height_px * scale
        origin_x = (size.width() - shown_width) / 2
        origin_y = (size.height() - shown_height) / 2
        painter.translate(origin_x, origin_y)
        painter.scale(scale, scale)
        paper = QRectF(0, 0, self._geometry.page_width_px, self._geometry.page_height_px)
        painter.fillRect(paper, QColor("#ffffff"))
        painter.setPen(QPen(QColor("#cbd5e1"), 1.0 / scale))
        painter.drawRect(paper)

        left = self._geometry.points_to_pixels(self._geometry.margin_left_pt)
        top = self._geometry.points_to_pixels(self._geometry.margin_top_pt)
        content = QRectF(
            left,
            top,
            self._geometry.content_width_px,
            self._geometry.content_height_px,
        )
        painter.setClipRect(content)
        logical_top = page_index * self._geometry.content_height_px
        painter.translate(content.left(), content.top() - logical_top)
        context = QAbstractTextDocumentLayout.PaintContext()
        context.palette = self.palette()
        context.cursorPosition = -1
        context.clip = QRectF(
            0,
            logical_top,
            self._geometry.content_width_px,
            self._geometry.content_height_px,
        )
        self.document().documentLayout().draw(painter, context)
        painter.end()
        return image

    def inputMethodQuery(self, query: Qt.InputMethodQuery):
        if query == Qt.InputMethodQuery.ImCursorRectangle:
            return self.visual_cursor_rect()
        return super().inputMethodQuery(query)

    def _mapped_mouse_event(self, event: QMouseEvent) -> QMouseEvent | None:
        position = self._presentation.visual_to_document(event.position())
        if position is None:
            return None
        return QMouseEvent(
            event.type(),
            position,
            event.globalPosition(),
            event.button(),
            event.buttons(),
            event.modifiers(),
            event.pointingDevice(),
        )

    def extend_selection_to_visual(self, point: QPointF, anchor: int) -> None:
        """Extend a drag selection to a visual canvas point, including page gaps."""

        position = self.text_position_at_visual(point, clamp=True)
        if position is None:
            return
        document_end = max(0, self.document().characterCount() - 1)
        cursor = QTextCursor(self.document())
        cursor.setPosition(min(max(0, anchor), document_end))
        cursor.setPosition(
            min(max(0, position), document_end),
            QTextCursor.MoveMode.KeepAnchor,
        )
        self.setTextCursor(cursor)

    def text_position_at_visual(self, point: QPointF, *, clamp: bool = False) -> int | None:
        logical = (
            self._presentation.visual_to_document_clamped(point)
            if clamp
            else self._presentation.visual_to_document(point)
        )
        if logical is None:
            return None
        position = (
            self.document()
            .documentLayout()
            .hitTest(
                logical,
                Qt.HitTestAccuracy.FuzzyHit,
            )
        )
        document_end = max(0, self.document().characterCount() - 1)
        return min(max(0, position), document_end)

    def place_cursor_at_visual(self, point: QPointF, *, keep_anchor: bool = False) -> bool:
        position = self.text_position_at_visual(point)
        if position is None:
            return False
        cursor = self.textCursor()
        cursor.setPosition(
            position,
            QTextCursor.MoveMode.KeepAnchor if keep_anchor else QTextCursor.MoveMode.MoveAnchor,
        )
        self.setTextCursor(cursor)
        return True

    def select_word_at_visual(self, point: QPointF) -> bool:
        if not self.place_cursor_at_visual(point):
            return False
        cursor = self.textCursor()
        cursor.select(QTextCursor.SelectionType.WordUnderCursor)
        self.setTextCursor(cursor)
        return True

    def select_paragraph_at_visual(self, point: QPointF) -> bool:
        if not self.place_cursor_at_visual(point):
            return False
        cursor = self.textCursor()
        cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
        self.setTextCursor(cursor)
        return True

    def _paint_context(self) -> QAbstractTextDocumentLayout.PaintContext:
        context = QAbstractTextDocumentLayout.PaintContext()
        context.palette = self.palette()
        cursor = self.textCursor()
        selections = list(self.extraSelections())
        if cursor.hasSelection():
            selected = QTextEdit.ExtraSelection()
            selected.cursor = cursor
            selected.format.setBackground(self.palette().brush(QPalette.ColorRole.Highlight))
            selected.format.setForeground(self.palette().brush(QPalette.ColorRole.HighlightedText))
            selections.append(selected)
        for value in selections:
            selection = QAbstractTextDocumentLayout.Selection()
            selection.cursor = value.cursor
            selection.format = value.format
            context.selections.append(selection)
        context.cursorPosition = cursor.position() if self.hasFocus() else -1
        return context

    def _cursor_page(self) -> int:
        return self.current_page

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
        cursor.beginEditBlock()
        following = QTextBlockFormat(cursor.blockFormat())
        following.setPageBreakPolicy(QTextFormat.PageBreakFlag.PageBreak_Auto)
        following.clearProperty(int(QTextFormat.Property.UserProperty) + 104)
        cursor.insertBlock()
        page_break = QTextBlockFormat(following)
        page_break.setPageBreakPolicy(QTextFormat.PageBreakFlag.PageBreak_AlwaysBefore)
        page_break.setProperty(int(QTextFormat.Property.UserProperty) + 104, True)
        cursor.setBlockFormat(page_break)
        cursor.insertBlock(following)
        cursor.endEditBlock()
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
        if not self._document_active:
            return
        self.model_changed.emit()
        self._pagination_timer.start()
        self.viewport().update()

    def _cursor_position_changed(self) -> None:
        if self._document_active:
            self.set_active_page(self.current_page)
        rect = self.visual_cursor_rect()
        self.cursor_visibility_requested.emit(rect)
        self.viewport().update()

    def _emit_pagination(self) -> None:
        if not self._document_active:
            return
        count = self.pagination_snapshot().page_count
        changed = count != self._page_count
        self._page_count = count
        self._refresh_presentation(count)
        if changed:
            self.pagination_changed.emit(count)

    def refresh_pagination(self) -> int:
        """Synchronously refresh cached pagination for explicit save/export actions."""

        self._pagination_timer.stop()
        self._emit_pagination()
        return self._page_count

    def _refresh_presentation(self, page_count: int) -> None:
        selected = PagePresentation(self._geometry, max(1, page_count))
        if selected == self._presentation:
            return
        self._presentation = selected
        self._active_page = min(self._active_page, selected.page_count - 1)
        self.presentation_changed.emit()
        self.viewport().update()


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
