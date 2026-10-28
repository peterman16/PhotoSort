"""Running slow work (reading the Card, copying) off the GUI thread, with a progress dialog."""
import logging

from PySide6.QtCore import QEventLoop, Qt, QThread, Signal
from PySide6.QtWidgets import QProgressDialog

from .. import APP_NAME

log = logging.getLogger(__name__)


class Worker(QThread):
    """Runs fn(*args, progress=...) on a thread. fn calls progress(done, total[, text]) and stops
    if it returns False."""

    progress = Signal(int, int, str)

    def __init__(self, fn, *args):
        super().__init__()
        self.fn, self.args = fn, args
        self.result = self.error = None
        self.cancelled = False

    def run(self):
        try:
            self.result = self.fn(*self.args, progress=self.report)
        except Exception as e:
            log.exception("Background task failed")
            self.error = e

    def report(self, done, total, text=""):
        self.progress.emit(done, total, str(text))
        return not self.cancelled


def run_with_progress(parent, label, fn, *args, cancel_text="Cancel"):
    """Run fn on a Worker while showing a progress dialog. Returns the Worker when it's done
    (check .result, .error and .cancelled)."""
    dialog = QProgressDialog(label, cancel_text, 0, 0, parent)
    dialog.setWindowTitle(APP_NAME)
    dialog.setWindowModality(Qt.WindowModal)
    dialog.setMinimumDuration(300)
    dialog.setMinimumWidth(480)
    dialog.setAutoClose(False)
    dialog.setAutoReset(False)

    worker = Worker(fn, *args)

    def on_progress(done, total, text):
        dialog.setMaximum(total)
        dialog.setValue(done)
        if text:
            dialog.setLabelText(f"{label}\n{text}")

    def on_cancel():
        worker.cancelled = True
        dialog.setLabelText("Stopping…")

    worker.progress.connect(on_progress)
    dialog.canceled.connect(on_cancel)
    loop = QEventLoop()
    worker.finished.connect(loop.quit)
    worker.start()
    loop.exec()
    dialog.close()
    return worker
