"""What PhotoSort's shortcuts run, with the base Python's pythonw.exe (no console window).

Why not the venv's own pythonw.exe? On Python 3.13.0 that launcher starts the console
python.exe, which opens a terminal window next to PhotoSort. So the shortcut starts the base
pythonw.exe, and this file puts the venv's packages first on the path before starting the app.
"""
import site
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

before = list(sys.path)
site.addsitedir(str(REPO / ".venv" / "Lib" / "site-packages"))  # also runs pywin32's .pth setup
added = [p for p in sys.path if p not in before]
sys.path[:] = [str(REPO)] + added + before  # the venv's packages win over any global ones

from photosort.app import main  # noqa: E402

sys.exit(main())
