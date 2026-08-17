from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QDragEnterEvent,
    QDropEvent,
    QKeySequence,
)
from PySide6.QtWidgets import (
    QDockWidget,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from flowpdf.backends.base import AnnotationInfo, PageInfo
from flowpdf.document_mode.importing import ImportReport
from flowpdf.document_mode.models import FlowDocument
from flowpdf.document_mode.ui import DocumentEditorView, DocumentToolbar
from flowpdf.editing.tools import ToolMode
from flowpdf.i18n import tr
from flowpdf.rendering.render_scheduler import RenderScheduler, RenderSource
from flowpdf.ui.annotation_panel import AnnotationPanel
from flowpdf.ui.document_view import DocumentView
from flowpdf.ui.search_panel import SearchPanel
from flowpdf.ui.thumbnail_panel import ThumbnailPanel
from flowpdf.ui.welcome_page import WelcomePage


class MainWindow(QMainWindow):
    """Three-column Qt shell; application behavior lives in its controller."""

    pdf_dropped = Signal(str)
    recent_file_requested = Signal(str)
    theme_requested = Signal(str)

    def __init__(self, scheduler: RenderScheduler) -> None:
        super().__init__()
        self.scheduler = scheduler
        self.controller: Any | None = None
        self.document_mode_controller: Any | None = None
        self.lifecycle_controller: Any | None = None
        self.active_mode = "welcome"
        self._page_count = 0
        self._closing = False
        self.setObjectName("mainWindow")
        self.setWindowTitle("FlowPDF")
        self.resize(1280, 820)
        self.setMinimumSize(900, 600)
        self.setAcceptDrops(True)

        self._workspace = QStackedWidget(self)
        self._welcome = WelcomePage(self._workspace)
        self.document_view = DocumentView(scheduler, self._workspace)
        self.document_editor_view = DocumentEditorView(self._workspace)
        self._workspace.addWidget(self._welcome)
        self._workspace.addWidget(self.document_view)
        self._workspace.addWidget(self.document_editor_view)
        self.setCentralWidget(self._workspace)

        self._create_actions()
        self._create_menus()
        self._create_toolbar()
        self._create_search_bar()
        self._create_left_dock()
        self._create_right_dock()
        self._create_status_bar()
        self._connect_view_controls()
        self.set_document_enabled(False)
        self._apply_mode_ui()

    def attach_controller(self, controller: Any) -> None:
        self.controller = controller

    def attach_document_mode_controller(self, controller: Any) -> None:
        self.document_mode_controller = controller

    def show_document(
        self,
        source: RenderSource,
        page_infos: list[PageInfo],
        *,
        title: str,
        revision: int = 0,
        annotations: list[AnnotationInfo] | None = None,
    ) -> None:
        self._page_count = len(page_infos)
        self.document_view.set_document(source, page_infos, revision=revision)
        self.thumbnail_panel.set_document(source, page_infos, revision=revision)
        self.annotation_panel.set_annotations(annotations or [])
        self.page_spin.setRange(1, max(1, self._page_count))
        self.page_spin.setValue(1)
        self._workspace.setCurrentWidget(self.document_view)
        self.active_mode = "layout"
        self._apply_mode_ui()
        self.setWindowTitle(f"{title} — FlowPDF")
        self.set_document_enabled(True)
        self._update_page_status(0)

    def refresh_document(
        self,
        source: RenderSource,
        page_infos: list[PageInfo],
        *,
        revision: int,
        annotations: list[AnnotationInfo] | None = None,
    ) -> None:
        self._page_count = len(page_infos)
        self.document_view.update_snapshot(source, page_infos, revision=revision)
        self.thumbnail_panel.set_document(source, page_infos, revision=revision)
        self.annotation_panel.set_annotations(annotations or [])
        self.page_spin.setRange(1, max(1, self._page_count))
        self._update_page_status(self.document_view.current_page)

    def clear_document(self) -> None:
        self.document_view.clear_document()
        self.thumbnail_panel.clear_document()
        self.annotation_panel.clear()
        self.search_panel.set_results(0, 0)
        self._page_count = 0
        if self.active_mode != "document":
            self.active_mode = "welcome"
            self._workspace.setCurrentWidget(self._welcome)
            self.setWindowTitle("FlowPDF")
            self.page_status.setText(tr("MainWindow", "未打开文档"))
            self._apply_mode_ui()
        self.set_document_enabled(False)

    def show_document_editor(
        self,
        document: FlowDocument,
        report: ImportReport | None = None,
    ) -> None:
        self.document_editor_view.set_document(document, report)
        self._workspace.setCurrentWidget(self.document_editor_view)
        self.active_mode = "document"
        self.set_document_enabled(False)
        self.document_editor_view.editor.setEnabled(True)
        self.document_editor_view.editor.setFocus()
        self.set_document_mode_enabled(True)
        self._apply_mode_ui()
        self._set_document_navigation(document)
        self.set_import_report(report)
        self.mode_status.setText("文档编辑模式")
        self.update_document_word_count(len(document.plain_text.replace("\n", "")))
        self.update_document_mode_status(
            self.document_editor_view.current_page,
            self.document_editor_view.editor.page_count,
        )

    def clear_document_editor(self) -> None:
        self.document_editor_view.clear_document()
        if self.active_mode == "document":
            self.active_mode = "welcome"
            self._workspace.setCurrentWidget(self._welcome)
            self.setWindowTitle("FlowPDF")
            self.page_status.setText(tr("MainWindow", "未打开文档"))
            self.mode_status.setText("")
            self.word_status.setText("")
            self._apply_mode_ui()

    def update_document_mode_status(self, page_index: int, page_count: int) -> None:
        if self.active_mode != "document":
            return
        count = max(1, page_count)
        page = min(max(0, page_index), count - 1)
        self.page_status.setText(f"第 {page + 1} 页，共 {count} 页")
        self.total_pages_label.setText(f"/ {count}")
        if self.document_page_list.count() != count:
            self.document_page_list.clear()
            self.document_page_list.addItems([f"第 {index + 1} 页" for index in range(count)])
        self.document_page_list.setCurrentRow(page)

    def update_document_word_count(self, count: int) -> None:
        self.word_status.setText(f"字符 {max(0, count)}")

    def selected_pages(self) -> list[int]:
        pages = self.thumbnail_panel.selected_pages()
        return pages or ([self.document_view.current_page] if self._page_count else [])

    def set_document_enabled(self, enabled: bool) -> None:
        for action in (
            self.save_action,
            self.save_as_action,
            self.close_action,
            self.undo_action,
            self.redo_action,
            self.search_action,
            self.zoom_in_action,
            self.zoom_out_action,
            self.fit_page_action,
            self.fit_width_action,
            self.actual_size_action,
            self.delete_pages_action,
            self.duplicate_pages_action,
            self.rotate_pages_action,
            self.insert_blank_action,
            self.insert_pdf_action,
            self.export_pages_action,
            self.merge_pdf_action,
            self.split_pdf_action,
            *self.tool_actions.values(),
        ):
            action.setEnabled(enabled)
        self.page_spin.setEnabled(enabled)
        if not enabled:
            self.document_view.set_tool(ToolMode.SELECT)

    def set_document_mode_enabled(self, enabled: bool) -> None:
        for action in (
            self.save_action,
            self.save_as_action,
            self.close_action,
            self.search_action,
            self.zoom_in_action,
            self.zoom_out_action,
            self.actual_size_action,
        ):
            action.setEnabled(enabled)
        self.document_toolbar.setEnabled(enabled)

    def set_import_report(self, report: ImportReport | None) -> None:
        if report is None:
            self.import_report_label.setText("从工程文件打开，未重新分析来源 PDF。")
            return
        details = [
            f"质量评分：{report.score}/100",
            f"检测栏数：{report.detected_columns}",
            f"段落：{report.paragraph_count}",
            f"标题：{report.heading_count}",
        ]
        if report.warnings:
            details.append("\n".join(f"• {warning}" for warning in report.warnings[:5]))
        self.import_report_label.setText("\n".join(details))

    def set_busy(self, busy: bool, message: str = "") -> None:
        self.progress_bar.setVisible(busy)
        if busy:
            self.progress_bar.setRange(0, 0)
            self.save_status.setText(message or "正在处理…")
        else:
            self.progress_bar.setRange(0, 100)
        self.open_action.setEnabled(not busy)
        self.new_action.setEnabled(not busy)

    def set_progress(self, value: int, message: str) -> None:
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(value)
        self.save_status.setText(message)

    def set_saved_status(self, message: str) -> None:
        self.save_status.setText(message)

    def set_history_state(
        self,
        *,
        can_undo: bool,
        can_redo: bool,
        undo_text: str | None = None,
        redo_text: str | None = None,
    ) -> None:
        self.undo_action.setEnabled(can_undo)
        self.redo_action.setEnabled(can_redo)
        self.undo_action.setText(f"撤销 {undo_text}" if undo_text else "撤销")
        self.redo_action.setText(f"重做 {redo_text}" if redo_text else "重做")

    def set_recent_files(self, paths: list[Path]) -> None:
        self.recent_menu.clear()
        for path in paths:
            action = QAction(path.name, self.recent_menu)
            action.setToolTip(str(path))
            action.triggered.connect(
                lambda _checked=False, value=str(path): self.recent_file_requested.emit(value)
            )
            self.recent_menu.addAction(action)
        self.recent_menu.setEnabled(bool(paths))

    def show_search(self) -> None:
        self.search_toolbar.show()
        self.search_panel.open_and_focus()

    def hide_search(self) -> None:
        self.search_toolbar.hide()
        if self.active_mode == "document":
            self.document_editor_view.editor.setFocus()
        else:
            self.document_view.setFocus()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if _first_pdf_path(event.mimeData()) is not None:
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        path = _first_pdf_path(event.mimeData())
        if path is not None:
            self.pdf_dropped.emit(str(path))
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._closing:
            event.accept()
            return
        lifecycle = self.lifecycle_controller or self.document_mode_controller or self.controller
        if lifecycle is not None and not lifecycle.request_close():
            event.ignore()
            return
        self._closing = True
        self.document_view.close()
        self.thumbnail_panel.close()
        if not self.scheduler.shutdown():
            self._closing = False
            self.show_error("无法退出", "后台渲染任务未能及时结束，请稍后再试。")
            event.ignore()
            return
        event.accept()

    def force_close_after_save(self) -> None:
        self.close()

    def show_error(self, title: str, message: str) -> None:
        QMessageBox.critical(self, title, message)

    def _create_actions(self) -> None:
        self.document_mode_action = QAction("文档编辑", self)
        self.layout_mode_action = QAction("版面编辑", self)
        self.document_mode_action.setCheckable(True)
        self.layout_mode_action.setCheckable(True)
        self.mode_group = QActionGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_group.addAction(self.document_mode_action)
        self.mode_group.addAction(self.layout_mode_action)

        self.open_action = QAction(tr("MainWindow", "打开"), self)
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.new_action = QAction(tr("MainWindow", "新建空白 PDF"), self)
        self.new_action.setShortcut(QKeySequence.StandardKey.New)
        self.open_project_action = QAction("打开 FlowPDF 工程…", self)
        self.save_action = QAction(tr("MainWindow", "保存"), self)
        self.save_action.setShortcut(QKeySequence.StandardKey.Save)
        self.save_as_action = QAction(tr("MainWindow", "另存为副本"), self)
        self.save_as_action.setShortcut(QKeySequence.StandardKey.SaveAs)
        self.close_action = QAction(tr("MainWindow", "关闭文档"), self)
        self.quit_action = QAction(tr("MainWindow", "退出"), self)
        self.quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        self.quit_action.triggered.connect(self.close)

        self.undo_action = QAction(tr("MainWindow", "撤销"), self)
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.redo_action = QAction(tr("MainWindow", "重做"), self)
        self.redo_action.setShortcut(QKeySequence.StandardKey.Redo)
        self.search_action = QAction(tr("MainWindow", "搜索"), self)
        self.search_action.setShortcut(QKeySequence.StandardKey.Find)

        self.zoom_in_action = QAction(tr("MainWindow", "放大"), self)
        self.zoom_in_action.setShortcuts([QKeySequence.ZoomIn, QKeySequence("Ctrl++")])
        self.zoom_out_action = QAction(tr("MainWindow", "缩小"), self)
        self.zoom_out_action.setShortcut(QKeySequence.ZoomOut)
        self.actual_size_action = QAction(tr("MainWindow", "实际大小"), self)
        self.fit_page_action = QAction(tr("MainWindow", "适应页面"), self)
        self.fit_page_action.setShortcut(QKeySequence("Ctrl+0"))
        self.fit_width_action = QAction(tr("MainWindow", "适应宽度"), self)
        self.continuous_action = QAction(tr("MainWindow", "连续滚动"), self)
        self.continuous_action.setCheckable(True)
        self.continuous_action.setChecked(True)
        self.cache_settings_action = QAction("渲染缓存设置…", self)

        self.light_theme_action = QAction("浅色主题", self)
        self.dark_theme_action = QAction("深色主题", self)
        self.light_theme_action.setCheckable(True)
        self.dark_theme_action.setCheckable(True)
        self.theme_group = QActionGroup(self)
        self.theme_group.setExclusive(True)
        self.theme_group.addAction(self.light_theme_action)
        self.theme_group.addAction(self.dark_theme_action)
        self.light_theme_action.setChecked(True)

        self.delete_pages_action = QAction("删除所选页面", self)
        self.delete_pages_action.setShortcut(QKeySequence(Qt.Key.Key_Delete))
        self.duplicate_pages_action = QAction("复制所选页面", self)
        self.rotate_pages_action = QAction("顺时针旋转", self)
        self.insert_blank_action = QAction("插入空白页面", self)
        self.insert_pdf_action = QAction("从 PDF 插入页面", self)
        self.export_pages_action = QAction("导出所选页面", self)
        self.merge_pdf_action = QAction("合并 PDF…", self)
        self.split_pdf_action = QAction("拆分为单页 PDF…", self)

        self.tool_group = QActionGroup(self)
        self.tool_group.setExclusive(True)
        tool_labels = {
            ToolMode.SELECT: "选择/平移",
            ToolMode.ADD_TEXT: "添加文字",
            ToolMode.ADD_IMAGE: "添加图片",
            ToolMode.HIGHLIGHT: "高亮",
            ToolMode.UNDERLINE: "下划线批注",
            ToolMode.STRIKEOUT: "删除线",
            ToolMode.NOTE: "便签",
            ToolMode.LINE: "直线",
            ToolMode.ARROW: "箭头",
            ToolMode.RECTANGLE: "矩形",
            ToolMode.ELLIPSE: "椭圆",
            ToolMode.PERMANENT_DELETE: "永久擦除",
        }
        self.tool_actions: dict[ToolMode, QAction] = {}
        for tool, label in tool_labels.items():
            action = QAction(label, self)
            action.setCheckable(True)
            action.setData(tool.value)
            self.tool_group.addAction(action)
            self.tool_actions[tool] = action
        self.tool_actions[ToolMode.SELECT].setChecked(True)
        self.tool_actions[ToolMode.SELECT].setShortcut(QKeySequence(Qt.Key.Key_Escape))

    def _create_menus(self) -> None:
        file_menu = self.menuBar().addMenu(tr("MainWindow", "文件"))
        file_menu.addActions([self.new_action, self.open_action, self.open_project_action])
        self.recent_menu = file_menu.addMenu(tr("MainWindow", "最近打开"))
        file_menu.addSeparator()
        file_menu.addActions([self.save_action, self.save_as_action, self.close_action])
        file_menu.addSeparator()
        file_menu.addAction(self.quit_action)

        edit_menu = self.menuBar().addMenu(tr("MainWindow", "编辑"))
        edit_menu.addActions([self.undo_action, self.redo_action, self.search_action])
        self.page_menu = self.menuBar().addMenu(tr("MainWindow", "页面"))
        self.page_menu.addActions(
            [
                self.insert_blank_action,
                self.insert_pdf_action,
                self.duplicate_pages_action,
                self.rotate_pages_action,
                self.export_pages_action,
                self.merge_pdf_action,
                self.split_pdf_action,
                self.delete_pages_action,
            ]
        )
        self.annotation_menu = self.menuBar().addMenu(tr("MainWindow", "批注"))
        self.annotation_menu.addActions(
            [
                self.tool_actions[ToolMode.HIGHLIGHT],
                self.tool_actions[ToolMode.UNDERLINE],
                self.tool_actions[ToolMode.STRIKEOUT],
                self.tool_actions[ToolMode.NOTE],
                self.tool_actions[ToolMode.LINE],
                self.tool_actions[ToolMode.ARROW],
                self.tool_actions[ToolMode.RECTANGLE],
                self.tool_actions[ToolMode.ELLIPSE],
            ]
        )
        self.signature_menu = self.menuBar().addMenu(tr("MainWindow", "填写与签名"))
        self.signature_menu.addActions(
            [
                self.tool_actions[ToolMode.ADD_TEXT],
                self.tool_actions[ToolMode.ADD_IMAGE],
            ]
        )
        edit_menu.addSeparator()
        edit_menu.addAction(self.tool_actions[ToolMode.PERMANENT_DELETE])
        self.view_menu = self.menuBar().addMenu(tr("MainWindow", "视图"))
        self.view_menu.addActions(
            [
                self.zoom_in_action,
                self.zoom_out_action,
                self.actual_size_action,
                self.fit_page_action,
                self.fit_width_action,
                self.continuous_action,
            ]
        )
        theme_menu = self.view_menu.addMenu("主题")
        theme_menu.addActions([self.light_theme_action, self.dark_theme_action])
        self.view_menu.addAction(self.cache_settings_action)

    def _create_toolbar(self) -> None:
        self.mode_toolbar = QToolBar("编辑模式", self)
        self.mode_toolbar.setObjectName("modeToolbar")
        self.mode_toolbar.setMovable(False)
        self.mode_toolbar.addActions([self.document_mode_action, self.layout_mode_action])
        self.addToolBar(self.mode_toolbar)

        self.layout_toolbar = QToolBar(tr("MainWindow", "常用工具"), self)
        self.layout_toolbar.setObjectName("mainToolbar")
        self.layout_toolbar.setMovable(False)
        self.layout_toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.layout_toolbar.addActions([self.open_action, self.save_action])
        self.layout_toolbar.addSeparator()
        self.layout_toolbar.addActions([self.undo_action, self.redo_action])
        self.layout_toolbar.addSeparator()
        self.layout_toolbar.addActions(
            [self.search_action, self.zoom_out_action, self.zoom_in_action]
        )
        self.layout_toolbar.addSeparator()
        self.layout_toolbar.addActions(
            [
                self.tool_actions[ToolMode.SELECT],
                self.tool_actions[ToolMode.ADD_TEXT],
                self.tool_actions[ToolMode.ADD_IMAGE],
                self.tool_actions[ToolMode.HIGHLIGHT],
                self.tool_actions[ToolMode.PERMANENT_DELETE],
            ]
        )
        self.layout_toolbar.addSeparator()
        self.layout_toolbar.addWidget(QLabel("页码", self.layout_toolbar))
        self.page_spin = QSpinBox(self.layout_toolbar)
        self.page_spin.setRange(1, 1)
        self.page_spin.setFixedWidth(72)
        self.layout_toolbar.addWidget(self.page_spin)
        self.total_pages_label = QLabel("/ 0", self.layout_toolbar)
        self.layout_toolbar.addWidget(self.total_pages_label)
        self.addToolBar(self.layout_toolbar)

        self.document_toolbar = DocumentToolbar(self)
        self.document_toolbar.bind(self.document_editor_view.editor)
        self.addToolBar(self.document_toolbar)
        self.document_toolbar.hide()

    def _create_search_bar(self) -> None:
        self.search_toolbar = QToolBar("搜索栏", self)
        self.search_toolbar.setObjectName("searchToolbar")
        self.search_toolbar.setMovable(False)
        self.search_panel = SearchPanel(self.search_toolbar)
        self.search_toolbar.addWidget(self.search_panel)
        self.addToolBarBreak()
        self.addToolBar(self.search_toolbar)
        self.search_toolbar.hide()

    def _create_left_dock(self) -> None:
        dock = QDockWidget(tr("MainWindow", "导航"), self)
        dock.setObjectName("navigationDock")
        dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea)
        self.navigation_tabs = QTabWidget(dock)
        self.navigation_tabs.setDocumentMode(True)
        self.thumbnail_panel = ThumbnailPanel(self.scheduler, self.navigation_tabs)
        self.layout_pages_tab = self.navigation_tabs.addTab(
            self.thumbnail_panel, tr("MainWindow", "页面")
        )
        self.bookmark_list = QListWidget(self.navigation_tabs)
        self.bookmarks_tab = self.navigation_tabs.addTab(
            self.bookmark_list, tr("MainWindow", "书签")
        )
        self.annotation_panel = AnnotationPanel(self.navigation_tabs)
        self.annotations_tab = self.navigation_tabs.addTab(
            self.annotation_panel, tr("MainWindow", "批注")
        )
        self.document_page_list = QListWidget(self.navigation_tabs)
        self.document_pages_tab = self.navigation_tabs.addTab(self.document_page_list, "文档页")
        self.document_outline_list = QListWidget(self.navigation_tabs)
        self.document_outline_tab = self.navigation_tabs.addTab(
            self.document_outline_list, "文档结构"
        )
        self.document_page_list.currentRowChanged.connect(self.document_editor_view.jump_to_page)
        dock.setWidget(self.navigation_tabs)
        dock.setMinimumWidth(190)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)

    def _create_right_dock(self) -> None:
        dock = QDockWidget(tr("MainWindow", "属性"), self)
        dock.setObjectName("propertiesDock")
        dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea)
        self.properties_stack = QStackedWidget(dock)
        layout_body = QWidget(self.properties_stack)
        layout = QVBoxLayout(layout_body)
        hint = QLabel(tr("MainWindow", "选择页面或对象后，这里会显示可用属性。"), layout_body)
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(hint)
        layout.addStretch(1)
        document_body = QWidget(self.properties_stack)
        document_layout = QVBoxLayout(document_body)
        document_layout.addWidget(QLabel("导入诊断", document_body))
        self.import_report_label = QLabel(document_body)
        self.import_report_label.setWordWrap(True)
        self.import_report_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        document_layout.addWidget(self.import_report_label)
        document_layout.addStretch(1)
        self.properties_stack.addWidget(layout_body)
        self.properties_stack.addWidget(document_body)
        dock.setWidget(self.properties_stack)
        dock.setMinimumWidth(220)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)

    def _create_status_bar(self) -> None:
        self.page_status = QLabel(tr("MainWindow", "未打开文档"), self)
        self.word_status = QLabel("", self)
        self.mode_status = QLabel("", self)
        self.zoom_status = QLabel("100%", self)
        self.save_status = QLabel(tr("MainWindow", "原文件将受到保护"), self)
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setMaximumWidth(150)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        self.statusBar().addWidget(self.page_status)
        self.statusBar().addWidget(self.word_status)
        self.statusBar().addPermanentWidget(self.progress_bar)
        self.statusBar().addPermanentWidget(self.zoom_status)
        self.statusBar().addPermanentWidget(self.save_status)
        self.statusBar().addPermanentWidget(self.mode_status)

    def _connect_view_controls(self) -> None:
        self._welcome.open_requested.connect(self.open_action.trigger)
        self._welcome.new_requested.connect(self.new_action.trigger)
        self.zoom_in_action.triggered.connect(self._zoom_in)
        self.zoom_out_action.triggered.connect(self._zoom_out)
        self.actual_size_action.triggered.connect(self._actual_size)
        self.fit_page_action.triggered.connect(self.document_view.fit_page)
        self.fit_width_action.triggered.connect(self.document_view.fit_width)
        self.continuous_action.toggled.connect(self.document_view.set_continuous_mode)
        self.document_view.zoom_changed.connect(
            lambda zoom: self.zoom_status.setText(f"{round(zoom * 100)}%")
        )
        self.document_editor_view.editor.zoom_changed.connect(
            lambda zoom: self.zoom_status.setText(f"{round(zoom * 100)}%")
        )
        self.document_view.current_page_changed.connect(self._update_page_status)
        self.thumbnail_panel.page_activated.connect(self.document_view.jump_to_page)
        self.document_view.current_page_changed.connect(self.thumbnail_panel.select_page)
        self.page_spin.valueChanged.connect(lambda page: self.document_view.jump_to_page(page - 1))
        self.search_action.triggered.connect(self.show_search)
        self.search_panel.close_requested.connect(self.hide_search)
        for tool, action in self.tool_actions.items():
            action.triggered.connect(
                lambda _checked=False, selected=tool: self.document_view.set_tool(selected)
            )
        self.document_view.tool_changed.connect(self._sync_tool_action)
        self.light_theme_action.triggered.connect(
            lambda _checked=False: self.theme_requested.emit("light")
        )
        self.dark_theme_action.triggered.connect(
            lambda _checked=False: self.theme_requested.emit("dark")
        )

    def _set_document_navigation(self, document: FlowDocument) -> None:
        self.document_outline_list.clear()
        for section in document.sections:
            for block in section.blocks:
                role = getattr(block, "semantic_role", None)
                if role is None or role.value not in {"title", "heading1", "heading2", "heading3"}:
                    continue
                text = getattr(block, "text", "").strip()
                if text:
                    self.document_outline_list.addItem(text[:80])

    def _zoom_in(self) -> None:
        if self.active_mode == "document":
            self.document_editor_view.editor.zoom_in()
        else:
            self.document_view.zoom_in()

    def _zoom_out(self) -> None:
        if self.active_mode == "document":
            self.document_editor_view.editor.zoom_out()
        else:
            self.document_view.zoom_out()

    def _actual_size(self) -> None:
        if self.active_mode == "document":
            self.document_editor_view.editor.actual_size()
        else:
            self.document_view.actual_size()

    def _apply_mode_ui(self) -> None:
        is_document = self.active_mode == "document"
        is_layout = self.active_mode == "layout"
        self.document_toolbar.setVisible(is_document)
        self.layout_toolbar.setVisible(not is_document)
        self.document_mode_action.setChecked(is_document)
        self.layout_mode_action.setChecked(is_layout)
        self.page_menu.setEnabled(not is_document)
        self.annotation_menu.setEnabled(not is_document)
        self.signature_menu.setEnabled(not is_document)
        self.navigation_tabs.setTabVisible(self.layout_pages_tab, not is_document)
        self.navigation_tabs.setTabVisible(self.bookmarks_tab, not is_document)
        self.navigation_tabs.setTabVisible(self.annotations_tab, not is_document)
        self.navigation_tabs.setTabVisible(self.document_pages_tab, is_document)
        self.navigation_tabs.setTabVisible(self.document_outline_tab, is_document)
        self.properties_stack.setCurrentIndex(1 if is_document else 0)
        self.mode_status.setText(
            "文档编辑模式" if is_document else "版面编辑模式" if is_layout else ""
        )

    def _update_page_status(self, page_index: int) -> None:
        if not self._page_count:
            return
        page_index = max(0, min(page_index, self._page_count - 1))
        self.page_status.setText(f"第 {page_index + 1} / {self._page_count} 页")
        self.total_pages_label.setText(f"/ {self._page_count}")
        blocked = self.page_spin.blockSignals(True)
        self.page_spin.setValue(page_index + 1)
        self.page_spin.blockSignals(blocked)

    def _sync_tool_action(self, value: str) -> None:
        tool = ToolMode(value)
        self.tool_actions[tool].setChecked(True)
        if tool is not ToolMode.SELECT:
            self.save_status.setText(f"当前工具：{self.tool_actions[tool].text()}；Esc 取消")

    def set_theme_choice(self, value: str) -> None:
        (self.dark_theme_action if value == "dark" else self.light_theme_action).setChecked(True)


def _first_pdf_path(mime_data) -> Path | None:
    if not mime_data.hasUrls():
        return None
    for url in mime_data.urls():
        path = Path(url.toLocalFile())
        if path.suffix.casefold() == ".pdf" and path.is_file():
            return path
    return None
