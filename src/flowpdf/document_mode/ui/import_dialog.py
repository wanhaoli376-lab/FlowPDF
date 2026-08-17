from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from flowpdf.document_mode.importing import ImportReport


class ModeChoiceDialog(QDialog):
    """Explain import quality before the user chooses a PDF editing model."""

    def __init__(self, report: ImportReport, parent=None) -> None:
        super().__init__(parent)
        self.report = report
        self.choice: str | None = None
        self.setWindowTitle("选择 PDF 编辑模式")
        self.setMinimumWidth(520)

        quality = (
            "适合像 Word 一样编辑"
            if report.score >= 80
            else "可以使用，但可能需要调整"
            if report.score >= 60
            else "复杂版式，建议保持原版式"
        )
        summary = QLabel(
            f"文档编辑质量评分：{report.score}/100\n{quality}\n"
            f"检测到 {report.detected_columns} 栏、{report.paragraph_count} 个段落。",
            self,
        )
        summary.setWordWrap(True)

        document_button = QPushButton("像 Word 一样编辑", self)
        layout_button = QPushButton("保持原版式编辑", self)
        details_button = QPushButton("查看分析详情", self)
        recommended = document_button if report.recommended_mode == "document" else layout_button
        recommended.setDefault(True)
        document_button.clicked.connect(self._choose_document)
        layout_button.clicked.connect(lambda: self._finish("layout"))
        details_button.clicked.connect(self._show_details)

        buttons = QHBoxLayout()
        buttons.addWidget(document_button)
        buttons.addWidget(layout_button)
        buttons.addWidget(details_button)
        layout = QVBoxLayout(self)
        layout.addWidget(summary)
        layout.addLayout(buttons)

    @classmethod
    def choose(cls, parent, report: ImportReport) -> str | None:
        dialog = cls(report, parent)
        dialog.exec()
        return dialog.choice

    def _choose_document(self) -> None:
        if self.report.score < 60:
            answer = QMessageBox.warning(
                self,
                "复杂版式提醒",
                "文档模式会重新构建阅读顺序，双栏、公式或复杂定位内容可能改变排版。仍要继续吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer is not QMessageBox.StandardButton.Yes:
                return
        self._finish("document")

    def _finish(self, value: str) -> None:
        self.choice = value
        self.accept()

    def _show_details(self) -> None:
        warnings = "\n".join(f"• {item}" for item in self.report.warnings) or "未发现额外警告"
        QMessageBox.information(
            self,
            "文档导入分析",
            f"文字覆盖率：{self.report.text_coverage:.0%}\n"
            f"图片覆盖率：{self.report.image_coverage:.0%}\n"
            f"标题：{self.report.heading_count}\n"
            f"表格：{self.report.table_count}\n\n{warnings}",
        )
