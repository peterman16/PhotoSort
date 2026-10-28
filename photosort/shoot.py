"""A Shoot: one folder of photos culled together, and its hidden state file.

The state file (`.photosort.json` in the Shoot folder) is the source of truth. It holds every
photo's mark, where it came from on the Card, and the Export record. Every mark is saved
immediately. If the Library drive is unplugged, marks are kept in memory and in a backup on C:,
and are written to the state file once the drive is back (or the next time the Shoot is opened).
"""
import logging
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from .appdata import app_dir
from .files import read_json, set_hidden, write_json
from .formats import is_jpg
from .metadata import read_jpg_info

log = logging.getLogger(__name__)

STATE_FILE = ".photosort.json"
CACHE_DIR = ".photosort"  # hidden folder for the Grid thumbnails
STATE_VERSION = 1

PICK, REJECT = "pick", "reject"


@dataclass
class Photo:
    name: str                     # current JPG filename in the Shoot folder
    captured: str                 # capture time, ISO format ("2025-11-12T14:20:59")
    camera: str | None = None     # EXIF model, e.g. "Canon EOS R8"
    original: str | None = None   # filename on the Card, if Import renamed it to avoid a clash
    card: str | None = None       # volume serial of the Card it was imported from
    source: str | None = None     # its path on the Card, relative to the Card's root
    mark: str | None = None       # PICK, REJECT or None (Unmarked)
    raw: str | None = None        # filename of its exported Companion RAW in the Shoot folder
    raw_hash: str | None = None   # SHA-256 of that RAW, taken while reading it from the Card
    present: bool = field(default=True, repr=False)  # its JPG is in the folder (not saved)

    @property
    def original_name(self):
        return self.original or self.name

    @property
    def key(self):
        """What "already imported" compares: the Card filename plus capture time."""
        return self.original_name.lower(), self.captured

    def to_json(self):
        data = asdict(self)
        del data["present"]
        return {k: v for k, v in data.items() if v is not None}

    @classmethod
    def from_json(cls, data):
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__ and k != "present"})


@dataclass
class Counts:
    total: int
    picks: int
    rejects: int

    @property
    def unmarked(self):
        return self.total - self.picks - self.rejects


class Shoot:
    def __init__(self, folder, data=None):
        self.folder = Path(folder)
        data = data or {}
        self.id = data.get("id") or uuid.uuid4().hex
        self.cards = data.get("cards", {})            # volume serial -> Card label
        self.last_viewed = data.get("last_viewed")
        self.exported_at = data.get("exported_at")
        self.photos = [Photo.from_json(p) for p in data.get("photos", [])]
        self.unsaved = False                          # True while the drive is unreachable
        self.sort()

    # ---------- opening ----------

    @staticmethod
    def is_shoot(folder):
        return (Path(folder) / STATE_FILE).is_file()

    @classmethod
    def read(cls, folder):
        """Read a Shoot's state file as it is, without scanning the folder."""
        return cls(folder, read_json(Path(folder) / STATE_FILE))

    @classmethod
    def open(cls, folder, progress=None):
        """Open a Shoot folder, or make an existing folder of JPGs into a Shoot.

        Adds any JPGs not yet in the state file (reading their EXIF, a few ms each), applies a
        mark backup left from a disconnected drive, and saves. `progress(done, total)` is called
        while reading EXIF and may return False to cancel (returns None then).
        """
        folder = Path(folder)
        shoot = cls.read(folder) if cls.is_shoot(folder) else cls(folder)
        if not shoot.scan(progress):
            return None
        shoot.apply_backup()
        shoot.save()
        return shoot

    def scan(self, progress=None):
        on_disk = {n.lower(): n for n in os.listdir(self.folder) if is_jpg(n)}
        known = {p.name.lower() for p in self.photos}
        for photo in self.photos:
            photo.present = photo.name.lower() in on_disk
        new = [n for key, n in on_disk.items() if key not in known]
        for i, name in enumerate(new):
            if progress and progress(i, len(new)) is False:
                return False
            info = read_jpg_info(self.folder / name)
            self.photos.append(Photo(name, info.captured.isoformat(), info.camera))
        self.sort()
        return True

    def sort(self):
        # Display order is fixed to capture time, so two cameras' photos interleave as shot.
        self.photos.sort(key=lambda p: (p.captured, p.name.lower()))

    # ---------- about the Shoot ----------

    @property
    def name(self):
        return self.folder.name

    @property
    def exported(self):
        return self.exported_at is not None

    def cull_photos(self):
        """The photos that can be culled: those whose JPG is in the folder, in capture order."""
        return [p for p in self.photos if p.present]

    def photo(self, name):
        name = name.lower()
        return next((p for p in self.photos if p.name.lower() == name), None)

    def counts(self):
        return Counts(len(self.photos),
                      sum(p.mark == PICK for p in self.photos),
                      sum(p.mark == REJECT for p in self.photos))

    def summary(self):
        """For the home screen, e.g. "138 photos · 40 unmarked · not exported"."""
        c = self.counts()
        status = f"exported {self.exported_at[:10]}" if self.exported else "not exported"
        return f"{c.total} photos · {c.picks} picks · {c.unmarked} unmarked · {status}"

    # ---------- changing ----------

    def set_mark(self, photo, mark):
        photo.mark = mark
        return self.save()

    def to_json(self):
        return {
            "app": "PhotoSort",
            "version": STATE_VERSION,
            "id": self.id,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "cards": self.cards,
            "last_viewed": self.last_viewed,
            "exported_at": self.exported_at,
            "photos": [p.to_json() for p in self.photos],
        }

    def save(self):
        """Write the state file. Returns False, keeping a backup on C:, if the drive is unreachable."""
        try:
            write_json(self.folder / STATE_FILE, self.to_json(), hidden=True)
        except OSError:
            if not self.unsaved:
                log.warning("Could not save %s; keeping a backup on C:", self.folder, exc_info=True)
            self.unsaved = True
            self.write_backup()
            return False
        if self.unsaved:
            log.info("Saved %s again after the drive came back", self.folder)
        self.unsaved = False
        self.backup_path().unlink(missing_ok=True)
        return True

    # ---------- backup for a disconnected drive ----------

    def backup_path(self):
        return app_dir() / "backups" / f"{self.id}.json"

    def write_backup(self):
        path = self.backup_path()
        path.parent.mkdir(exist_ok=True)
        write_json(path, {
            "folder": str(self.folder),
            "last_viewed": self.last_viewed,
            "marks": {p.name: p.mark for p in self.photos if p.mark},
        })

    def apply_backup(self):
        """Apply marks that couldn't be saved last time because the drive was unplugged."""
        path = self.backup_path()
        if not path.exists():
            return
        backup = read_json(path)
        marks = backup["marks"]
        for photo in self.photos:
            photo.mark = marks.get(photo.name)
        self.last_viewed = backup.get("last_viewed") or self.last_viewed
        log.info("Applied the mark backup for %s", self.folder)


def cache_dir(folder):
    path = Path(folder) / CACHE_DIR
    if not path.exists():
        path.mkdir()
        set_hidden(path)
    return path
