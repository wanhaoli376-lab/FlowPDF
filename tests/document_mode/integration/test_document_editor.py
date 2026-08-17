from __future__ import annotations

import io

from PIL import Image
from PySide6.QtCore import QMimeData, QRect, QRectF, Qt
from PySide6.QtGui import QInputMethodEvent, QTextCursor

from flowpdf.document_mode.editing import PaginatedTextEdit
from flowpdf.document_mode.models import BlockImage, FlowDocument, PageSetup, Paragraph, TextRun


def _reflow_document() -> FlowDocument:
    document = FlowDocument.new(title="自动重排测试")
    document.page_setup = PageSetup(
        width_pt=260,
        height_pt=220,
        margin_top_pt=30,
        margin_bottom_pt=30,
        margin_left_pt=30,
        margin_right_pt=30,
    )
    document.append_block(Paragraph(runs=[TextRun("第一段开头。")]))
    document.append_block(
        Paragraph(runs=[TextRun("第二段应该随着第一段内容自动向下移动，然后在删除后向上回流。")])
    )
    document.append_block(Paragraph(runs=[TextRun("最后一段用于观察分页数量。")]))
    return document


def test_long_chinese_edit_pushes_following_paragraphs_across_pages_and_reflows_back(qapp) -> None:
    editor = PaginatedTextEdit()
    editor.set_flow_document(_reflow_document())
    before = editor.pagination_snapshot()
    inserted = "新增的中文内容会自动换行并推动后续段落。" * 12
    cursor = QTextCursor(editor.document())
    insertion_position = len("第一段")
    cursor.setPosition(insertion_position)

    cursor.insertText(inserted)
    after_insert = editor.pagination_snapshot()

    assert after_insert.block_line_counts[0] > before.block_line_counts[0]
    assert after_insert.block_tops[1] > before.block_tops[1]
    assert after_insert.page_count > before.page_count

    cursor.setPosition(insertion_position)
    cursor.setPosition(insertion_position + len(inserted), QTextCursor.MoveMode.KeepAnchor)
    cursor.removeSelectedText()
    after_delete = editor.pagination_snapshot()

    assert after_delete.block_tops[1] == before.block_tops[1]
    assert after_delete.page_count == before.page_count
    editor.close()


def test_editor_applies_character_and_paragraph_formats_and_syncs_model(qapp) -> None:
    document = FlowDocument.new()
    document.append_block(Paragraph(runs=[TextRun("中文 English")]))
    editor = PaginatedTextEdit()
    editor.set_flow_document(document)
    cursor = editor.textCursor()
    cursor.setPosition(0)
    cursor.setPosition(2, QTextCursor.MoveMode.KeepAnchor)
    editor.setTextCursor(cursor)

    editor.set_bold(True)
    editor.set_font_size(18)
    editor.set_paragraph_alignment("center")
    editor.set_line_spacing(1.5)
    editor.set_paragraph_indents(first_line_pt=24, left_pt=12, right_pt=6)
    updated = editor.flow_document()

    paragraph = updated.sections[0].blocks[0]
    assert isinstance(paragraph, Paragraph)
    chinese_run = next(run for run in paragraph.runs if run.text == "中文")
    assert chinese_run.style.bold is True
    assert chinese_run.style.font_size_pt == 18
    assert paragraph.style.alignment.value == "center"
    assert paragraph.style.line_spacing == 1.5
    assert paragraph.style.first_line_indent_pt == 24
    assert paragraph.style.left_indent_pt == 12
    assert paragraph.style.right_indent_pt == 6
    editor.close()


def test_editor_supports_paragraph_merge_undo_redo_find_replace_and_safe_rich_paste(qapp) -> None:
    document = FlowDocument.new()
    document.append_block(Paragraph(runs=[TextRun("第一段 FlowPDF")]))
    document.append_block(Paragraph(runs=[TextRun("第二段 FlowPDF")]))
    editor = PaginatedTextEdit()
    editor.set_flow_document(document)
    second = editor.document().findBlockByNumber(1)
    cursor = QTextCursor(second)
    cursor.deletePreviousChar()
    assert editor.document().blockCount() == 1
    assert "第一段 FlowPDF第二段" in editor.toPlainText()

    editor.undo()
    assert editor.document().blockCount() == 2
    editor.redo()
    assert editor.document().blockCount() == 1
    assert editor.replace_all("FlowPDF", "文档模式") == 2
    assert editor.find_text("文档模式") is True

    mime = QMimeData()
    mime.setHtml('<p onclick="bad()">安全内容<script>bad()</script><b>粗体</b></p>')
    cursor = editor.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    editor.setTextCursor(cursor)
    editor.insertFromMimeData(mime)
    assert "安全内容粗体" in editor.toPlainText()
    assert "bad()" not in editor.toPlainText()
    editor.close()


