"""The home screen: the list of Shoots with their progress, and the ways to start one."""
import os
import subprocess

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QHeaderView, QLabel, QMenu, QPushButton,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)


class HomeScreen(QWidget):
    open_requested = Signal(str)   # a Shoot folder (or any folder of JPGs) to open
    import_requested = Signal()

    def __init__(self, library):
        super().__init__()
        self.library = library

        title = QLabel("PhotoSort")
        title.setStyleSheet("font-size: 22pt; font-weight: 600;")
        self.root_label = QLabel()
        change_root = QPushButton("Change…")
        change_root.clicked.connect(self.choose_root)

        import_button = QPushButton("Import from Card…")
        import_button.setDefault(True)
        import_button.setStyleSheet("font-weight: 600; padding: 6px 16px;")
        import_button.clicked.connect(self.import_requested)
        open_button = QPushButton("Open folder as Shoot…")
        open_button.clicked.connect(self.choose_folder)
        rescan_button = QPushButton("Rescan library")
        rescan_button.clicked.connect(self.rescan)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Shoot", "Progress", "Folder"])
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.itemActivated.connect(self.open_item)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.context_menu)

        top = QHBoxLayout()
        top.addWidget(title)
        top.addStretch()
        top.addWidget(QLabel("Library:"))
        top.addWidget(self.root_label)
        top.addWidget(change_root)

        buttons = QHBoxLayout()
        buttons.addWidget(import_button)
        buttons.addWidget(open_button)
        buttons.addStretch()
        buttons.addWidget(rescan_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.addLayout(top)
        layout.addLayout(buttons)
        layout.addWidget(self.tree)
        layout.addWidget(QLabel("Double-click a Shoot to cull it. Right-click for more."))

    def refresh(self):
        root = self.library.root()
        self.root_label.setText(str(root) if root else f"{self.library.prefs['library_root']} (not connected)")
        self.tree.clear()
        for entry, folder in self.library.shoots():
            progress = entry["summary"] if folder else f"offline · {entry['summary']}"
            item = QTreeWidgetItem([entry["name"], progress, str(folder or entry["path"])])
            item.setData(0, Qt.UserRole, entry)
            if folder is None:
                for col in range(3):
                    item.setForeground(col, QColor(130, 130, 130))
            elif not entry["exported"] and entry.get("unmarked"):
                item.setForeground(1, QColor(240, 200, 90))
            self.tree.addTopLevelItem(item)
        if self.tree.topLevelItemCount():
            self.tree.setCurrentItem(self.tree.topLevelItem(0))
        self.tree.setFocus()

    def open_item(self, item):
        entry = item.data(0, Qt.UserRole)
        folder = self.library.resolve(entry)
        if folder is None:
            self.window().statusBar().showMessage(
                f"{entry['name']} is offline. Connect its drive and try again.", 8000)
            return
        self.open_requested.emit(str(folder))

    def context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if not item:
            return
        entry = item.data(0, Qt.UserRole)
        folder = self.library.resolve(entry)
        menu = QMenu(self)
        explorer = menu.addAction("Show in Explorer")
        explorer.setEnabled(folder is not None)
        forget = menu.addAction("Remove from this list (keeps the folder)")
        chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if chosen is explorer:
            subprocess.Popen(["explorer", os.path.normpath(folder)])
        elif chosen is forget:
            self.library.forget(entry)
            self.refresh()

    def choose_folder(self):
        start = str(self.library.root() or os.path.expanduser("~\\Pictures"))
        folder = QFileDialog.getExistingDirectory(self, "Open a folder of JPGs as a Shoot", start)
        if folder:
            self.open_requested.emit(folder)

    def choose_root(self):
        start = str(self.library.root() or "")
        folder = QFileDialog.getExistingDirectory(self, "Where do your Shoot folders live?", start)
        if folder:
            self.library.set_root(os.path.normpath(folder))
            self.refresh()

    def rescan(self):
        self.library.rebuild()
        self.refresh()
