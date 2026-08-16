from __future__ import annotations

from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFontComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from flowpdf.backends.base import Color, TextStyle
from flowpdf.editing.text_editor import OverflowStrategy


class TextEditDialog(QDialog):
    def __init__(
        self,
        *,
        text: str = "",
        style: TextStyle | None = None,
        title: str = "添加文字",
        warning: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(520, 430)
        current = style or TextStyle()
        self._text_color = _qcolor(current.color)
        self._background_color = _qcolor(current.background_color or (1.0, 1.0, 1.0))

        root = QVBoxLayout(self)
        if warning:
            warning_label = QLabel(warning, self)
            warning_label.setWordWrap(True)
            warning_label.setStyleSheet(
                "background:#FEF3C7;color:#92400E;padding:8px;border-radius:4px;"
            )
            root.addWidget(warning_label)

        self.text_edit = QTextEdit(self)
        self.text_edit.setPlainText(text)
        self.text_edit.setAcceptRichText(False)
        root.addWidget(self.text_edit, 1)

        form = QFormLayout()
        self.font_combo = QFontComboBox(self)
        self.font_combo.setCurrentFont(QFont(current.font_family))
        self.size_spin = QDoubleSpinBox(self)
        self.size_spin.setRange(4.0, 144.0)
        self.size_spin.setDecimals(1)
        self.size_spin.setValue(current.font_size)
        form.addRow("字体", self.font_combo)
        form.addRow("字号", self.size_spin)

        style_row = QHBoxLayout()
        self.bold_check = QCheckBox("加粗", self)
        self.italic_check = QCheckBox("斜体", self)
        self.underline_check = QCheckBox("下划线", self)
        self.bold_check.setChecked(current.bold)
        self.italic_check.setChecked(current.italic)
        self.underline_check.setChecked(current.underline)
        # PyMuPDF textbox insertion needs concrete font variants. Keep these
        # controls visible but honest until the variant resolver is available.
        self.bold_check.setEnabled(False)
        self.italic_check.setEnabled(False)
        self.bold_check.setToolTip("当前版本尚未实现可靠的合成加粗")
        self.italic_check.setToolTip("当前版本尚未实现可靠的合成斜体")
        style_row.addWidget(self.bold_check)
        style_row.addWidget(self.italic_check)
        style_row.addWidget(self.underline_check)
        style_row.addStretch(1)
        form.addRow("字形", style_row)

        color_row = QHBoxLayout()
        self.text_color_button = QPushButton("文字颜色", self)
        self.background_check = QCheckBox("背景", self)
        self.background_check.setChecked(current.background_color is not None)
        self.background_button = QPushButton("背景颜色", self)
        self.text_color_button.clicked.connect(self._choose_text_color)
        self.background_button.clicked.connect(self._choose_background_color)
        color_row.addWidget(self.text_color_button)
        color_row.addWidget(self.background_check)
        color_row.addWidget(self.background_button)
        color_row.addStretch(1)
        form.addRow("颜色", color_row)

        self.opacity_spin = QDoubleSpinBox(self)
        self.opacity_spin.setRange(10, 100)
        self.opacity_spin.setSuffix("%")
        self.opacity_spin.setValue(current.opacity * 100)
        form.addRow("透明度", self.opacity_spin)

        self.alignment_combo = QComboBox(self)
        for label, value in (("左对齐", 0), ("居中", 1), ("右对齐", 2)):
            self.alignment_combo.addItem(label, value)
        self.alignment_combo.setCurrentIndex(max(0, min(2, current.alignment)))
        form.addRow("对齐", self.alignment_combo)

        self.overflow_combo = QComboBox(self)
        overflow_options = (
            ("自动换行", OverflowStrategy.WRAP),
            ("自动缩小字号", OverflowStrategy.AUTO_SHRINK),
            ("扩大文字框", OverflowStrategy.EXPAND),
            ("保持字号并提示溢出", OverflowStrategy.WARN),
        )
        for label, value in overflow_options:
            self.overflow_combo.addItem(label, value.value)
        selected = self.overflow_combo.findData(current.overflow.value)
        self.overflow_combo.setCurrentIndex(max(0, selected))
        form.addRow("文字溢出", self.overflow_combo)
        root.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._refresh_color_buttons()

    def text_and_style(self) -> tuple[str, TextStyle]:
        background = (
            _color_tuple(self._background_color) if self.background_check.isChecked() else None
        )
        return self.text_edit.toPlainText(), TextStyle(
            font_family=self.font_combo.currentFont().family(),
            font_size=self.size_spin.value(),
            color=_color_tuple(self._text_color),
            background_color=background,
            opacity=self.opacity_spin.value() / 100,
            bold=self.bold_check.isChecked(),
            italic=self.italic_check.isChecked(),
            underline=self.underline_check.isChecked(),
            alignment=int(self.alignment_combo.currentData()),
            overflow=OverflowStrategy(str(self.overflow_combo.currentData())),
        )

    def _choose_text_color(self) -> None:
        chosen = QColorDialog.getColor(self._text_color, self, "选择文字颜色")
        if chosen.isValid():
            self._text_color = chosen
            self._refresh_color_buttons()

    def _choose_background_color(self) -> None:
        chosen = QColorDialog.getColor(self._background_color, self, "选择背景颜色")
        if chosen.isValid():
            self._background_color = chosen
            self.background_check.setChecked(True)
            self._refresh_color_buttons()

    def _refresh_color_buttons(self) -> None:
        self.text_color_button.setStyleSheet(_button_style(self._text_color))
        self.background_button.setStyleSheet(_button_style(self._background_color))


def _qcolor(value: Color) -> QColor:
    return QColor.fromRgbF(*value)


def _color_tuple(color: QColor) -> Color:
    return color.redF(), color.greenF(), color.blueF()


def _button_style(color: QColor) -> str:
    foreground = "#FFFFFF" if color.lightnessF() < 0.45 else "#111827"
    return f"background:{color.name()};color:{foreground};"
