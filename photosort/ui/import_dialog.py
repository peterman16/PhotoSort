"""Import from Card: pick the Card, preview its photos by capture day, then copy the JPGs."""
import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from .. import APP_NAME, drives, importer
from ..shoot import Shoot
from .worker import run_with_progress

CHOOSE_FOLDER = "Choose a folder…"


class ImportDialog(QDialog):
    def __init__(self, library, parent=None):
        super().__init__(parent)
        self.library = library
        self.card = None
        self.days = {}
        self.imported = []  # Shoots, once the Import has run
        self.destination_root = library.root() or Path(library.prefs["library_root"])
        self.setWindowTitle(f"Import from Card · {APP_NAME}")
        self.resize(780, 620)

        self.source = QComboBox()
        self.source.activated.connect(self.source_chosen)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.fill_sources)
        source_row = QHBoxLayout()
        source_row.addWidget(self.source, 1)
        source_row.addWidget(refresh)

        self.days_list = QTreeWidget()
        self.days_list.setHeaderLabels(["Capture day", "Photos", ""])
        self.days_list.setRootIsDecorated(False)
        self.days_list.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.days_list.itemChanged.connect(lambda *_: self.update_preview())
        self.skip_imported = QCheckBox("Skip photos that are already imported")
        self.skip_imported.setChecked(True)
        self.skip_imported.toggled.connect(self.update_preview)
        self.split_days = QCheckBox("One Shoot per day")
        self.split_days.toggled.connect(self.update_preview)
        self.description = QLineEdit()
        self.description.setPlaceholderText("optional, e.g. Mount Baker")
        self.description.textChanged.connect(self.update_preview)
        self.root_label = QLabel(str(self.destination_root))
        change_root = QPushButton("Change…")
        change_root.clicked.connect(self.choose_root)
        root_row = QHBoxLayout()
        root_row.addWidget(self.root_label, 1)
        root_row.addWidget(change_root)
        self.preview = QLabel()
        self.preview.setWordWrap(True)
        self.preview.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.import_button = self.buttons.addButton("Import", QDialogButtonBox.AcceptRole)
        self.buttons.accepted.connect(self.run_import)
        self.buttons.rejected.connect(self.reject)

        form = QFormLayout()
        form.addRow("Card:", source_row)
        form.addRow("Description:", self.description)
        form.addRow("Destination:", root_row)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.days_list, 1)
        layout.addWidget(self.skip_imported)
        layout.addWidget(self.split_days)
        layout.addWidget(self.preview)
        layout.addWidget(self.buttons)

        self.fill_sources()

    # ---------- choosing the Card ----------

    def fill_sources(self):
        self.source.clear()
        for drive in drives.removable_drives_with_dcim():
            self.source.addItem(f"{drive.label or 'Card'} ({drive.root[:2]})", str(Path(drive.root) / "DCIM"))
        self.source.addItem(CHOOSE_FOLDER, None)
        if self.source.count() > 1:
            self.source.setCurrentIndex(0)
            self.scan(self.source.currentData())
        else:
            self.show_card(None)
            self.preview.setText("No card found. Insert the card, then press Refresh "
                                 "(or choose a folder).")

    def source_chosen(self, index):
        folder = self.source.itemData(index)
        if folder is None:
            folder = QFileDialog.getExistingDirectory(self, "Folder to import JPGs from")
            if not folder:
                return
            self.source.insertItem(index, os.path.normpath(folder), os.path.normpath(folder))
            self.source.setCurrentIndex(index)
        self.scan(folder)

    def scan(self, folder):
        known = self.library.known_photo_keys()
        worker = run_with_progress(self, f"Reading photos on {folder}…", importer.scan_card, folder, known)
        if worker.error:
            QMessageBox.warning(self, APP_NAME, f"Could not read {folder}:\n{worker.error}")
        self.show_card(worker.result)

    def show_card(self, card):
        self.card = card
        self.days = importer.group_by_day(card.photos) if card else {}
        self.days_list.blockSignals(True)
        self.days_list.clear()
        for day, photos in self.days.items():
            already = sum(p.already_imported for p in photos)
            new = len(photos) - already
            item = QTreeWidgetItem([day.strftime("%a %d %b %Y"), str(len(photos)),
                                    f"{new} new · {already} already imported" if already else f"{new} new"])
            item.setData(0, Qt.UserRole, day)
            item.setCheckState(0, Qt.Checked if new else Qt.Unchecked)
            self.days_list.addTopLevelItem(item)
        self.days_list.blockSignals(False)
        self.update_preview()

    def choose_root(self):
        folder = QFileDialog.getExistingDirectory(self, "Import into which library folder?", str(self.destination_root))
        if folder:
            self.destination_root = Path(os.path.normpath(folder))
            self.root_label.setText(str(self.destination_root))
            self.update_preview()

    # ---------- the plan ----------

    def chosen_days(self):
        chosen = {}
        for k in range(self.days_list.topLevelItemCount()):
            item = self.days_list.topLevelItem(k)
            if item.checkState(0) == Qt.Checked:
                day = item.data(0, Qt.UserRole)
                photos = [p for p in self.days[day] if not (self.skip_imported.isChecked() and p.already_imported)]
                if photos:
                    chosen[day] = photos
        return chosen

    def current_plan(self):
        return importer.plan(self.destination_root, self.chosen_days(), self.description.text(),
                             self.split_days.isChecked())

    def update_preview(self):
        if self.card is None:
            self.import_button.setEnabled(False)
            return
        total = sum(len(ps) for ps in self.days.values())
        already = sum(p.already_imported for ps in self.days.values() for p in ps)
        lines = [f"{total - already} new · {already} already imported on this card."]
        steps = self.current_plan()
        for dest, photos in steps:
            how = "adds to the existing Shoot" if dest.joins else "new Shoot"
            lines.append(f"→ {dest.folder}  ({len(photos)} JPGs, {how})")
        if not steps:
            lines.append("Nothing to import: tick a day with new photos.")
        self.preview.setText("\n".join(lines))
        self.import_button.setEnabled(bool(steps))

    # ---------- importing ----------

    def run_import(self):
        steps = self.current_plan()
        for dest, photos in steps:
            worker = run_with_progress(self, f"Copying JPGs to {dest.folder}…",
                                       importer.copy_into, dest, photos, self.card, cancel_text="Stop")
            if worker.error:
                QMessageBox.warning(self, APP_NAME, f"The Import stopped:\n{worker.error}\n\n"
                                    "What was copied is kept; run Import again to finish.")
            shoot = worker.result
            if shoot is None and Shoot.is_shoot(dest.folder):  # failed part-way: list what's there
                shoot = Shoot.read(dest.folder)
            if shoot is not None:
                self.imported.append(shoot)
                self.library.remember(shoot)
            if worker.error or worker.cancelled:
                break
        self.accept()
