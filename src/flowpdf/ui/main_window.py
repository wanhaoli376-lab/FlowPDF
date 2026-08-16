from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from flowpdf.i18n import tr
from flowpdf.ui.welcome_page import WelcomePage


class MainWindow(QMainWindow):
    """Top-level three-column FlowPDF shell.

    Document behavior is attached through actions so the UI remains independent
    from the concrete PDF engine.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("mainWindow")
        self.setWindowTitle("FlowPDF")
        self.resize(1280, 820)
        self.setMinimumSize(900, 600)
        self.setAcceptDrops(True)

        self._workspace = QStackedWidget(self)
        self._welcome = WelcomePage(self)
        self._workspace.addWidget(self._welcome)
        self.setCentralWidget(self._workspace)

        self._create_actions()
        self._create_menus()
        self._create_toolbar()
        self._create_left_dock()
        self._create_right_dock()
        self._create_status_bar()

    def _create_actions(self) -> None:
        self.open_action = QAction(tr("MainWindow", "打开"), self)
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_action.setToolTip(tr("MainWindow", "打开 PDF（Ctrl+O）"))

        self.new_action = QAction(tr("MainWindow", "新建空白 PDF"), self)
        self.new_action.setShortcut(QKeySequence.StandardKey.New)
        self.save_action = QAction(tr("MainWindow", "保存"), self)
        self.save_action.setShortcut(QKeySequence.StandardKey.Save)
        self.save_as_action = QAction(tr("MainWindow", "另存为副本"), self)
        self.save_as_action.setShortcut(QKeySequence.StandardKey.SaveAs)

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
        self.fit_page_action = QAction(tr("MainWindow", "适应页面"), self)
        self.fit_page_action.setShortcut(QKeySequence("Ctrl+0"))

        self.close_action = QAction(tr("MainWindow", "关闭文档"), self)
        self.quit_action = QAction(tr("MainWindow", "退出"), self)
        self.quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        self.quit_action.triggered.connect(self.close)

    def _create_menus(self) -> None:
        file_menu = self.menuBar().addMenu(tr("MainWindow", "文件"))
        file_menu.addActions([self.new_action, self.open_action])
        self.recent_menu = file_menu.addMenu(tr("MainWindow", "最近打开"))
        self.recent_menu.setEnabled(False)
        file_menu.addSeparator()
        file_menu.addActions([self.save_action, self.save_as_action, self.close_action])
        file_menu.addSeparator()
        file_menu.addAction(self.quit_action)

        edit_menu = self.menuBar().addMenu(tr("MainWindow", "编辑"))
        edit_menu.addActions([self.undo_action, self.redo_action, self.search_action])
        self.page_menu = self.menuBar().addMenu(tr("MainWindow", "页面"))
        self.annotation_menu = self.menuBar().addMenu(tr("MainWindow", "批注"))
        self.signature_menu = self.menuBar().addMenu(tr("MainWindow", "填写与签名"))
        self.view_menu = self.menuBar().addMenu(tr("MainWindow", "视图"))
        self.view_menu.addActions([self.zoom_in_action, self.zoom_out_action, self.fit_page_action])

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
        self.addToolBar(toolbar)

    def _create_left_dock(self) -> None:
        dock = QDockWidget(tr("MainWindow", "导航"), self)
        dock.setObjectName("navigationDock")
        dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea)
        tabs = QTabWidget(dock)
        tabs.setDocumentMode(True)
        tabs.addTab(QListWidget(tabs), tr("MainWindow", "页面"))
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
        self.statusBar().addWidget(self.page_status)
        self.statusBar().addPermanentWidget(self.zoom_status)
        self.statusBar().addPermanentWidget(self.save_status)

    def closeEvent(self, event: QCloseEvent) -> None:
        # Phase 0 has no document session yet; keeping the hook makes the later
        # unsaved-change guard live at the correct seam.
        event.accept()

    def show_error(self, title: str, message: str) -> None:
        QMessageBox.critical(self, title, message)
