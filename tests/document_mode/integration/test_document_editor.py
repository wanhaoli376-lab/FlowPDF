from __future__ import annotations

import io

from PIL import Image
from PySide6.QtCore import QMimeData, QPoint, QPointF, QRect, QRectF, QSize, QSizeF, Qt
from PySide6.QtGui import QInputMethodEvent, QTextCursor, QWheelEvent
from PySide6.QtTest import QTest

from flowpdf.document_mode.editing import PaginatedTextEdit
from flowpdf.document_mode.models import (
    BlockImage,
    FlowDocument,
    PageBreak,
    PageSetup,
    Paragraph,
    Section,
    SourceReference,
    TextRun,
)
from flowpdf.document_mode.ui import DocumentEditorView


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
    mime.setHtml(
        '<p onclick="bad()" style="font-weight:bold;background-image:url(file:///secret)">'
        "安全内容<script>bad()</script><b>粗体</b>"
        '<img src="file:///C:/Users/example/secret.png">'
        '<a href="https://example.invalid">链接</a></p>'
    )
    cursor = editor.textCursor()
    cursor.movePosition(QTextCursor.MoveOperation.End)
    editor.setTextCursor(cursor)
    editor.insertFromMimeData(mime)
    assert "安全内容粗体链接" in editor.toPlainText()
    assert "bad()" not in editor.toPlainText()
    assert "file:///" not in editor.toHtml()
    assert "https://example.invalid" not in editor.toHtml()
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


def test_editor_page_break_survives_model_mapping_and_forces_new_page(qapp) -> None:
    document = FlowDocument.new()
    document.append_block(Paragraph(runs=[TextRun("第一页内容")]))
    editor = PaginatedTextEdit()
    editor.set_flow_document(document)
    editor.moveCursor(QTextCursor.MoveOperation.End)

    editor.insert_page_break()
    editor.insertPlainText("第二页内容")
    restored = editor.flow_document()

    assert any(isinstance(block, PageBreak) for block in restored.sections[0].blocks)
    assert editor.page_count >= 2
    editor.close()


def test_editor_preserves_run_sources_sections_and_visual_zoom(qapp) -> None:
    first_source = SourceReference(0, (10, 20, 80, 34), "第一节", "SourceFont", 0.9)
    second_source = SourceReference(1, (10, 20, 80, 34), "第二节", "SourceFont", 0.8)
    document = FlowDocument.new()
    document.sections = [
        Section(blocks=[Paragraph(runs=[TextRun("第一节", source_ref=first_source)])]),
        Section(blocks=[Paragraph(runs=[TextRun("第二节", source_ref=second_source)])]),
    ]
    view = DocumentEditorView()
    view.set_document(document)
    editor = view.editor
    first_block = editor.document().begin()
    before_height = editor.document().documentLayout().blockBoundingRect(first_block).height()
    before_page_width = editor.document().pageSize().width()

    editor.set_zoom_factor(1.4)
    after_height = editor.document().documentLayout().blockBoundingRect(first_block).height()
    restored = editor.flow_document()

    assert editor.zoom_factor == 1.4
    assert view.editor_canvas.transform().m11() == 1.4
    assert after_height == before_height
    assert (
        abs(before_page_width * view.editor_canvas.transform().m11() - 1.4 * before_page_width)
        < 0.01
    )
    assert len(restored.sections) == 2
    assert restored.sections[0].blocks[0].runs[0].source_ref == first_source
    assert restored.sections[1].blocks[0].runs[0].source_ref == second_source
    assert restored.plain_text == document.plain_text
    editor.actual_size()
    assert editor.zoom_factor == 1.0
    assert view.editor_canvas.transform().m11() == 1.0
    view.close()


def test_document_editor_view_displays_separated_physical_paper(qapp) -> None:
    document = _reflow_document()
    document.sections[0].blocks[0].runs[0].text += "分页纸张内容。" * 80
    view = DocumentEditorView()
    view.resize(720, 520)
    view.set_document(document)
    view.show()
    qapp.processEvents()

    presentation = view.editor.page_presentation
    assert presentation.page_count >= 2
    first = presentation.paper_rect(0)
    second = presentation.paper_rect(1)
    assert second.top() > first.bottom()
    assert view.editor.height() >= round(presentation.visual_size.height())

    rendered = view.editor.grab().toImage()
    paper_color = rendered.pixelColor(round(first.left() + 5), round(first.top() + 5))
    gap_color = rendered.pixelColor(
        round(first.center().x()),
        round((first.bottom() + second.top()) / 2),
    )
    assert paper_color.lightness() > gap_color.lightness() + 20
    content = presentation.content_rect(0).toAlignedRect()
    dark_content_pixels = sum(
        rendered.pixelColor(x, y).lightness() < 160
        for x in range(content.left(), min(content.right(), rendered.width() - 1), 2)
        for y in range(content.top(), min(content.bottom(), rendered.height() - 1), 2)
    )
    assert dark_content_pixels > 40
    view.close()


