"""The Export dialog: Batch rename option, waiting for the Card, copying, then the Recycle Bin."""
import os
import subprocess

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel,
                               QLineEdit, QMessageBox, QPushButton, QVBoxLayout)

from .. import APP_NAME, exporter
from ..shoot import PICK, REJECT
from .worker import run_with_progress

PREVIEW_COUNT = 3


def confirm_unmarked(parent, shoot):
    """Warn about Unmarked photos. Returns the photos to treat as Rejects ([] if none are
    unmarked), or None to go back to culling."""
    unmarked = [p for p in shoot.cull_photos() if p.mark is None]
    if not unmarked:
        return []
    box = QMessageBox(parent)
    box.setWindowTitle(APP_NAME)
    box.setIcon(QMessageBox.Warning)
    box.setText(f"{len(unmarked)} photos are unmarked.")
    back = box.addButton("Back to culling", QMessageBox.RejectRole)
    box.addButton("Export; treat unmarked as Rejects", QMessageBox.AcceptRole)
    box.setDefaultButton(back)
    box.exec()
    return None if box.clickedButton() is back else unmarked


class ExportDialog(QDialog):
    def __init__(self, shoot, prefs, treat_as_rejects=(), parent=None):
        super().__init__(parent)
        self.shoot = shoot
        self.treat_as_rejects = treat_as_rejects
        self.prefs = prefs
        self.finder = exporter.RawFinder()
        self.picks = [p for p in shoot.photos if p.mark == PICK]
        self.exported = False  # True once the Export has finished
        self.setWindowTitle(f"Export {shoot.name} · {APP_NAME}")
        self.setMinimumWidth(640)

        count = len(self.picks)
        intro = QLabel(f"Copy the RAWs of {count} Pick{'s' if count != 1 else ''} from the card into\n{shoot.folder}")
        self.rename = QCheckBox("Rename RAWs")
        self.rename.setChecked(prefs["rename_on_export"])
        self.pattern = QLineEdit(exporter.default_pattern(shoot))
        self.pattern.setToolTip("{n} is the Pick's number in capture order")
        self.rename_preview = QLabel()
        self.rename.toggled.connect(self.update_rename)
        self.pattern.textChanged.connect(self.update_rename)

        self.status = QLabel()
        self.status.setWordWrap(True)
        locate = QPushButton("Locate RAWs…")
        locate.clicked.connect(self.locate)
        status_row = QHBoxLayout()
        status_row.addWidget(self.status, 1)
        status_row.addWidget(locate)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        self.export_button = self.buttons.addButton("Export", QDialogButtonBox.AcceptRole)
        self.buttons.accepted.connect(self.start)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addSpacing(8)
        layout.addWidget(self.rename)
        layout.addWidget(self.pattern)
        layout.addWidget(self.rename_preview)
        layout.addSpacing(8)
        layout.addLayout(status_row)
        layout.addWidget(self.buttons)

        # Export waits for the Card and starts by itself once it appears.
        self.waiting = False
        self.poll = QTimer(self, interval=2000, timeout=self.check_card)
        self.poll.start()
        self.update_rename()
        self.check_card()

    def renaming(self):
        return self.rename.isChecked()

    def update_rename(self):
        self.pattern.setEnabled(self.renaming())
        if self.renaming():
            names = [exporter.renamed(self.pattern.text(), n, len(self.picks)) + ".CR3"
                     for n in range(1, min(PREVIEW_COUNT, len(self.picks)) + 1)]
            self.rename_preview.setText("  ".join(names) + ("  …" if len(self.picks) > PREVIEW_COUNT else ""))
        else:
            self.rename_preview.setText("RAWs keep their camera filenames.")

    def missing(self):
        return self.finder.missing_cards(self.shoot, self.picks)

    def check_card(self):
        missing = self.missing()
        if missing:
            self.status.setText(f"Insert card {', '.join(missing)} to export (or Locate RAWs…)."
                                + ("\nExport will start when it's inserted." if self.waiting else ""))
        else:
            self.status.setText("Ready: the RAWs' source is available.")
            if self.waiting:
                self.start()

    def locate(self):
        folder = QFileDialog.getExistingDirectory(self, "Folder with the RAWs (searched with its subfolders)")
        if folder:
            self.finder.locate(os.path.normpath(folder))
            self.check_card()

    def start(self):
        if self.missing():
            self.waiting = True
            self.export_button.setEnabled(False)
            self.check_card()
            return
        self.poll.stop()
        for photo in self.treat_as_rejects:
            photo.mark = REJECT
        self.shoot.save()
        self.prefs["rename_on_export"] = self.renaming()
        pattern = self.pattern.text() if self.renaming() else None
        items = exporter.plan_export(self.shoot, self.finder, pattern)
        worker = run_with_progress(self, "Copying and verifying RAWs…", exporter.copy_raws, self.shoot, items,
                                   cancel_text="Stop")
        result = worker.result or exporter.ExportResult(stopped=True)
        if worker.error:
            result.failed.append((None, str(worker.error)))
        self.finish(items, result)

    def finish(self, items, result):
        problems = [f"{i.photo.name}: {i.problem}" for i in items if i.problem]
        failures = [f"{i.photo.name if i else ''}: {msg}" for i, msg in result.failed]
        lines = [f"{result.copied} RAWs copied and verified"
                 + (f", {result.already_done} already done" if result.already_done else "") + "."]
        if problems:
            lines += ["", "These Picks have no RAW to copy; their JPGs are kept:"] + problems[:20]
        if not result.finished:
            if failures or result.stopped:
                lines += ["", "The Export didn't finish. Run it again to continue; finished RAWs are skipped."]
            else:
                lines += ["", "No RAWs were exported, so nothing was moved to the Recycle Bin. "
                              "Insert the card or use Locate RAWs…, then Export again."]
            lines += failures[:20]
            QMessageBox.warning(self, APP_NAME, "\n".join(lines))
            exporter.finish(self.shoot, items, result, remove_jpgs=False, renaming=False)
            self.reject()
            return

        jpgs = exporter.jpgs_to_remove(self.shoot, items)
        remove = False
        if jpgs:
            lines += ["", f"Move {len(jpgs)} JPGs (verified Picks and all Rejects) to the Recycle Bin, "
                          "leaving a Shoot folder of RAWs? The card is not touched."]
            answer = QMessageBox.question(self, APP_NAME, "\n".join(lines),
                                          QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            remove = answer == QMessageBox.Yes
        else:
            QMessageBox.information(self, APP_NAME, "\n".join(lines))
        try:
            recycled = exporter.finish(self.shoot, items, result, remove, self.renaming())
        except OSError as e:
            QMessageBox.warning(self, APP_NAME, f"Could not finish the Export:\n{e}")
            self.reject()
            return
        self.exported = True
        message = f"{self.shoot.name} is exported." + (f" {recycled} JPGs went to the Recycle Bin." if recycled else "")
        box = QMessageBox(QMessageBox.Information, APP_NAME, message, QMessageBox.Ok, self)
        explorer = box.addButton("Show folder", QMessageBox.ActionRole)
        box.exec()
        if box.clickedButton() is explorer:
            subprocess.Popen(["explorer", os.path.normpath(self.shoot.folder)])
        self.accept()
