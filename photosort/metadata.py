"""Reading capture time, camera model and the embedded thumbnail from photo files.

JPGs are read with Pillow (header only, a few ms each). Pillow can't read .CR3, so RAW camera
models are read with python-exiv2.
"""
import io
import logging
import os
from dataclasses import dataclass
from datetime import datetime

from PIL import ExifTags, Image

log = logging.getLogger(__name__)

TAG_MODEL = 0x0110
TAG_ORIENTATION = 0x0112
TAG_DATETIME = 0x0132
TAG_DATETIME_ORIGINAL = 0x9003
TAG_THUMB_OFFSET = 0x0201
TAG_THUMB_LENGTH = 0x0202

# EXIF orientation -> the Pillow transpose that makes the image upright
TRANSPOSE = {2: Image.FLIP_LEFT_RIGHT, 3: Image.ROTATE_180, 4: Image.FLIP_TOP_BOTTOM,
             5: Image.TRANSPOSE, 6: Image.ROTATE_270, 7: Image.TRANSVERSE, 8: Image.ROTATE_90}


@dataclass
class JpgInfo:
    captured: datetime
    camera: str | None


def _parse_exif_time(value):
    try:
        return datetime.strptime(str(value).strip("\0 "), "%Y:%m:%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def read_jpg_info(path):
    """Capture time and camera model. Falls back to the file's modified time if EXIF has no date."""
    captured, camera = None, None
    try:
        with Image.open(path) as im:
            exif = im.getexif()
            sub = exif.get_ifd(ExifTags.IFD.Exif)
            captured = _parse_exif_time(sub.get(TAG_DATETIME_ORIGINAL) or exif.get(TAG_DATETIME))
            camera = (str(exif.get(TAG_MODEL)).strip("\0 ") or None) if exif.get(TAG_MODEL) else None
    except Exception:
        log.warning("Could not read EXIF from %s", path, exc_info=True)
    if captured is None:
        captured = datetime.fromtimestamp(os.path.getmtime(path)).replace(microsecond=0)
    return JpgInfo(captured, camera)


def exif_thumbnail(path):
    """The camera's embedded thumbnail (160x120 on Canon), upright, as a Pillow image; None if missing."""
    with Image.open(path) as im:
        exif = im.getexif()
        ifd1 = exif.get_ifd(ExifTags.IFD.IFD1)
        if TAG_THUMB_OFFSET not in ifd1 or "exif" not in im.info:
            return None
        # The offset counts from the TIFF header, which starts after the 6-byte "Exif\0\0" marker.
        start = ifd1[TAG_THUMB_OFFSET] + 6
        raw = im.info["exif"][start:start + ifd1[TAG_THUMB_LENGTH]]
        orientation = exif.get(TAG_ORIENTATION)
    thumb = Image.open(io.BytesIO(raw))
    thumb.load()
    if orientation in TRANSPOSE:
        thumb = thumb.transpose(TRANSPOSE[orientation])
    return thumb


def raw_camera_model(path):
    """Camera model from a RAW file (.CR3 or .CR2), or None if it can't be read."""
    try:
        import exiv2
        exiv2.LogMsg.setLevel(exiv2.LogMsg.Level.mute)
        image = exiv2.ImageFactory.open(str(path))
        image.readMetadata()
        return str(image.exifData()["Exif.Image.Model"].toString()).strip() or None
    except Exception:
        log.warning("Could not read the camera model from %s", path, exc_info=True)
        return None


def camera_tag(model):
    """A short camera tag for filename clashes: "Canon EOS 70D" -> "70D", "Canon EOS R8" -> "R8"."""
    if not model:
        return "CAM"
    tag = "".join(c for c in model.split()[-1] if c.isalnum())
    return tag or "CAM"
