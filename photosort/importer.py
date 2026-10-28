"""Import: copy JPGs from the Card into Shoot folders. RAWs stay on the Card until Export.

- Photos are grouped by capture day. By default the chosen days become one Shoot named by the
  first day; they can be split into one Shoot per day.
- New Shoots go to <root>\\YYYY\\YYYY_MM_DD[ description].
- A photo is "already imported" if its Card filename and capture time match a photo in a known
  Shoot; those are skipped by default.
- An Import for a date that already has a Shoot joins it, unless that Shoot is exported; then
  it goes to YYYY_MM_DD_2 (or _3, ...).
- If an incoming JPG's name clashes with a different photo in the Shoot, it gets a camera tag
  (IMG_3988.JPG -> IMG_3988_70D.JPG). Its RAW gets the same name at Export.
The Card is only ever read.
"""
import logging
import os
import re
import shutil
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import drives
from .formats import is_jpg
from .metadata import camera_tag, read_jpg_info
from .shoot import Photo, Shoot
from .thumbs import write_thumb

log = logging.getLogger(__name__)

SAVE_EVERY = 50  # photos; an interrupted Import can be re-run and skips what's already there


@dataclass
class CardPhoto:
    path: Path               # where it is on the Card
    source: str              # path relative to the Card's root, e.g. DCIM\100CANON\IMG_0001.JPG
    captured: datetime
    camera: str | None
    already_imported: bool = False

    @property
    def name(self):
        return self.path.name

    @property
    def key(self):
        return self.name.lower(), self.captured.isoformat()


@dataclass
class Card:
    root: Path               # the folder that was scanned (usually the Card's DCIM folder)
    serial: str | None
    label: str
    photos: list             # CardPhoto, in capture order


def scan_card(folder, known_keys, progress=None):
    """Find every JPG under `folder` and read its capture time. `progress(done, total)` may
    return False to cancel (returns None then)."""
    folder = Path(folder)
    drive = drives.volume_of(folder)
    paths = sorted(Path(dirpath) / n for dirpath, _, names in os.walk(folder) for n in names if is_jpg(n))
    photos = []
    for i, path in enumerate(paths):
        if progress and progress(i, len(paths)) is False:
            return None
        info = read_jpg_info(path)
        source = str(path.relative_to(path.anchor))
        photo = CardPhoto(path, source, info.captured, info.camera)
        photo.already_imported = photo.key in known_keys
        photos.append(photo)
    photos.sort(key=lambda p: (p.captured, p.name.lower()))
    return Card(folder, drive.serial if drive else None, (drive.label if drive else "") or "card", photos)


def group_by_day(photos):
    """{date: [CardPhoto]} in date order."""
    days = {}
    for photo in photos:
        days.setdefault(photo.captured.date(), []).append(photo)
    return dict(sorted(days.items()))


# ---------- where each Shoot goes ----------

@dataclass
class Destination:
    folder: Path
    joins: bool              # adds to an existing, unexported Shoot


def _date_folders(year_dir, day):
    """Existing folders for this capture date, with their _N number (1 for the plain date)."""
    base = f"{day:%Y_%m_%d}"
    pattern = re.compile(rf"^{base}(?:_(\d+))?(?: .*)?$")
    found = []
    if year_dir.is_dir():
        for folder in year_dir.iterdir():
            m = pattern.match(folder.name)
            if folder.is_dir() and m:
                found.append((int(m.group(1) or 1), folder))
    return sorted(found)


def destination_for(root, day, description=""):
    year_dir = Path(root) / f"{day:%Y}"
    existing = _date_folders(year_dir, day)
    for _, folder in reversed(existing):
        if Shoot.is_shoot(folder) and not Shoot.read(folder).exported:
            return Destination(folder, joins=True)
    n = max((num for num, _ in existing), default=0) + 1
    name = f"{day:%Y_%m_%d}" + (f"_{n}" if n > 1 else "")
    description = description.strip()
    if description:
        name += " " + re.sub(r'[<>:"/\\|?*]', "-", description)
    return Destination(year_dir / name, joins=False)


def plan(root, days, description="", split_days=False):
    """[(Destination, [CardPhoto])] for the chosen days ({date: [CardPhoto]})."""
    if not days:
        return []
    if split_days:
        return [(destination_for(root, day, description), photos) for day, photos in days.items()]
    first = next(iter(days))
    return [(destination_for(root, first, description), [p for photos in days.values() for p in photos])]


# ---------- copying ----------

def free_name(name, camera, taken):
    """`name`, or a camera-tagged variant if a different photo already uses it."""
    if name.lower() not in taken:
        return name
    stem, ext = os.path.splitext(name)
    tagged = f"{stem}_{camera_tag(camera)}{ext}"
    n = 2
    while tagged.lower() in taken:
        tagged = f"{stem}_{camera_tag(camera)}_{n}{ext}"
        n += 1
    return tagged


def copy_into(destination, photos, card, progress=None):
    """Copy `photos` from the Card into the Shoot folder, building Grid thumbnails alongside.

    `progress(done, total, name)` may return False to stop early (what's copied is kept).
    Returns the Shoot.
    """
    folder = destination.folder
    folder.mkdir(parents=True, exist_ok=True)
    shoot = Shoot.read(folder) if Shoot.is_shoot(folder) else Shoot(folder)
    shoot.scan()  # picks up JPGs left by an interrupted Import
    if card.serial:
        shoot.cards[card.serial] = card.label
    by_key = {p.key: p for p in shoot.photos}
    taken = {p.name.lower() for p in shoot.photos}

    thumb_pool = ThreadPoolExecutor(4, thread_name_prefix="import-thumbs")
    try:
        for i, card_photo in enumerate(photos):
            if progress and progress(i, len(photos), card_photo.name) is False:
                break
            existing = by_key.get(card_photo.key)
            if existing is not None:  # already here: just make sure we know where it came from
                existing.card, existing.source = card.serial, card_photo.source
                continue
            name = free_name(card_photo.name, card_photo.camera, taken)
            data = card_photo.path.read_bytes()  # one read from the Card
            tmp = folder / (name + ".part")
            tmp.write_bytes(data)
            shutil.copystat(card_photo.path, tmp)
            os.replace(tmp, folder / name)
            thumb_pool.submit(_thumb, folder, name, data)

            photo = Photo(name, card_photo.captured.isoformat(), card_photo.camera,
                          original=card_photo.name if name != card_photo.name else None,
                          card=card.serial, source=card_photo.source)
            shoot.photos.append(photo)
            by_key[photo.key] = photo
            taken.add(name.lower())
            if i % SAVE_EVERY == SAVE_EVERY - 1:
                shoot.sort()
                shoot.save()
    finally:
        thumb_pool.shutdown(wait=True)
        shoot.sort()
        shoot.save()
    return shoot


def _thumb(folder, name, data):
    try:
        write_thumb(folder, name, data)
    except Exception:
        log.warning("Could not make a thumbnail for %s", name, exc_info=True)