def test_editor_inserts_resizes_aligns_deletes_and_undoes_image(qapp) -> None:
    document = FlowDocument.new()
    document.append_block(Paragraph(runs=[TextRun("图片之前")]))
    image = Image.new("RGB", (200, 100), "#16a34a")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    editor = PaginatedTextEdit()
    editor.set_flow_document(document)
    cursor = editor.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    editor.setTextCursor(cursor)

    asset_id = editor.insert_image(
        buffer.getvalue(),
        media_type="image/png",
        width_pt=120,
        alt_text="绿色示例图",
    )
    assert editor.update_image(
        asset_id,
        width_pt=180,
        alignment="right",
        alt_text="调整后的绿色图",
    )
    updated = editor.flow_document()
    image_block = next(
        block for block in updated.sections[0].blocks if isinstance(block, BlockImage)
    )
    assert image_block.width_pt == 180
    assert image_block.height_pt == 90
    assert image_block.alignment == "right"
    assert image_block.alt_text == "调整后的绿色图"
    assert updated.assets[asset_id].data == buffer.getvalue()

    assert editor.delete_image(asset_id)
    assert not any(
        isinstance(block, BlockImage) for block in editor.flow_document().sections[0].blocks
    )
    editor.undo()
    assert any(isinstance(block, BlockImage) for block in editor.flow_document().sections[0].blocks)
    editor.close()


def test_editor_creates_bullet_and_numbered_lists_in_document_model(qapp) -> None:
    document = FlowDocument.new()
    document.append_block(Paragraph(runs=[TextRun("列表项")]))
    editor = PaginatedTextEdit()
    editor.set_flow_document(document)

    editor.set_list_style("bullet")
    bullet = editor.flow_document().sections[0].blocks[0]
    assert isinstance(bullet, Paragraph)
    assert bullet.style.list_kind == "bullet"

    editor.set_list_style("number")
    numbered = editor.flow_document().sections[0].blocks[0]
    assert isinstance(numbered, Paragraph)
    assert numbered.style.list_kind == "number"
    editor.close()


def test_editor_accepts_chinese_input_method_commit_and_reports_candidate_rectangle(qapp) -> None:
    document = FlowDocument.new()
    document.append_block(Paragraph(runs=[TextRun("光标：")]))
    editor = PaginatedTextEdit()
    editor.set_flow_document(document)
    cursor = editor.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    editor.setTextCursor(cursor)
    editor.show()
    editor.setFocus()
    event = QInputMethodEvent()
    event.setCommitString("中文输入")

    assert qapp.sendEvent(editor, event)
    candidate_rect = editor.inputMethodQuery(Qt.InputMethodQuery.ImCursorRectangle)

    assert editor.toPlainText() == "光标：中文输入"
    assert isinstance(candidate_rect, (QRect, QRectF))
    assert candidate_rect.width() >= 0
    assert candidate_rect.height() > 0
    editor.close()


def test_editor_selects_copies_deletes_undoes_and_redoes_across_pages(qapp) -> None:
    document = FlowDocument.new()
    document.page_setup = PageSetup(
        width_pt=260,
        height_pt=220,
        margin_top_pt=30,
        margin_bottom_pt=30,
        margin_left_pt=30,
        margin_right_pt=30,
    )
    for index in range(10):
        document.append_block(Paragraph(runs=[TextRun(f"第 {index + 1} 段跨页选择内容。" * 2)]))
    editor = PaginatedTextEdit()
    editor.set_flow_document(document)
    snapshot = editor.pagination_snapshot()
    first_second_page = snapshot.block_pages.index(1)
    last_first_page = first_second_page - 1
    start_block = editor.document().findBlockByNumber(last_first_page)
    end_block = editor.document().findBlockByNumber(first_second_page)
    cursor = QTextCursor(editor.document())
    cursor.setPosition(start_block.position() + max(1, start_block.length() // 2))
    cursor.setPosition(
        end_block.position() + max(1, end_block.length() // 2),
        QTextCursor.MoveMode.KeepAnchor,
    )
    selected = cursor.selectedText()
    editor.setTextCursor(cursor)

    editor.copy()
    assert qapp.clipboard().text().replace("\n", "\u2029") == selected
    cursor.removeSelectedText()
    assert selected not in editor.toPlainText()
    editor.undo()
    assert selected.replace("\u2029", "\n") in editor.toPlainText()
    editor.redo()
    assert selected not in editor.toPlainText()
    editor.close()
