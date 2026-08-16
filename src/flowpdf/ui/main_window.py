from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QAction,
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

from flowpdf.backends.base import PageInfo
from flowpdf.i18n import tr
from flowpdf.rendering.render_scheduler import RenderScheduler, RenderSource
from flowpdf.ui.document_view import DocumentView
from flowpdf.ui.search_panel import SearchPanel
from flowpdf.ui.thumbnail_panel import ThumbnailPanel
from flowpdf.ui.welcome_page import WelcomePage


class MainWindow(QMainWindow):
    """Three-column Qt shell; application behavior lives in its controller."""

    pdf_dropped = Signal(str)
    recent_file_requested = Signal(str)

    def __init__(self, scheduler: RenderScheduler) -> None:
        super().__init__()
        self.scheduler = scheduler
        self.controller: Any | None = None
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
        self._workspace.addWidget(self._welcome)
        self._workspace.addWidget(self.document_view)
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

    def attach_controller(self, controller: Any) -> None:
        self.controller = controller

    def show_document(
        self,
        source: RenderSource,
        page_infos: list[PageInfo],
        *,
        title: str,
        revision: int = 0,
    ) -> None:
        self._page_count = len(page_infos)
        self.document_view.set_document(source, page_infos, revision=revision)
        self.thumbnail_panel.set_document(source, page_infos, revision=revision)
        self.page_spin.setRange(1, max(1, self._page_count))
        self.page_spin.setValue(1)
        self._workspace.setCurrentWidget(self.document_view)
        self.setWindowTitle(f"{title} — FlowPDF")
        self.set_document_enabled(True)
        self._update_page_status(0)

    def refresh_document(
        self,
        source: RenderSource,
        page_infos: list[PageInfo],
        *,
        revision: int,
    ) -> None:
        self._page_count = len(page_infos)
        self.document_view.update_snapshot(source, page_infos, revision=revision)
        self.thumbnail_panel.set_document(source, page_infos, revision=revision)
        self.page_spin.setRange(1, max(1, self._page_count))
        self._update_page_status(self.document_view.current_page)

    def clear_document(self) -> None:
        self.document_view.clear_document()
        self.thumbnail_panel.clear_document()
        self.search_panel.set_results(0, 0)
        self._page_count = 0
        self._workspace.setCurrentWidget(self._welcome)
        self.setWindowTitle("FlowPDF")
        self.page_status.setText(tr("MainWindow", "未打开文档"))
        self.set_document_enabled(False)

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
        ):
            action.setEnabled(enabled)
        self.page_spin.setEnabled(enabled)

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
        if self.controller is not None and not self.controller.request_close():
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
        self.open_action = QAction(tr("MainWindow", "打开"), self)
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.new_action = QAction(tr("MainWindow", "新建空白 PDF"), self)
        self.new_action.setShortcut(QKeySequence.StandardKey.New)
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

        self.delete_pages_action = QAction("删除所选页面", self)
        self.delete_pages_action.setShortcut(QKeySequence(Qt.Key.Key_Delete))
        self.duplicate_pages_action = QAction("复制所选页面", self)
        self.rotate_pages_action = QAction("顺时针旋转", self)
        self.insert_blank_action = QAction("插入空白页面", self)
        self.insert_pdf_action = QAction("从 PDF 插入页面", self)
        self.export_pages_action = QAction("导出所选页面", self)

    def _create_menus(self) -> None:
        file_menu = self.menuBar().addMenu(tr("MainWindow", "文件"))
        file_menu.addActions([self.new_action, self.open_action])
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
                self.delete_pages_action,
            ]
        )
        self.annotation_menu = self.menuBar().addMenu(tr("MainWindow", "批注"))
        self.signature_menu = self.menuBar().addMenu(tr("MainWindow", "填写与签名"))
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

    def _create_toolbar(self) -> None:
        toolbar = QToolBar(tr("MainWindow", "常用工具"), self)
        toolbar.setObjectName("mainToolbar")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        toolbar.addActions([self.open_action, self.save_action])
        toolbar.addSeparator()
        toolbar.addActions([self.undo_action, self.redo_action])
        toolbar.addSeparator()
        toolbar.addActions([self.search_action, self.zoom_out_action, self.zoom_in_action])
        toolbar.addSeparator()
        toolbar.addWidget(QLabel("页码", toolbar))
        self.page_spin = QSpinBox(toolbar)
        self.page_spin.setRange(1, 1)
        self.page_spin.setFixedWidth(72)
        toolbar.addWidget(self.page_spin)
        self.total_pages_label = QLabel("/ 0", toolbar)
        toolbar.addWidget(self.total_pages_label)
        self.addToolBar(toolbar)

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
        tabs = QTabWidget(dock)
        tabs.setDocumentMode(True)
        self.thumbnail_panel = ThumbnailPanel(self.scheduler, tabs)
        tabs.addTab(self.thumbnail_panel, tr("MainWindow", "页面"))
        tabs.addTab(QListWidget(tabs), tr("MainWindow", "书签"))
        tabs.addTab(QListWidget(tabs), tr("MainWindow", "批注"))
        dock.setWidget(tabs)
        dock.setMinimumWidth(190)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)

    def _create_right_dock(self) -> None:
        dock = QDockWidget(tr("MainWindow", "属性"), self)
        dock.setObjectName("propertiesDock")
        dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea)
        body = QWidget(dock)
        layout = QVBoxLayout(body)
        hint = QLabel(tr("MainWindow", "选择页面或对象后，这里会显示可用属性。"), body)
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addWidget(hint)
        layout.addStretch(1)
        dock.setWidget(body)
        dock.setMinimumWidth(220)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)

    def _create_status_bar(self) -> None:
        self.page_status = QLabel(tr("MainWindow", "未打开文档"), self)
        self.zoom_status = QLabel("100%", self)
        self.save_status = QLabel(tr("MainWindow", "原文件将受到保护"), self)
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setMaximumWidth(150)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.hide()
        self.statusBar().addWidget(self.page_status)
        self.statusBar().addPermanentWidget(self.progress_bar)
        self.statusBar().addPermanentWidget(self.zoom_status)
        self.statusBar().addPermanentWidget(self.save_status)

    def _connect_view_controls(self) -> None:
        self._welcome.open_requested.connect(self.open_action.trigger)
        self._welcome.new_requested.connect(self.new_action.trigger)
        self.zoom_in_action.triggered.connect(self.document_view.zoom_in)
        self.zoom_out_action.triggered.connect(self.document_view.zoom_out)
        self.actual_size_action.triggered.connect(self.document_view.actual_size)
        self.fit_page_action.triggered.connect(self.document_view.fit_page)
        self.fit_width_action.triggered.connect(self.document_view.fit_width)
        self.continuous_action.toggled.connect(self.document_view.set_continuous_mode)
        self.document_view.zoom_changed.connect(
            lambda zoom: self.zoom_status.setText(f"{round(zoom * 100)}%")
        )
        self.document_view.current_page_changed.connect(self._update_page_status)
        self.thumbnail_panel.page_activated.connect(self.document_view.jump_to_page)
        self.document_view.current_page_changed.connect(self.thumbnail_panel.select_page)
        self.page_spin.valueChanged.connect(lambda page: self.document_view.jump_to_page(page - 1))
        self.search_action.triggered.connect(self.show_search)
        self.search_panel.close_requested.connect(self.hide_search)

    def _update_page_status(self, page_index: int) -> None:
        if not self._page_count:
            return
        page_index = max(0, min(page_index, self._page_count - 1))
        self.page_status.setText(f"第 {page_index + 1} / {self._page_count} 页")
        self.total_pages_label.setText(f"/ {self._page_count}")
        blocked = self.page_spin.blockSignals(True)
        self.page_spin.setValue(page_index + 1)
        self.page_spin.blockSignals(blocked)


def _first_pdf_path(mime_data) -> Path | None:
    if not mime_data.hasUrls():
        return None
    for url in mime_data.urls():
        path = Path(url.toLocalFile())
        if path.suffix.casefold() == ".pdf" and path.is_file():
            return path
    return None