def test_clicking_text_on_a_later_visual_page_places_the_document_cursor(qapp) -> None:
    document = _reflow_document()
    document.sections[0].blocks[0].runs[0].text += "跨页点击命中。" * 80
    view = DocumentEditorView()
    view.resize(720, 520)
    view.set_document(document)
    view.show()
    qapp.processEvents()

    editor = view.editor
    snapshot = editor.pagination_snapshot()
    target_block_number = next(
        index for index, page_index in enumerate(snapshot.block_pages) if page_index > 0
    )
    block = editor.document().findBlockByNumber(target_block_number)
    block_rect = editor.document().documentLayout().blockBoundingRect(block)
    logical_point = QPointF(block_rect.left() + 8, block_rect.top() + 8)
    visual_point = editor.page_presentation.document_to_visual(logical_point)

    QTest.mouseClick(
        editor.viewport(),
        Qt.MouseButton.LeftButton,
        pos=visual_point.toPoint(),
    )

    assert editor.textCursor().blockNumber() == target_block_number
    view.close()


def test_mouse_drag_selects_text_across_physical_page_gap(qapp) -> None:
    document = _reflow_document()
    document.sections[0].blocks[0].runs[0].text += "跨页拖动选择。" * 80
    view = DocumentEditorView()
    view.resize(720, 520)
    view.set_document(document)
    view.show()
    qapp.processEvents()

    editor = view.editor
    snapshot = editor.pagination_snapshot()
    target_block_number = next(
        index for index, page_index in enumerate(snapshot.block_pages) if page_index > 0
    )
    first_block = editor.document().begin()
    target_block = editor.document().findBlockByNumber(target_block_number)
    first_rect = editor.document().documentLayout().blockBoundingRect(first_block)
    target_rect = editor.document().documentLayout().blockBoundingRect(target_block)
    start = editor.page_presentation.document_to_visual(
        QPointF(first_rect.left() + 4, first_rect.top() + 4)
    )
    end = editor.page_presentation.document_to_visual(
        QPointF(target_rect.right() - 4, target_rect.top() + 8)
    )

    QTest.mousePress(editor.viewport(), Qt.MouseButton.LeftButton, pos=start.toPoint())
    QTest.mouseMove(editor.viewport(), end.toPoint())
    QTest.mouseRelease(editor.viewport(), Qt.MouseButton.LeftButton, pos=end.toPoint())

    cursor = editor.textCursor()
    assert cursor.hasSelection()
    assert cursor.selectionStart() < target_block.position()
    assert cursor.selectionEnd() >= target_block.position()
    assert cursor.selectionEnd() <= target_block.position() + target_block.length()
    view.close()


def test_double_click_selects_a_word_on_a_later_physical_page(qapp) -> None:
    document = FlowDocument.new()
    document.page_setup = PageSetup(
        width_pt=260,
        height_pt=220,
        margin_top_pt=30,
        margin_bottom_pt=30,
        margin_left_pt=30,
        margin_right_pt=30,
    )
    document.append_block(Paragraph(runs=[TextRun("filler " * 180)]))
    document.append_block(Paragraph(runs=[TextRun("TargetWord trailing")]))
    view = DocumentEditorView()
    view.resize(720, 520)
    view.set_document(document)
    view.show()
    qapp.processEvents()

    editor = view.editor
    target = editor.document().findBlockByNumber(1)
    target_rect = editor.document().documentLayout().blockBoundingRect(target)
    visual = editor.page_presentation.document_to_visual(
        QPointF(target_rect.left() + 8, target_rect.top() + 8)
    )
    QTest.mouseDClick(
        editor.viewport(),
        Qt.MouseButton.LeftButton,
        pos=visual.toPoint(),
    )

    assert editor.textCursor().selectedText() == "TargetWord"
    view.close()


