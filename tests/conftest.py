"""Test helpers. Tests never touch real photos: they make tiny JPGs in a temporary folder."""
import os
from datetime import datetime

import pytest
from PIL import Image

from photosort.metadata import TAG_DATETIME_ORIGINAL, TAG_MODEL, TAG_ORIENTATION


@pytest.fixture(autouse=True)
def app_data(tmp_path, monkeypatch):
    """Point PhotoSort's app-data folder at a temporary folder."""
    folder = tmp_path / "appdata"
    monkeypatch.setenv("PHOTOSORT_APPDATA", str(folder))
    return folder


def make_jpg(path, captured="2025:11:12 10:00:00", model="Canon EOS R8", size=(60, 40), orientation=1):
    """A tiny JPG with a capture time, camera model and embedded thumbnail."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    im = Image.new("RGB", size, (120, 80, 40))
    exif = im.getexif()
    exif[TAG_MODEL] = model
    exif[TAG_ORIENTATION] = orientation
    exif.get_ifd(0x8769)[TAG_DATETIME_ORIGINAL] = captured
    im.save(path, exif=exif)
    return path


def make_raw(path, content=b"raw data"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(content)
    return path


def capture_time(minute):
    return datetime(2025, 11, 12, 10, minute).strftime("%Y:%m:%d %H:%M:%S")
