from __future__ import annotations

import copy
import json
from dataclasses import asdict

from PySide6.QtCore import QSizeF, Qt, QUrl
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextFormat,
    QTextImageFormat,
    QTextListFormat,
)

from flowpdf.document_mode.layout import PageGeometry
from flowpdf.document_mode.models import (
    BlockImage,
    FlowDocument,
    ImageAsset,
    PageBreak,
    PageSetup,
    Paragraph,
    ParagraphAlignment,
    ParagraphStyle,
    Section,
    SemanticRole,
    SourceReference,
    TextRun,
    TextStyle,
)

_ROLE_PROPERTY = int(QTextFormat.Property.UserProperty) + 101
_SOURCE_PROPERTY = int(QTextFormat.Property.UserProperty) + 102
_IMAGE_ALT_PROPERTY = int(QTextFormat.Property.UserProperty) + 103
_PAGE_BREAK_PROPERTY = int(QTextFormat.Property.UserProperty) + 104
_RUN_SOURCE_PROPERTY = int(QTextFormat.Property.UserProperty) + 105
_SECTION_PROPERTY = int(QTextFormat.Property.UserProperty) + 106
_ASSET_SCHEME = "flowpdf-asset"
BASE_FONT_SIZE_PT = 11.0


class DocumentMapper:
    """Map FlowDocument to and from one QTextDocument without making Qt canonical."""

    def __init__(self) -> None:
        self._template = FlowDocument.new()

    def populate(self, target: QTextDocument, source: FlowDocument) -> PageGeometry:
        self._template = copy.deepcopy(source)
        geometry = PageGeometry.from_setup(source.page_setup)
        target.setUndoRedoEnabled(False)
        target.clear()
        default_font = target.defaultFont()
        default_font.setPointSizeF(BASE_FONT_SIZE_PT)
        target.setDefaultFont(default_font)
        target.setDocumentMargin(0.0)
        target.setPageSize(QSizeF(geometry.content_width_px, geometry.content_height_px))
        self._install_resources(target, source)
        cursor = QTextCursor(target)
        first = True
        for section_index, section in enumerate(source.sections):
            for block in section.blocks:
                if not first:
                    cursor.insertBlock()
                first = False
                if isinstance(block, Paragraph):
                    self._insert_paragraph(cursor, block, geometry, section_index)
                elif isinstance(block, PageBreak):
                    self._insert_page_break(cursor, section_index)
                else:
                    self._insert_image(cursor, block, geometry, section_index)
        if first:
            self._apply_block_format(cursor, Paragraph(), geometry, 0)
        target.setUndoRedoEnabled(True)
        target.clearUndoRedoStacks()
        return geometry

    def to_model(self, source: QTextDocument) -> FlowDocument:
        document = copy.deepcopy(self._template)
        sections: list[Section] = []
        current_section: int | None = None
        block = source.begin()
        while block.isValid():
            section_value = block.blockFormat().property(_SECTION_PROPERTY)
            section_index = int(section_value) if section_value is not None else 0
            if current_section != section_index:
                sections.append(Section())
                current_section = section_index
            if block.blockFormat().boolProperty(_PAGE_BREAK_PROPERTY):
                sections[-1].blocks.append(PageBreak())
                block = block.next()
                continue
            image = self._block_image(block)
            sections[-1].blocks.append(image if image is not None else self._paragraph(block))
            block = block.next()
        document.sections = sections or [Section()]
        document.normalize()
        return document

    def register_asset(self, target: QTextDocument, asset: ImageAsset) -> None:
        if asset.asset_id in self._template.assets:
            raise ValueError("图片资产标识重复")
        self._template.add_asset(asset)
        image = QImage.fromData(asset.data)
        if image.isNull():
            raise ValueError("图片内容无法解码")
        target.addResource(
            QTextDocument.ResourceType.ImageResource,
            QUrl(f"{_ASSET_SCHEME}://{asset.asset_id}"),
            image,
        )

    @staticmethod
    def _install_resources(target: QTextDocument, source: FlowDocument) -> None:
        for asset in source.assets.values():
            image = QImage.fromData(asset.data)
            if image.isNull():
                continue
            target.addResource(
                QTextDocument.ResourceType.ImageResource,
                QUrl(f"{_ASSET_SCHEME}://{asset.asset_id}"),
                image,
            )

    def _insert_paragraph(
        self,
        cursor: QTextCursor,
        paragraph: Paragraph,
        geometry: PageGeometry,
        section_index: int,
    ) -> None:
        self._apply_block_format(cursor, paragraph, geometry, section_index)
        for run in paragraph.runs:
            cursor.insertText(run.text, _char_format(run.style, run.source_ref))
        if paragraph.style.list_kind is not None:
            list_format = QTextListFormat()
            list_format.setStyle(
                QTextListFormat.Style.ListDecimal
                if paragraph.style.list_kind == "number"
                else QTextListFormat.Style.ListDisc
            )
            list_format.setIndent(max(1, paragraph.style.list_level + 1))
            cursor.createList(list_format)

    def _apply_block_format(
        self,
        cursor: QTextCursor,
        paragraph: Paragraph,
        geometry: PageGeometry,
        section_index: int,
    ) -> None:
        block_format = _block_format(paragraph.style, geometry)
        block_format.setProperty(_ROLE_PROPERTY, paragraph.semantic_role.value)
        block_format.setProperty(_SECTION_PROPERTY, section_index)
        if paragraph.source_ref is not None:
            block_format.setProperty(
                _SOURCE_PROPERTY,
                json.dumps(asdict(paragraph.source_ref), ensure_ascii=False),
            )
        cursor.setBlockFormat(block_format)

    @staticmethod
    def _insert_page_break(cursor: QTextCursor, section_index: int) -> None:
        block_format = QTextBlockFormat()
        block_format.setProperty(_PAGE_BREAK_PROPERTY, True)
        block_format.setProperty(_SECTION_PROPERTY, section_index)
        block_format.setPageBreakPolicy(QTextFormat.PageBreakFlag.PageBreak_AlwaysBefore)
        cursor.setBlockFormat(block_format)

    @staticmethod
    def _insert_image(
        cursor: QTextCursor,
        image: BlockImage,
        geometry: PageGeometry,
        section_index: int,
    ) -> None:
        block_format = QTextBlockFormat()
        block_format.setAlignment(_qt_alignment(image.alignment))
        block_format.setProperty(_SECTION_PROPERTY, section_index)
        if image.source_ref is not None:
            block_format.setProperty(
                _SOURCE_PROPERTY,
                json.dumps(asdict(image.source_ref), ensure_ascii=False),
            )
        cursor.setBlockFormat(block_format)
        image_format = QTextImageFormat()
        image_format.setName(f"{_ASSET_SCHEME}://{image.asset_id}")
        image_format.setWidth(geometry.points_to_pixels(image.width_pt))
        image_format.setHeight(geometry.points_to_pixels(image.height_pt))
        image_format.setProperty(_IMAGE_ALT_PROPERTY, image.alt_text)
        cursor.insertImage(image_format)

    def _paragraph(self, block) -> Paragraph:
        runs: list[TextRun] = []
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.isValid() and fragment.text() and fragment.text() != "\ufffc":
                char_format = fragment.charFormat()
                runs.append(
                    TextRun(
                        fragment.text(),
                        _text_style(char_format),
                        _source_reference(char_format.property(_RUN_SOURCE_PROPERTY)),
                    )
                )
            iterator += 1
        block_format = block.blockFormat()
        role_value = block_format.property(_ROLE_PROPERTY)
        try:
            role = SemanticRole(str(role_value)) if role_value else SemanticRole.BODY
        except ValueError:
            role = SemanticRole.UNKNOWN
        return Paragraph(
            runs=runs,
            style=_paragraph_style(block),
            semantic_role=role,
            source_ref=_source_reference(block_format.property(_SOURCE_PROPERTY)),
        )

    def _block_image(self, block) -> BlockImage | None:
        iterator = block.begin()
        while not iterator.atEnd():
            fragment = iterator.fragment()
            if fragment.isValid() and fragment.charFormat().isImageFormat():
                image_format = fragment.charFormat().toImageFormat()
                url = QUrl(image_format.name())
                if url.scheme() != _ASSET_SCHEME:
                    return None
                geometry = PageGeometry.from_setup(self._template.page_setup)
                alignment = _alignment_name(block.blockFormat().alignment())
                return BlockImage(
                    asset_id=url.host(),
                    width_pt=geometry.pixels_to_points(image_format.width()),
                    height_pt=geometry.pixels_to_points(image_format.height()),
                    alignment=alignment,
                    alt_text=str(image_format.property(_IMAGE_ALT_PROPERTY) or ""),
                    source_ref=_source_reference(block.blockFormat().property(_SOURCE_PROPERTY)),
                )
            iterator += 1
        return None


