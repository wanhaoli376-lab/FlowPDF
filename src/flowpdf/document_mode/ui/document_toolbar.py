from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QFont, QTextCharFormat
from PySide6.QtWidgets import (
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFontComboBox,
    QLabel,
    QToolBar,
)

from flowpdf.document_mode.editing import PaginatedTextEdit


class DocumentToolbar(QToolBar):
    """High-frequency character and paragraph tools for document mode."""

    insert_image_requested = Signal()
    export_pdf_requested = Signal()
    find_replace_requested = Signal()
    page_setup_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__("文档编辑工具", parent)
        self.setObjectName("documentModeToolbar")
        self.setMovable(False)
        self._editor: PaginatedTextEdit | None = None

        self.font_family = QFontComboBox(self)
        self.font_family.setMinimumWidth(150)
        self.font_size = QDoubleSpinBox(self)
        self.font_size.setRange(1, 512)
        self.font_size.setDecimals(1)
        self.font_size.setValue(11)
        self.font_size.setSuffix(" pt")
        self.font_size.setFixedWidth(82)
        self.addWidget(self.font_family)
        self.addWidget(self.font_size)
        self.addSeparator()

        self.bold_action = self._format_action("加粗", "Ctrl+B", checkable=True)
        self.italic_action = self._format_action("斜体", "Ctrl+I", checkable=True)
        self.underline_action = self._format_action("下划线", "Ctrl+U", checkable=True)
        self.strikeout_action = self._format_action("删除线", checkable=True)
        self.text_color_action = self._format_action("文字颜色")
        self.background_color_action = self._format_action("背景色")
        self.superscript_action = self._format_action("上标", checkable=True)
        self.subscript_action = self._format_action("下标", checkable=True)
        self.clear_format_action = self._format_action("清除格式")
        self.addSeparator()

        self.alignment_group = QActionGroup(self)
        self.alignment_group.setExclusive(True)
        self.left_action = self._alignment_action("左对齐", "left")
        self.center_action = self._alignment_action("居中", "center")
        self.right_action = self._alignment_action("右对齐", "right")
        self.justify_action = self._alignment_action("两端对齐", "justify")
        self.left_action.setChecked(True)

        self.line_spacing = QComboBox(self)
        for label, value in (("单倍", 1.0), ("1.15 倍", 1.15), ("1.5 倍", 1.5), ("2 倍", 2.0)):
            self.line_spacing.addItem(label, value)
        self.line_spacing.setCurrentIndex(1)
        self.addWidget(QLabel("行距", self))
        self.addWidget(self.line_spacing)
        self.bullet_action = self._format_action("项目符号", checkable=True)
        self.number_action = self._format_action("编号", checkable=True)
        self.first_line_indent_action = self._format_action("首行缩进", checkable=True)
        self.decrease_indent_action = self._format_action("减少缩进")
        self.increase_indent_action = self._format_action("增加缩进")
        self.addSeparator()

        self.insert_image_action = self._format_action("插入图片")
        self.page_break_action = self._format_action("分页符")
        self.page_setup_action = self._format_action("页面设置")
        self.find_replace_action = self._format_action("查找替换", "Ctrl+H")
        self.export_pdf_action = self._format_action("导出 PDF")

        self.insert_image_action.triggered.connect(self.insert_image_requested)
        self.find_replace_action.triggered.connect(self.find_replace_requested)
        self.page_setup_action.triggered.connect(self.page_setup_requested)
        self.export_pdf_action.triggered.connect(self.export_pdf_requested)

    def bind(self, editor: PaginatedTextEdit) -> None:
        if self._editor is not None:
            raise RuntimeError("文档工具栏不能重复绑定编辑器")
        self._editor = editor
        self.font_family.currentFontChanged.connect(
            lambda font: editor.set_font_family(font.family())
        )
        self.font_size.valueChanged.connect(editor.set_font_size)
        self.bold_action.triggered.connect(editor.set_bold)
        self.italic_action.triggered.connect(editor.set_italic)
        self.underline_action.triggered.connect(editor.set_underline)
        self.strikeout_action.triggered.connect(editor.set_strikeout)
        self.text_color_action.triggered.connect(self._choose_text_color)
        self.background_color_action.triggered.connect(self._choose_background_color)
        self.superscript_action.triggered.connect(self._set_superscript)
        self.subscript_action.triggered.connect(self._set_subscript)
        self.clear_format_action.triggered.connect(editor.clear_character_format)
        self.left_action.triggered.connect(
            lambda _checked=False: editor.set_paragraph_alignment("left")
        )
        self.center_action.triggered.connect(
            lambda _checked=False: editor.set_paragraph_alignment("center")
        )
        self.right_action.triggered.connect(
            lambda _checked=False: editor.set_paragraph_alignment("right")
        )
        self.justify_action.triggered.connect(
            lambda _checked=False: editor.set_paragraph_alignment("justify")
        )
        self.line_spacing.currentIndexChanged.connect(
            lambda index: editor.set_line_spacing(float(self.line_spacing.itemData(index)))
        )
        self.bullet_action.triggered.connect(
            lambda checked: editor.set_list_style("bullet" if checked else None)
        )
        self.number_action.triggered.connect(
            lambda checked: editor.set_list_style("number" if checked else None)
        )
        self.first_line_indent_action.triggered.connect(
            lambda checked: editor.set_paragraph_indents(first_line_pt=24 if checked else 0)
        )
        self.decrease_indent_action.triggered.connect(
            lambda _checked=False: editor.change_paragraph_indent(-18)
        )
        self.increase_indent_action.triggered.connect(
            lambda _checked=False: editor.change_paragraph_indent(18)
        )
        self.page_break_action.triggered.connect(editor.insert_page_break)
        editor.currentCharFormatChanged.connect(self._sync_character_format)
        editor.cursorPositionChanged.connect(self._sync_cursor_state)
        # PySide 6.11 / Windows can dereference an invalid default font-family
        # property while QTextEdit and QFontComboBox are both still constructing.
        # Read the editor's concrete QFont only after the event loop owns both.
        QTimer.singleShot(0, self._sync_from_editor)

    def _format_action(
        self,
        label: str,
        shortcut: str | None = None,
        *,
        checkable: bool = False,
    ) -> QAction:
        action = QAction(label, self)
        action.setCheckable(checkable)
        if shortcut:
            action.setShortcut(shortcut)
        self.addAction(action)
        return action

    def _alignment_action(self, label: str, value: str) -> QAction:
        action = self._format_action(label, checkable=True)
        action.setData(value)
        self.alignment_group.addAction(action)
        return action

    def _sync_character_format(self, value: QTextCharFormat) -> None:
        family = value.font().family()
        if family:
            blocked = self.font_family.blockSignals(True)
            self.font_family.setCurrentFont(QFont(family))
            self.font_family.blockSignals(blocked)
        points = value.fontPointSize()
        if points > 0:
            blocked = self.font_size.blockSignals(True)
            self.font_size.setValue(points)
            self.font_size.blockSignals(blocked)
        self.bold_action.setChecked(value.fontWeight() >= QFont.Weight.Bold)
        self.italic_action.setChecked(value.fontItalic())
        self.underline_action.setChecked(value.fontUnderline())
        self.strikeout_action.setChecked(value.fontStrikeOut())
        vertical = value.verticalAlignment()
        self.superscript_action.setChecked(
            vertical == QTextCharFormat.VerticalAlignment.AlignSuperScript
        )
        self.subscript_action.setChecked(
            vertical == QTextCharFormat.VerticalAlignment.AlignSubScript
        )

    def _sync_from_editor(self) -> None:
        if self._editor is None:
            return
        self._sync_character_format(self._editor.currentCharFormat())
        self._sync_cursor_state()

    def _sync_cursor_state(self) -> None:
        if self._editor is None:
            return
        alignment = self._editor.textCursor().blockFormat().alignment()
        if alignment & Qt.AlignmentFlag.AlignJustify:
            action = self.justify_action
        elif alignment & Qt.AlignmentFlag.AlignHCenter:
            action = self.center_action
        elif alignment & Qt.AlignmentFlag.AlignRight:
            action = self.right_action
        else:
            action = self.left_action
        action.setChecked(True)

    def _choose_text_color(self) -> None:
        if self._editor is None:
            return
        color = QColorDialog.getColor(parent=self)
        if color.isValid():
            self._editor.set_text_color(color)

    def _choose_background_color(self) -> None:
        if self._editor is None:
            return
        color = QColorDialog.getColor(parent=self)
        if color.isValid():
            self._editor.set_background_color(color)

    def _set_superscript(self, checked: bool) -> None:
        if self._editor is None:
            return
        if checked:
            self.subscript_action.setChecked(False)
            self._editor.set_subscript(False)
        self._editor.set_superscript(checked)

    def _set_subscript(self, checked: bool) -> None:
        if self._editor is None:
            return
        if checked:
            self.superscript_action.setChecked(False)
            self._editor.set_superscript(False)
        self._editor.set_subscript(checked)
