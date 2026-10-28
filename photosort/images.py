"""Decoding photos for the Cull, ahead of time, within a fixed memory budget.

- ImageCache: screen-sized copies of the current photo and its neighbours, decoded on 4 threads
  (6 ahead, 2 behind) into a 12-frame cache, plus one full-resolution slot for 100% zoom.
- ThumbStore: small images for the filmstrip, the Grid and the held-Next placeholder. Each comes
  from the Grid thumbnail cache on disk when it's been built, otherwise from the JPG's embedded
  EXIF thumbnail. Only the most recently used ones stay in memory.

Both emit `loaded(index)` (on the GUI thread) when an image becomes available.
"""
import logging
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageOps
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QImage

from .metadata import TAG_ORIENTATION, exif_thumbnail
from .thumbs import thumb_path

log = logging.getLogger(__name__)

SCREEN_FRAMES = 12
LOOK_AHEAD, LOOK_BEHIND = 6, 2
DECODE_THREADS = 4
SMALL_EDGE = 240          # long edge of in-memory thumbnails, in pixels
SMALL_CAPACITY = 600      # about 90 MB


def to_qimage(im):
    im = im.convert("RGB")
    return QImage(im.tobytes(), im.width, im.height, im.width * 3, QImage.Format_RGB888).copy()


def decode(path, fit=None):
    """Decode a JPG, upright. With `fit` (w, h), decode at reduced size (Pillow's draft mode,
    much faster) and shrink to fit. Returns (QImage, full size (w, h) of the upright photo)."""
    with Image.open(path) as im:
        w, h = im.size  # read before draft() shrinks it
        rotated = im.getexif().get(TAG_ORIENTATION) in (5, 6, 7, 8)
        if fit:
            fit = (fit[1], fit[0]) if rotated else fit  # we shrink before turning upright
            im.draft("RGB", fit)
            im.thumbnail(fit, Image.BILINEAR)  # turning a smaller image upright is cheaper
        upright = ImageOps.exif_transpose(im)
        return to_qimage(upright), ((h, w) if rotated else (w, h))


class ImageCache(QObject):
    loaded = Signal(int)

    def __init__(self, paths, screen_size):
        super().__init__()
        self.paths = paths
        self.screen_size = screen_size
        self.frames = OrderedDict()   # index -> QImage, least recently used first
        self.pending = set()
        self.full_sizes = {}          # index -> (w, h) of the full-resolution photo
        self.full = (None, None)      # (index, QImage) for 100% zoom
        self.full_wanted = None
        self.center = 0
        self.lock = threading.Lock()
        self.pool = ThreadPoolExecutor(DECODE_THREADS, thread_name_prefix="decode")
        # Zoom gets its own thread so it never waits behind look-ahead decodes.
        self.full_pool = ThreadPoolExecutor(1, thread_name_prefix="decode-full")

    def request(self, i):
        """Start decoding photo i and its neighbours, nearest first."""
        n = len(self.paths)
        order = [i] + list(range(i + 1, min(n, i + LOOK_AHEAD + 1))) + \
            list(range(i - 1, max(-1, i - LOOK_BEHIND - 1), -1))
        with self.lock:
            self.center = i
            for j in order:
                if j not in self.frames and j not in self.pending:
                    self.pending.add(j)
                    self.pool.submit(self._decode, j)
            if i in self.frames:
                self.frames.move_to_end(i)

    def _decode(self, i):
        with self.lock:
            if not -LOOK_BEHIND - 2 <= i - self.center <= LOOK_AHEAD + 2:
                self.pending.discard(i)  # we've moved on; don't spend a thread on it
                return
        try:
            img, full_size = decode(self.paths[i], self.screen_size)
        except Exception:
            log.exception("Could not decode %s", self.paths[i])
            with self.lock:
                self.pending.discard(i)
            return
        with self.lock:
            self.frames[i] = img
            self.full_sizes[i] = full_size
            self.pending.discard(i)
            while len(self.frames) > SCREEN_FRAMES:
                self.frames.popitem(last=False)
        self.loaded.emit(i)

    def get(self, i):
        with self.lock:
            return self.frames.get(i)

    def full_size(self, i):
        return self.full_sizes.get(i)

    def request_full(self, i):
        if self.full[0] != i and self.full_wanted != i:
            self.full_wanted = i
            self.full_pool.submit(self._decode_full, i)

    def _decode_full(self, i):
        if self.full_wanted != i:
            return
        try:
            img, size = decode(self.paths[i])
        except Exception:
            log.exception("Could not decode %s", self.paths[i])
            return
        if self.full_wanted == i:
            self.full = (i, img)  # replaces the previous one: only one full-size frame in memory
            self.full_sizes[i] = size
            self.loaded.emit(i)

    def get_full(self, i):
        index, img = self.full
        return img if index == i else None

    def close(self):
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.full_pool.shutdown(wait=False, cancel_futures=True)


class ThumbStore(QObject):
    loaded = Signal(int)

    def __init__(self, folder, names):
        super().__init__()
        self.folder = folder
        self.names = names
        self.images = OrderedDict()   # index -> (QImage, from_disk_cache)
        self.pending = set()
        self.asked = {}               # index -> frame number when last asked for
        self.frame = 0
        self.lock = threading.Lock()
        self.pool = ThreadPoolExecutor(2, thread_name_prefix="thumbs")

    def next_frame(self):
        """Call once per paint: thumbnails not asked for in the last few paints are skipped."""
        self.frame += 1

    def get(self, i):
        with self.lock:
            self.asked[i] = self.frame
            entry = self.images.get(i)
            if entry is not None:
                self.images.move_to_end(i)
                return entry[0]
            if i not in self.pending:
                self.pending.add(i)
                self.pool.submit(self._load, i)
        return None

    def _load(self, i):
        with self.lock:
            if self.frame - self.asked.get(i, 0) > 3:
                self.pending.discard(i)
                return
        image, from_disk = None, False
        try:
            cached = thumb_path(self.folder, self.names[i])
            if cached.exists():
                image, from_disk = Image.open(cached), True
            else:
                image = exif_thumbnail(self.folder / self.names[i])
                if image is None:  # no embedded thumbnail: decode small
                    with Image.open(self.folder / self.names[i]) as im:
                        im.draft("RGB", (SMALL_EDGE, SMALL_EDGE))
                        image = ImageOps.exif_transpose(im)
            image.thumbnail((SMALL_EDGE, SMALL_EDGE))
            qimage = to_qimage(image)
        except Exception:
            log.warning("No thumbnail for %s", self.names[i], exc_info=True)
            qimage = None
        with self.lock:
            self.pending.discard(i)
            if qimage is not None:
                self.images[i] = (qimage, from_disk)
                while len(self.images) > SMALL_CAPACITY:
                    self.images.popitem(last=False)
        if qimage is not None:
            self.loaded.emit(i)

    def disk_thumb_built(self, i):
        """The Grid thumbnail for photo i has just been built: replace its EXIF placeholder."""
        with self.lock:
            entry = self.images.get(i)
            if entry is not None and not entry[1]:
                del self.images[i]

    def close(self):
        self.pool.shutdown(wait=False, cancel_futures=True)