def _char_format(
    style: TextStyle,
    source_ref: SourceReference | None = None,
) -> QTextCharFormat:
    value = QTextCharFormat()
    value.setFontFamilies([style.font_family])
    value.setFontPointSize(style.font_size_pt)
    value.setFontWeight(QFont.Weight.Bold if style.bold else QFont.Weight.Normal)
    value.setFontItalic(style.italic)
    value.setFontUnderline(style.underline)
    value.setFontStrikeOut(style.strikeout)
    value.setForeground(QColor(style.color))
    if style.background_color:
        value.setBackground(QColor(style.background_color))
    if style.superscript:
        value.setVerticalAlignment(QTextCharFormat.VerticalAlignment.AlignSuperScript)
    elif style.subscript:
        value.setVerticalAlignment(QTextCharFormat.VerticalAlignment.AlignSubScript)
    if source_ref is not None:
        value.setProperty(
            _RUN_SOURCE_PROPERTY,
            json.dumps(asdict(source_ref), ensure_ascii=False),
        )
    return value


def _text_style(value: QTextCharFormat) -> TextStyle:
    family = value.font().family()
    vertical = value.verticalAlignment()
    background = value.background().color()
    has_background = value.background().style() is not Qt.BrushStyle.NoBrush
    return TextStyle(
        font_family=family or "Microsoft YaHei",
        font_size_pt=value.fontPointSize() if value.fontPointSize() > 0 else BASE_FONT_SIZE_PT,
        bold=value.fontWeight() >= QFont.Weight.Bold,
        italic=value.fontItalic(),
        underline=value.fontUnderline(),
        strikeout=value.fontStrikeOut(),
        color=value.foreground().color().name(),
        background_color=(background.name() if has_background and background.isValid() else None),
        superscript=vertical == QTextCharFormat.VerticalAlignment.AlignSuperScript,
        subscript=vertical == QTextCharFormat.VerticalAlignment.AlignSubScript,
    )


