"""Which file types PhotoSort handles.

To support another RAW format, add its extension to RAW_EXTENSIONS. Nothing else needs to change.
"""
from pathlib import Path

RAW_EXTENSIONS = (".CR3", ".CR2")  # Canon EOS R8, Canon EOS 70D
JPG_EXTENSIONS = (".JPG", ".JPEG")


def is_jpg(name):
    return Path(name).suffix.upper() in JPG_EXTENSIONS


def is_raw(name):
    return Path(name).suffix.upper() in RAW_EXTENSIONS
