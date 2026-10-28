"""Small file helpers: hidden files and crash-safe JSON writes."""
import ctypes
import json
import os
from pathlib import Path

FILE_ATTRIBUTE_HIDDEN = 0x2
INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF


def set_hidden(path):
    kernel32 = ctypes.windll.kernel32
    attrs = kernel32.GetFileAttributesW(str(path))
    if attrs != INVALID_FILE_ATTRIBUTES and not attrs & FILE_ATTRIBUTE_HIDDEN:
        kernel32.SetFileAttributesW(str(path), attrs | FILE_ATTRIBUTE_HIDDEN)


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path, data, hidden=False):
    """Write JSON so a crash or unplugged drive never leaves a half-written file.

    The data goes to a temporary file first, which then replaces the old file in one step.
    (Windows refuses to overwrite a hidden file in place, which this also avoids.)
    """
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
    if hidden:
        set_hidden(path)
