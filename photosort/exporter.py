"""Export: copy each Pick's Companion RAW from the Card into the Shoot folder, verified.

- The Card is found by the volume serial recorded at Import. A Shoot opened from an existing
  folder has no recorded Card, so the DCIM folders of inserted removable drives are searched.
  Either way, "Locate RAWs…" can point at another folder (e.g. a backup drive).
- A Companion RAW has the same filename stem as the Card's JPG (case-insensitive). If several
  RAWs match, the one whose camera model matches the JPG is used; if that can't be told, the
  photo is listed instead of guessing.
- Each RAW is checksummed while it's read from the Card (one read), and the copy is checked
  against it. Re-running an interrupted Export skips RAWs that already verify.
- Afterwards, verified Picks' JPGs and all Rejects' JPGs can go to the Recycle Bin. A Pick
  with no RAW keeps its JPG. The Card is never modified.
"""
import hashlib
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from send2trash import send2trash

from . import drives
from .formats import RAW_EXTENSIONS
from .metadata import raw_camera_model
from .shoot import PICK, REJECT
from .thumbs import delete_thumbs

log = logging.getLogger(__name__)

CHUNK = 4 * 1024 * 1024
UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*]')  # not allowed in Windows filenames, or would leave the folder


# ---------- finding RAWs ----------

def _raw_index(paths):
    """{lowercase stem: [RAW paths]}. Each file is listed once, even if two searched folders
    overlap (e.g. Locate RAWs… pointed at a card whose DCIM is already searched)."""
    index, seen = {}, set()
    for path in paths:
        key = os.path.normcase(os.path.abspath(path))
        if path.suffix.upper() in RAW_EXTENSIONS and key not in seen:
            seen.add(key)
            index.setdefault(path.stem.lower(), []).append(path)
    return index


class RawFinder:
    def __init__(self, located=()):
        self.located = [Path(p) for p in located]   # folders chosen with "Locate RAWs…"
        self.folder_index = {}                        # one folder on a Card -> index
        self.tree_index = None                        # DCIM folders + located folders -> index

    def locate(self, folder):
        self.located.append(Path(folder))
        self.tree_index = None

    def _folder(self, folder):
        if folder not in self.folder_index:
            try:
                self.folder_index[folder] = _raw_index(p for p in folder.iterdir() if p.is_file())
            except OSError:
                self.folder_index[folder] = {}
        return self.folder_index[folder]

    def _trees(self):
        if self.tree_index is None:
            roots = [Path(d.root) / "DCIM" for d in drives.removable_drives_with_dcim()] + self.located
            paths = [Path(dirpath) / n for root in roots for dirpath, _, names in os.walk(root) for n in names]
            self.tree_index = _raw_index(paths)
        return self.tree_index

    def card_connected(self, photo):
        return not photo.card or drives.find_drive(photo.card) is not None

    def candidates(self, photo):
        """RAW files that could be this photo's Companion RAW.

        Returns None if the photo's Card isn't inserted and no folder has been located (wait)."""
        stem = Path(photo.original_name).stem.lower()
        found = []
        if photo.card and photo.source:
            root = drives.find_drive(photo.card)
            if root:
                found = self._folder(Path(root) / Path(photo.source).parent).get(stem, [])
            elif not self.located:
                return None
        if not found:
            found = self._trees().get(stem, [])
        return found

    def missing_cards(self, shoot, photos):
        """Labels of Cards that are needed but not inserted (while nothing has been located)."""
        if self.located:
            return []
        return sorted({shoot.cards.get(p.card, "card") for p in photos if not self.card_connected(p)})


# ---------- the plan ----------

@dataclass
class ExportItem:
    photo: object
    raw: Path | None = None       # the RAW to copy
    target: str | None = None     # its filename in the Shoot folder
    problem: str | None = None    # why there's no RAW to copy


def choose_raw(photo, candidates):
    if len(candidates) == 1:
        return candidates[0], None
    if not candidates:
        return None, "no RAW found"
    same_camera = [c for c in candidates if photo.camera and raw_camera_model(c) == photo.camera]
    if len(same_camera) == 1:
        return same_camera[0], None
    return None, f"{len(candidates)} RAWs match and the camera can't tell them apart"


def default_pattern(shoot):
    """`YYYY_MM_DD[_description]_{n}` from the Shoot folder name ("2025_09_20 Mount Baker")."""
    m = re.match(r"^(\d{4}_\d{2}_\d{2})(?:_\d+)?(?: (.*))?$", shoot.name)
    if m:
        date, description = m.group(1), (m.group(2) or "").strip()
    else:
        first = shoot.photos[0].captured if shoot.photos else datetime.now().isoformat()
        date, description = first[:10].replace("-", "_"), ""
    description = re.sub(r"\s+", "-", description)
    return f"{date}_{description}_{{n}}" if description else f"{date}_{{n}}"


