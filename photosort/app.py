"""Starting PhotoSort: logging, error dialogs, a single instance, and the main window."""
import ctypes
import getpass
import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtGui import QColor, QIcon, QPalette
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMessageBox

from . import APP_ID, APP_NAME
from .appdata import app_dir

log = logging.getLogger("photosort")

ICON = Path(__file__).parent / "resources" / "photosort.ico"
INSTANCE_NAME = f"{APP_NAME}-{getpass.getuser()}"
ASFW_ANY = -1


def log_path():
    return app_dir() / "photosort.log"


def setup_logging():
    handler = RotatingFileHandler(log_path(), maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    if sys.stderr:  # None under pythonw.exe
        root.addHandler(logging.StreamHandler())


def install_error_handlers():
    """Log every unhandled error, and tell the user where the log is."""
    def on_error(kind, value, tb):
        log.critical("Unhandled error", exc_info=(kind, value, tb))
        if QApplication.instance():
            QMessageBox.critical(None, APP_NAME, f"Something went wrong:\n{value}\n\n"
                                 f"Details are in the log file:\n{log_path()}")

    def on_thread_error(args):
        log.critical("Unhandled error in thread %s", args.thread.name,
                     exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    sys.excepthook = on_error
    threading.excepthook = on_thread_error


def hand_over_to_running_copy():
    """If PhotoSort is already running, ask it to come to the front and return True."""
    socket = QLocalSocket()
    socket.connectToServer(INSTANCE_NAME)
    if not socket.waitForConnected(500):
        return False
    ctypes.windll.user32.AllowSetForegroundWindow(ASFW_ANY)  # let the running copy take focus
    socket.write(b"show")
    socket.waitForBytesWritten(500)
    socket.disconnectFromServer()
    return True


def listen_for_second_launch(window):
    QLocalServer.removeServer(INSTANCE_NAME)  # clears a stale name left by a crash
    server = QLocalServer(window)
    server.listen(INSTANCE_NAME)

    def bring_to_front():
        server.nextPendingConnection()
        if window.isMinimized():
            window.showMaximized()
        window.raise_()
        window.activateWindow()

    server.newConnection.connect(bring_to_front)
    return server


def dark_palette():
    p = QPalette()
    base, window, text = QColor(30, 30, 30), QColor(40, 40, 40), QColor(225, 225, 225)
    p.setColor(QPalette.Window, window)
    p.setColor(QPalette.WindowText, text)
    p.setColor(QPalette.Base, base)
    p.setColor(QPalette.AlternateBase, window)
    p.setColor(QPalette.Text, text)
    p.setColor(QPalette.Button, QColor(55, 55, 55))
    p.setColor(QPalette.ButtonText, text)
    p.setColor(QPalette.Highlight, QColor(60, 120, 200))
    p.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    p.setColor(QPalette.ToolTipBase, base)
    p.setColor(QPalette.ToolTipText, text)
    p.setColor(QPalette.PlaceholderText, QColor(130, 130, 130))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor(120, 120, 120))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(120, 120, 120))
    return p


def main():
    setup_logging()
    install_error_handlers()
    # Our own taskbar button and icon, instead of pythonw's. Must come before any window.
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    app = QApplication(sys.argv)
    if hand_over_to_running_copy():
        return 0  # two copies could overwrite each other's state files
    log.info("Starting %s", APP_NAME)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    app.setPalette(dark_palette())
    if ICON.exists():
        app.setWindowIcon(QIcon(str(ICON)))

    from .ui.main_window import MainWindow
    window = MainWindow()
    listen_for_second_launch(window)
    window.showMaximized()
    return app.exec()
