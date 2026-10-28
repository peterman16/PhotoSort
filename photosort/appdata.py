"""PhotoSort's own folder on C: (preferences, the central Shoot list, mark backups, the log).

Set the PHOTOSORT_APPDATA environment variable to use a different folder, e.g. for testing.
"""
import logging
import os
from pathlib import Path

from .files import read_json, write_json

log = logging.getLogger(__name__)


def app_dir():
    folder = os.environ.get("PHOTOSORT_APPDATA") or Path(os.environ["LOCALAPPDATA"]) / "PhotoSort"
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


class Prefs:
    """App-wide preferences, remembered between sessions. Saved on every change."""

    DEFAULTS = {
        "library_root": str(Path.home() / "Pictures"),  # the only real setting; each Import can pick another
        "library_serial": None,     # volume serial of the library drive, to find it if its letter changes
        "view": "filmstrip",        # "filmstrip" or "grid"
        "filter": "all",
        "auto_advance": False,
        "rename_on_export": False,  # off on the first Export, then remembers the last choice
    }

    def __init__(self, path=None):
        self.path = Path(path) if path else app_dir() / "prefs.json"
        self.values = dict(self.DEFAULTS)
        if self.path.exists():
            try:
                self.values.update(read_json(self.path))
            except (OSError, ValueError):
                log.exception("Could not read %s; using defaults", self.path)

    def __getitem__(self, key):
        return self.values[key]

    def __setitem__(self, key, value):
        if self.values.get(key) != value:
            self.values[key] = value
            write_json(self.path, self.values)
