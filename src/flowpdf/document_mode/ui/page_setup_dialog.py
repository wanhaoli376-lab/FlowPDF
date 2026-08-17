from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QVBoxLayout,
)

from flowpdf.document_mode.models import PageSetup

_POINTS_PER_MM = 72.0 / 25.4


class PageSetupDialog(QDialog):
    def __init__(self, setup: PageSetup, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("页面设置")
        self.paper = QComboBox(self)
        self.paper.addItem("A4", "a4")
        self.paper.addItem("Letter", "letter")
        self.paper.addItem("自定义", "custom")
        self.orientation = QComboBox(self)
        self.orientation.addItem("纵向", "portrait")
        self.orientation.addItem("横向", "landscape")
        self.width = _millimeter_spin(self)
        self.height = _millimeter_spin(self)
        self.margin_top = _millimeter_spin(self)
        self.margin_bottom = _millimeter_spin(self)
        self.margin_left = _millimeter_spin(self)
        self.margin_right = _millimeter_spin(self)
        self.page_numbers = QComboBox(self)
        self.page_numbers.addItem("不显示", "none")
        self.page_numbers.addItem("底部居中", "bottom_center")
        self.page_numbers.addItem("底部右侧", "bottom_right")
        self.hide_first_page_number = QCheckBox("首页不显示页码", self)

        form = QFormLayout()
        form.addRow("纸张", self.paper)
        form.addRow("方向", self.orientation)
        form.addRow("宽度", self.width)
        form.addRow("高度", self.height)
        form.addRow("上边距", self.margin_top)
        form.addRow("下边距", self.margin_bottom)
        form.addRow("左边距", self.margin_left)
        form.addRow("右边距", self.margin_right)
        form.addRow("页码", self.page_numbers)
        form.addRow("", self.hide_first_page_number)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

        self._load(setup)
        self.paper.currentIndexChanged.connect(self._apply_preset)
        self.orientation.currentIndexChanged.connect(self._apply_orientation)
        self.width.valueChanged.connect(lambda _value: self._mark_custom())
        self.height.valueChanged.connect(lambda _value: self._mark_custom())

    def page_setup(self) -> PageSetup:
        width = self.width.value() * _POINTS_PER_MM
        height = self.height.value() * _POINTS_PER_MM
        return PageSetup(
            width_pt=width,
            height_pt=height,
            margin_top_pt=self.margin_top.value() * _POINTS_PER_MM,
            margin_bottom_pt=self.margin_bottom.value() * _POINTS_PER_MM,
            margin_left_pt=self.margin_left.value() * _POINTS_PER_MM,
            margin_right_pt=self.margin_right.value() * _POINTS_PER_MM,
            page_number_position=str(self.page_numbers.currentData()),
            first_page_number_hidden=self.hide_first_page_number.isChecked(),
        )

    def _load(self, setup: PageSetup) -> None:
        for widget, value in (
            (self.width, setup.width_pt),
            (self.height, setup.height_pt),
            (self.margin_top, setup.margin_top_pt),
            (self.margin_bottom, setup.margin_bottom_pt),
            (self.margin_left, setup.margin_left_pt),
            (self.margin_right, setup.margin_right_pt),
        ):
            widget.setValue(value / _POINTS_PER_MM)
        self.orientation.setCurrentIndex(0 if setup.height_pt >= setup.width_pt else 1)
        self.page_numbers.setCurrentIndex(
            max(0, self.page_numbers.findData(setup.page_number_position))
        )
        self.hide_first_page_number.setChecked(setup.first_page_number_hidden)
        size = sorted((round(setup.width_pt), round(setup.height_pt)))
        if size == sorted((595, 842)):
            self.paper.setCurrentIndex(0)
        elif size == sorted((612, 792)):
            self.paper.setCurrentIndex(1)
        else:
            self.paper.setCurrentIndex(2)

    def _apply_preset(self, _index: int) -> None:
        preset = self.paper.currentData()
        if preset == "custom":
            return
        width, height = (210.0, 297.0) if preset == "a4" else (215.9, 279.4)
        if self.orientation.currentData() == "landscape":
            width, height = height, width
        for widget, value in ((self.width, width), (self.height, height)):
            blocked = widget.blockSignals(True)
            widget.setValue(value)
            widget.blockSignals(blocked)

    def _apply_orientation(self, _index: int) -> None:
        wants_landscape = self.orientation.currentData() == "landscape"
        is_landscape = self.width.value() > self.height.value()
        if wants_landscape != is_landscape:
            width, height = self.height.value(), self.width.value()
            self.width.setValue(width)
            self.height.setValue(height)

    def _mark_custom(self) -> None:
        if not self.signalsBlocked():
            self.paper.setCurrentIndex(2)


def _millimeter_spin(parent) -> QDoubleSpinBox:
    value = QDoubleSpinBox(parent)
    value.setRange(0, 2000)
    value.setDecimals(1)
    value.setSuffix(" mm")
    return value