def _block_format(style: ParagraphStyle, geometry: PageGeometry) -> QTextBlockFormat:
    value = QTextBlockFormat()
    value.setAlignment(_qt_alignment(style.alignment.value))
    value.setTextIndent(geometry.points_to_pixels(style.first_line_indent_pt))
    value.setLeftMargin(geometry.points_to_pixels(style.left_indent_pt))
    value.setRightMargin(geometry.points_to_pixels(style.right_indent_pt))
    value.setTopMargin(geometry.points_to_pixels(style.space_before_pt))
    value.setBottomMargin(geometry.points_to_pixels(style.space_after_pt))
    value.setLineHeight(
        style.line_spacing * 100,
        QTextBlockFormat.LineHeightTypes.ProportionalHeight.value,
    )
    value.setNonBreakableLines(style.keep_together)
    return value


def _paragraph_style(block) -> ParagraphStyle:
    value = block.blockFormat()
    geometry = PageGeometry.from_setup(PageSetup())
    line_height = value.lineHeight() / 100 if value.lineHeight() > 0 else 1.0
    text_list = block.textList()
    list_kind: str | None = None
    list_level = 0
    if text_list is not None:
        list_format = text_list.format()
        list_level = max(0, list_format.indent() - 1)
        list_kind = (
            "number"
            if list_format.style()
            in {
                QTextListFormat.Style.ListDecimal,
                QTextListFormat.Style.ListLowerAlpha,
                QTextListFormat.Style.ListUpperAlpha,
                QTextListFormat.Style.ListLowerRoman,
                QTextListFormat.Style.ListUpperRoman,
            }
            else "bullet"
        )
    return ParagraphStyle(
        alignment=ParagraphAlignment(_alignment_name(value.alignment())),
        first_line_indent_pt=geometry.pixels_to_points(value.textIndent()),
        left_indent_pt=geometry.pixels_to_points(value.leftMargin()),
        right_indent_pt=geometry.pixels_to_points(value.rightMargin()),
        line_spacing=line_height,
        space_before_pt=geometry.pixels_to_points(value.topMargin()),
        space_after_pt=geometry.pixels_to_points(value.bottomMargin()),
        keep_together=value.nonBreakableLines(),
        list_kind=list_kind,
        list_level=list_level,
    )


def _qt_alignment(value: str) -> Qt.AlignmentFlag:
    return {
        "left": Qt.AlignmentFlag.AlignLeft,
        "center": Qt.AlignmentFlag.AlignHCenter,
        "right": Qt.AlignmentFlag.AlignRight,
        "justify": Qt.AlignmentFlag.AlignJustify,
    }.get(value, Qt.AlignmentFlag.AlignLeft)


def _alignment_name(value: Qt.AlignmentFlag) -> str:
    if value & Qt.AlignmentFlag.AlignJustify:
        return "justify"
    if value & Qt.AlignmentFlag.AlignHCenter:
        return "center"
    if value & Qt.AlignmentFlag.AlignRight:
        return "right"
    return "left"


def _source_reference(value: object) -> SourceReference | None:
    if not value:
        return None
    try:
        data = json.loads(str(value))
        data["bbox"] = tuple(data["bbox"])
        return SourceReference(**data)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None
