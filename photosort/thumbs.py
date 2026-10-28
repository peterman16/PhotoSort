"""The Grid thumbnail cache: ~400 px JPEGs in a hidden `.photosort\thumbs` folder in the Shoot.

Built during Import (or in the background the first time an existing folder is opened), and
deleted right after a successful Export, when the JPGs are gone.
"""
import io
import logging
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageOps
from PySide6.QtCore import QObject, Signal

from .shoot import CACHE_DIR, cache_dir

log = logging.getLogger(__name__)

THUMB_EDGE = 400
THUMB_QUALITY = 80


def thumbs_dir(folder):
    return Path(folder) / CACHE_DIR / "thumbs"


def thumb_path(folder, name):
    return thumbs_dir(folder) / (name + ".jpg")


def make_thumb(source):
    """JPEG bytes of an upright ~400 px thumbnail. `source` is a path or the JPG's bytes."""
    if isinstance(source, bytes):
        source = io.BytesIO(source)
    with Image.open(source) as im:
        im.draft("RGB", (THUMB_EDGE, THUMB_EDGE))
        upright = ImageOps.exif_transpose(im).convert("RGB")
    upright.thumbnail((THUMB_EDGE, THUMB_EDGE))
    out = io.BytesIO()
    upright.save(out, "JPEG", quality=THUMB_QUALITY)
    return out.getvalue()


def write_thumb(folder, name, source):
    """Make and save the Grid thumbnail for one JPG."""
    path = thumb_path(folder, name)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(make_thumb(source))
    os.replace(tmp, path)


def delete_thumbs(folder):
    """After Export: remove the whole hidden cache folder, leaving RAWs plus the state file."""
    shutil.rmtree(Path(folder) / CACHE_DIR, ignore_errors=True)


class ThumbBuilder(QObject):
    """Builds missing Grid thumbnails in the background (4 threads), for a Shoot that was
    opened as an existing folder rather than imported. Emits built(index) for each one."""

    built = Signal(int)

    def __init__(self, folder, names):
        super().__init__()
        self.folder = Path(folder)
        self.pool = ThreadPoolExecutor(4, thread_name_prefix="thumb-build")
        cache_dir(self.folder)  # makes the hidden .photosort folder
        for i, name in enumerate(names):
            if not thumb_path(self.folder, name).exists():
                self.pool.submit(self._build, i, name)

    def _build(self, i, name):
        try:
            write_thumb(self.folder, name, self.folder / name)
        except Exception:
            log.warning("Could not make a thumbnail for %s", name, exc_info=True)
            return
        self.built.emit(i)

    def close(self):
        self.pool.shutdown(wait=False, cancel_futures=True)
