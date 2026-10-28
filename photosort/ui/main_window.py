"""The main window: the home screen, and the Cull screen once a Shoot is open."""
import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QProgressDialog,
                               QPushButton, QStackedWidget, QVBoxLayout, QWidget)

from .. import APP_NAME
from ..appdata import Prefs
from ..gamepad import Gamepad
from ..library import Library
from ..shoot import PICK, Shoot
from .cull import CullView
from .export_dialog import ExportDialog, confirm_unmarked
from .home import HomeScreen
from .import_dialog import ImportDialog

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.prefs = Prefs()
        self.library = Library(self.prefs)
        self.setWindowTitle(APP_NAME)
        self.resize(1400, 900)

        self.home = HomeScreen(self.library)
        self.home.open_requested.connect(self.open_shoot)
        self.home.import_requested.connect(self.import_from_card)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.home)
        self.setCentralWidget(self.stack)
        self.statusBar()
        self.cull = None  # the CullScreen while a Shoot is open
        self.gamepad = Gamepad(self)
        self.show_home()

    def show_home(self):
        if self.cull is not None:
            self.gamepad.set_target(None)
            self.cull.view.close_shoot()
            self.library.remember(self.cull.shoot)
            self.stack.removeWidget(self.cull)
            self.cull.deleteLater()
            self.cull = None
        self.setWindowTitle(APP_NAME)
        self.statusBar().show()
        self.home.refresh()
        self.stack.setCurrentWidget(self.home)

    def open_shoot(self, folder):
        shoot = self.load_shoot(folder)
        if shoot is None:
            return
        self.library.remember(shoot)
        if shoot.exported and not shoot.cull_photos():
            QMessageBox.information(self, APP_NAME, f"{shoot.name} was exported on {shoot.exported_at[:10]}. "
                                    "Its folder holds the Picks' RAWs; there are no JPGs left to cull.")
            self.home.refresh()
            return
        self.cull = CullScreen(shoot, self.prefs, self.screen_pixels())
        self.cull.home_button.clicked.connect(self.show_home)
        self.cull.view.home_requested.connect(self.show_home)
        self.cull.export_button.clicked.connect(self.export_current)
        self.stack.addWidget(self.cull)
        self.stack.setCurrentWidget(self.cull)
        self.statusBar().hide()
        self.setWindowTitle(f"{shoot.name} · {APP_NAME}")
        self.cull.view.setFocus()
        self.gamepad.set_target(self.cull.view)

    def export_current(self):
        shoot = self.cull.shoot
        if not any(p.mark == PICK for p in shoot.photos):
            QMessageBox.information(self, APP_NAME, "There are no Picks to export yet. Press A to pick a photo.")
            return
        if shoot.exported and QMessageBox.question(
                self, APP_NAME, f"{shoot.name} was already exported on {shoot.exported_at[:10]}. Export again?"
        ) != QMessageBox.Yes:
            return
        treat_as_rejects = confirm_unmarked(self, shoot)
        if treat_as_rejects is None:
            self.cull.view.setFocus()
            return
        dialog = ExportDialog(shoot, self.prefs, treat_as_rejects, self)
        dialog.exec()
        if dialog.exported:
            self.show_home()
        else:
            self.cull.view.update_visible()
            self.cull.view.update()
            self.cull.view.setFocus()

    def import_from_card(self):
        dialog = ImportDialog(self.library, self)
        dialog.exec()
        if len(dialog.imported) == 1:
            self.open_shoot(str(dialog.imported[0].folder))
        else:
            self.home.refresh()

    def screen_pixels(self):
        screen = self.screen()
        ratio = screen.devicePixelRatio()
        return int(screen.size().width() * ratio), int(screen.size().height() * ratio)

    def closeEvent(self, e):
        if self.cull is not None:
            self.show_home()
        super().closeEvent(e)

    def load_shoot(self, folder):
        """Open a Shoot folder, showing progress while new JPGs' EXIF is read."""
        dialog = QProgressDialog("Reading photos…", "Cancel", 0, 0, self)
        dialog.setWindowTitle(APP_NAME)
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setMinimumDuration(400)

        def progress(done, total):
            dialog.setMaximum(total)
            dialog.setValue(done)
            QApplication.processEvents()
            return not dialog.wasCanceled()

        try:
            shoot = Shoot.open(folder, progress)
        except OSError as e:
            log.exception("Could not open %s", folder)
            QMessageBox.warning(self, APP_NAME, f"Could not open {folder}:\n{e}")
            return None
        finally:
            dialog.close()
        if shoot is not None and not shoot.photos:
            QMessageBox.information(self, APP_NAME, f"There are no JPGs in {folder}.")
            return None
        return shoot


class CullScreen(QWidget):
    """A slim bar (Home, Shoot name, Export) above the Cull view."""

    def __init__(self, shoot, prefs, screen_size):
        super().__init__()
        self.shoot = shoot
        self.view = CullView(shoot, prefs, screen_size)
        self.home_button = QPushButton("◀  Home")
        self.export_button = QPushButton("Export…")
        self.export_button.setStyleSheet("font-weight: 600; padding: 4px 16px;")
        for button in (self.home_button, self.export_button):
            button.setFocusPolicy(Qt.NoFocus)  # keys always go to the Cull view
        title = QLabel(shoot.name)
        title.setStyleSheet("font-size: 12pt; font-weight: 600;")

        bar = QHBoxLayout()
        bar.setContentsMargins(8, 4, 8, 4)
        bar.addWidget(self.home_button)
        bar.addSpacing(12)
        bar.addWidget(title)
        bar.addStretch()
        bar.addWidget(self.export_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(bar)
        layout.addWidget(self.view, 1)