def renamed(pattern, number, count):
    """The new stem for the number-th Pick: 3 digits, or 4 when there are more than 999 Picks."""
    digits = 4 if count > 999 else 3
    pattern = UNSAFE_CHARS.sub("-", pattern).strip(" .")  # keeps every file inside the Shoot folder
    if "{n}" not in pattern:
        pattern += "_{n}"
    return pattern.replace("{n}", f"{number:0{digits}d}")


def plan_export(shoot, finder, pattern=None):
    """An ExportItem for every Pick, in capture order. `pattern` turns on Batch rename."""
    picks = [p for p in shoot.photos if p.mark == PICK and (p.present or p.raw)]
    items = []
    for number, photo in enumerate(picks, start=1):
        stem = renamed(pattern, number, len(picks)) if pattern else Path(photo.name).stem
        item = ExportItem(photo)
        candidates = finder.candidates(photo)
        if candidates is None:
            item.problem = "its card isn't inserted"
        else:
            item.raw, item.problem = choose_raw(photo, candidates)
        if item.raw is not None:
            item.target = stem + item.raw.suffix
        else:
            item.target = stem + Path(photo.name).suffix  # a Pick without RAW is renamed in sequence
        items.append(item)
    return items


# ---------- copying ----------

class VerifyError(Exception):
    pass


def file_hash(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def copy_verified(source, dest):
    """Copy source to dest, checksumming as it's read, then check the written copy. Returns the
    SHA-256. Never overwrites a different file already at dest."""
    tmp = dest.with_name(dest.name + ".part")
    h = hashlib.sha256()
    with open(source, "rb") as src, open(tmp, "wb") as out:
        while chunk := src.read(CHUNK):
            h.update(chunk)
            out.write(chunk)
        out.flush()
        os.fsync(out.fileno())
    digest = h.hexdigest()
    try:
        if file_hash(tmp) != digest:
            raise VerifyError(f"the copy of {source.name} doesn't match the card")
        if dest.exists():
            if file_hash(dest) != digest:
                raise VerifyError(f"a different file named {dest.name} is already in the Shoot folder")
            tmp.unlink()
        else:
            os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)
    return digest


@dataclass
class ExportResult:
    copied: int = 0
    already_done: int = 0
    failed: list = field(default_factory=list)     # (ExportItem, message)
    stopped: bool = False

    @property
    def finished(self):
        """True if the Export completed and at least one RAW is in the Shoot folder. An Export
        that found no RAWs at all is not finished: nothing is recycled or marked exported."""
        return not self.failed and not self.stopped and self.copied + self.already_done > 0


def already_verified(item, folder):
    photo = item.photo
    dest = folder / item.target
    return photo.raw == item.target and photo.raw_hash and dest.exists() and file_hash(dest) == photo.raw_hash


def copy_raws(shoot, items, progress=None):
    """Copy every item's RAW. `progress(done, total, name)` may return False to stop."""
    result = ExportResult()
    to_copy = [i for i in items if i.raw is not None]
    for n, item in enumerate(to_copy):
        if progress and progress(n, len(to_copy), item.raw.name) is False:
            result.stopped = True
            break
        try:
            if already_verified(item, shoot.folder):
                result.already_done += 1
                continue
            item.photo.raw_hash = copy_verified(item.raw, shoot.folder / item.target)
            item.photo.raw = item.target
            result.copied += 1
        except (OSError, VerifyError) as e:
            log.warning("Export of %s failed", item.raw, exc_info=True)
            result.failed.append((item, str(e)))
        shoot.save()  # an interrupted Export can be re-run
    return result


# ---------- finishing ----------

def jpgs_to_remove(shoot, items):
    """JPGs that may go to the Recycle Bin: verified Picks' and all Rejects'."""
    verified = {id(i.photo) for i in items if i.photo.raw == i.target and i.photo.raw_hash}
    return [p for p in shoot.photos if p.present and (p.mark == REJECT or id(p) in verified)]


def finish(shoot, items, result, remove_jpgs, renaming):
    """Mark the Shoot exported (if the Export finished), rename RAW-less Picks' JPGs when
    renaming, move JPGs to the Recycle Bin if asked, and delete the Grid thumbnails.
    Returns the number of JPGs recycled."""
    if not result.finished:
        shoot.save()
        return 0
    if renaming:
        for item in items:
            photo = item.photo
            if item.raw is None and photo.present and photo.name != item.target:
                if not photo.original:
                    photo.original = photo.name
                os.rename(shoot.folder / photo.name, shoot.folder / item.target)
                photo.name = item.target
    recycled = 0
    if remove_jpgs:
        jpgs = jpgs_to_remove(shoot, items)
        if jpgs:
            send2trash([str(shoot.folder / p.name) for p in jpgs])
            for photo in jpgs:
                photo.present = False
            recycled = len(jpgs)
    shoot.exported_at = datetime.now().isoformat(timespec="seconds")
    shoot.save()
    delete_thumbs(shoot.folder)
    return recycled
