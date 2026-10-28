"""The Library: where Shoot folders live (default: the Pictures folder), and the central list of known Shoots.

The central list (`shoots.json` in PhotoSort's app-data folder) only feeds the home screen. It can
be rebuilt at any time by scanning the library root, its root-level folders and its year folders
for Shoot state files. Each entry remembers its drive's volume serial, so a Shoot is still found
if the Library drive comes back under another letter, and shows as offline while it's unplugged.
"""
import logging
import os
from datetime import datetime
from pathlib import Path

from . import drives
from .appdata import app_dir
from .files import read_json, write_json
from .shoot import Shoot

log = logging.getLogger(__name__)


class Library:
    def __init__(self, prefs, path=None):
        self.prefs = prefs
        self.path = Path(path) if path else app_dir() / "shoots.json"
        self.entries = []  # dicts: path, serial, name, summary, unmarked, exported, updated
        try:
            self.entries = read_json(self.path)
        except FileNotFoundError:
            self.rebuild()  # first run
        except (OSError, ValueError):
            log.exception("Could not read %s; rebuilding it", self.path)
            self.rebuild()

    # ---------- the library root ----------

    def root(self):
        """The library root, following its drive to a new letter if needed. None if unplugged."""
        root = Path(self.prefs["library_root"])
        if root.exists():
            drive = drives.volume_of(root)
            if drive and self.prefs["library_serial"] != drive.serial:
                self.prefs["library_serial"] = drive.serial
            return root
        serial = self.prefs["library_serial"]
        new_drive = serial and drives.find_drive(serial)
        if new_drive:
            moved = Path(new_drive) / Path(root).relative_to(Path(root).anchor)
            if moved.exists():
                return moved
        return None

    def set_root(self, folder):
        drive = drives.volume_of(folder)
        self.prefs["library_root"] = str(folder)
        self.prefs["library_serial"] = drive.serial if drive else None
        self.rebuild()

    # ---------- the central list ----------

    def save(self):
        write_json(self.path, self.entries)

    def resolve(self, entry):
        """Where an entry's Shoot folder is now, or None if its drive isn't connected."""
        path = Path(entry["path"])
        if path.exists():
            return path
        new_drive = entry.get("serial") and drives.find_drive(entry["serial"])
        if new_drive:
            moved = Path(new_drive) / path.relative_to(path.anchor)
            if moved.exists():
                return moved
        return None

    def remember(self, shoot):
        """Add or update a Shoot on the home screen. Call after opening, culling or exporting."""
        drive = drives.volume_of(shoot.folder)
        c = shoot.counts()
        entry = {
            "path": str(shoot.folder),
            "serial": drive.serial if drive else None,
            "name": shoot.name,
            "summary": shoot.summary(),
            "unmarked": c.unmarked,
            "exported": shoot.exported,
            "updated": datetime.now().isoformat(timespec="seconds"),
        }
        self.entries = [e for e in self.entries if not self._same(e, shoot.folder)]
        self.entries.append(entry)
        self.save()

    def forget(self, entry):
        self.entries.remove(entry)
        self.save()

    def _same(self, entry, folder):
        folder = os.path.normcase(str(folder))
        if os.path.normcase(entry["path"]) == folder:
            return True
        now = self.resolve(entry)  # the same Shoot, seen under a new drive letter
        return now is not None and os.path.normcase(str(now)) == folder

    def rebuild(self):
        """Rescan the library root for Shoots. Keeps entries for unplugged drives (shown offline)."""
        found = {}
        root = self.root()
        if root:
            for folder in self.candidate_folders(root):
                try:
                    found[os.path.normcase(str(folder))] = Shoot.read(folder)
                except (OSError, ValueError):
                    log.warning("Skipping unreadable Shoot %s", folder, exc_info=True)
        # Keep Shoots that are offline, or outside the root (e.g. a folder opened as a Shoot on C:).
        self.entries = [e for e in self.entries if self.resolve(e) is None or Shoot.is_shoot(self.resolve(e))]
        for shoot in found.values():
            self.remember(shoot)
        self.save()

    @staticmethod
    def candidate_folders(root):
        """Root-level folders and folders inside year folders (e.g. D:\\2025\\2025_11_12)."""
        try:
            top = [p for p in Path(root).iterdir() if p.is_dir() and not p.name.startswith(("$", "."))]
        except OSError:
            return []
        out = []
        for folder in top:
            if Shoot.is_shoot(folder):
                out.append(folder)
            if folder.name.isdigit() and len(folder.name) == 4:
                try:
                    out += [p for p in folder.iterdir() if p.is_dir() and Shoot.is_shoot(p)]
                except OSError:
                    pass
        return out

    def shoots(self):
        """Each entry with its current folder (None when offline), newest Shoot first."""
        rows = [(e, self.resolve(e)) for e in self.entries]
        return sorted(rows, key=lambda r: r[0]["name"], reverse=True)

    def known_photo_keys(self):
        """(Card filename, capture time) of every photo in every reachable Shoot, for skipping
        already-imported photos."""
        keys = set()
        for entry, folder in self.shoots():
            if folder and Shoot.is_shoot(folder):
                try:
                    keys |= {p.key for p in Shoot.read(folder).photos}
                except (OSError, ValueError):
                    log.warning("Could not read %s", folder, exc_info=True)
        return keys