def test_later_page_cursor_scrolls_into_view_and_reports_visual_ime_rectangle(qapp) -> None:
    document = FlowDocument.new()
    document.page_setup = PageSetup(
        width_pt=260,
        height_pt=220,
        margin_top_pt=30,
        margin_bottom_pt=30,
        margin_left_pt=30,
        margin_right_pt=30,
    )
    for index in range(18):
        document.append_block(Paragraph(runs=[TextRun(f"第 {index + 1} 段候选框测试。" * 4)]))
    view = DocumentEditorView()
    view.resize(520, 360)
    view.set_document(document)
    view.show()
    qapp.processEvents()

    editor = view.editor
    target = editor.document().findBlockByNumber(15)
    cursor = QTextCursor(target)
    editor.setTextCursor(cursor)
    qapp.processEvents()
    snapshot = editor.pagination_snapshot()
    target_page = snapshot.block_pages[target.blockNumber()]
    candidate = editor.inputMethodQuery(Qt.InputMethodQuery.ImCursorRectangle)

    assert isinstance(candidate, (QRect, QRectF))
    assert editor.page_presentation.content_rect(target_page).contains(candidate.center())
    assert view.editor_canvas.verticalScrollBar().value() > 0
    view.close()


def test_document_editor_view_fits_physical_page_and_width(qapp) -> None:
    document = _reflow_document()
    view = DocumentEditorView()
    view.resize(760, 520)
    view.set_document(document)
    view.show()
    qapp.processEvents()
    viewport = QSizeF(view.editor_canvas.viewport().size())
    presentation = view.editor.page_presentation

    view.fit_width()
    expected_width = round(presentation.fit_width_factor(viewport), 2)
    assert view.editor.zoom_factor == expected_width
    assert abs(view.editor_canvas.transform().m11() - expected_width) < 0.001

    view.fit_page()
    expected_page = round(presentation.fit_page_factor(viewport), 2)
    assert view.editor.zoom_factor == expected_page
    assert abs(view.editor_canvas.transform().m11() - expected_page) < 0.001
    view.close()


def test_document_editor_renders_a_low_resolution_page_thumbnail(qapp) -> None:
    document = _reflow_document()
    editor = PaginatedTextEdit()
    editor.set_flow_document(document)

    thumbnail = editor.render_page_thumbnail(0, QSize(140, 180))

    assert not thumbnail.isNull()
    assert thumbnail.size() == QSize(140, 180)
    colors = {
        thumbnail.pixelColor(x, y).name()
        for x in range(0, thumbnail.width(), 10)
        for y in range(0, thumbnail.height(), 10)
    }
    assert "#ffffff" in colors
    assert len(colors) >= 3
    dark_content_pixels = sum(
        thumbnail.pixelColor(x, y).lightness() < 160
        for x in range(16, thumbnail.width() - 16)
        for y in range(16, thumbnail.height() - 16)
    )
    assert dark_content_pixels > 40
    editor.close()


def test_page_navigation_can_jump_into_a_page_inside_one_long_paragraph(qapp) -> None:
    document = _reflow_document()
    document.sections[0].blocks = [Paragraph(runs=[TextRun("连续长段落。" * 500)])]
    view = DocumentEditorView()
    view.resize(520, 360)
    view.set_document(document)
    view.show()
    qapp.processEvents()
    assert view.editor.page_count >= 3

    view.jump_to_page(1)
    qapp.processEvents()

    assert view.current_page == 1
    assert view.editor_canvas.verticalScrollBar().value() > 0
    view.close()


def test_mouse_wheel_scrolls_pages_and_ctrl_wheel_zooms(qapp) -> None:
    document = _reflow_document()
    document.sections[0].blocks = [Paragraph(runs=[TextRun("滚轮分页内容。" * 600)])]
    view = DocumentEditorView()
    view.resize(520, 360)
    view.set_document(document)
    view.show()
    qapp.processEvents()
    editor = view.editor
    canvas_scroll = view.editor_canvas.verticalScrollBar()
    assert canvas_scroll.maximum() > 0

    scroll_event = QWheelEvent(
        QPointF(80, 80),
        QPointF(80, 80),
        QPoint(),
        QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )
    assert qapp.sendEvent(editor.viewport(), scroll_event)
    assert canvas_scroll.value() > 0

    before_zoom = editor.zoom_factor
    zoom_event = QWheelEvent(
        QPointF(80, 80),
        QPointF(80, 80),
        QPoint(),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.ControlModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )
    assert qapp.sendEvent(editor.viewport(), zoom_event)
    assert editor.zoom_factor > before_zoom
    view.close()
