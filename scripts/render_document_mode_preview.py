from __future__ import annotations

import argparse
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from flowpdf.application import create_application
from flowpdf.document_mode.importing import ImportReport, ImportResult
from flowpdf.document_mode.models import (
    FlowDocument,
    Paragraph,
    ParagraphAlignment,
    ParagraphStyle,
    SemanticRole,
    TextRun,
    TextStyle,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render the document-mode shell for visual QA")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    app, window = create_application(
        ["flowpdf-preview"],
        data_root=args.output.parent / ".flowpdf-preview-data",
    )
    document = FlowDocument.new(title="FlowPDF 文档编辑模式")
    document.append_block(
        Paragraph(
            runs=[TextRun("FlowPDF 文档编辑模式", TextStyle(font_size_pt=22, bold=True))],
            style=ParagraphStyle(
                alignment=ParagraphAlignment.CENTER,
                space_after_pt=16,
            ),
            semantic_role=SemanticRole.TITLE,
        )
    )
    document.append_block(
        Paragraph(
            runs=[TextRun("像文字处理器一样连续编辑单栏 PDF", TextStyle(font_size_pt=15))],
            semantic_role=SemanticRole.HEADING1,
        )
    )
    document.append_block(
        Paragraph(
            runs=[
                TextRun(
                    "点击正文即可放置光标。输入新内容时，当前段落会自动换行，后续段落随之下移；"
                    "内容超过页面后会继续流入下一页。删除内容时，文档会自动向上回流。"
                )
            ]
        )
    )
    document.append_block(
        Paragraph(
            runs=[TextRun("保存 .flowpdfproj 可以保留段落、格式、图片和编辑状态。")],
            style=ParagraphStyle(list_kind="bullet"),
            semantic_role=SemanticRole.LIST_ITEM,
        )
    )
    report = ImportReport(
        score=92,
        recommended_mode="document",
        detected_columns=1,
        text_coverage=0.94,
        image_coverage=0.02,
        paragraph_count=4,
        heading_count=2,
    )
    window.document_mode_controller.apply_import_result(
        ImportResult(document, report),
        "示例报告.pdf",
    )
    window.resize(1440, 900)
    window.show()
    app.processEvents()
    saved = window.grab().save(str(args.output))
    window.document_mode_controller.close_document(discard=True)
    window.close()
    app.processEvents()
    return 0 if saved else 1


if __name__ == "__main__":
    raise SystemExit(main())
