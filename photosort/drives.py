"""Finding drives by volume serial number, which stays the same when the drive letter changes.

Used to recognise the Card at Export and the Library drive if it comes back under another letter.
"""
import ctypes
import os
import string
from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path

kernel32 = ctypes.windll.kernel32

DRIVE_REMOVABLE = 2
SEM_FAILCRITICALERRORS = 0x0001

# Don't let Windows pop up "There is no disk in the drive" for empty card-reader slots.
kernel32.SetErrorMode(SEM_FAILCRITICALERRORS)


@dataclass
class Drive:
    root: str        # e.g. "E:\\"
    serial: str      # e.g. "1A2B-3C4D"
    label: str       # e.g. "EOS_DIGITAL"
    removable: bool


def _volume_info(root):
    label = ctypes.create_unicode_buffer(261)
    serial = wintypes.DWORD()
    ok = kernel32.GetVolumeInformationW(root, label, len(label), ctypes.byref(serial), None, None, None, 0)
    if not ok:
        return None
    s = serial.value
    return f"{s >> 16:04X}-{s & 0xFFFF:04X}", label.value


def drive_root(path):
    return os.path.splitdrive(os.path.abspath(path))[0] + "\\"


def volume_of(path):
    """The Drive holding `path`, or None if it isn't available."""
    root = drive_root(path)
    info = _volume_info(root)
    if info is None:
        return None
    return Drive(root, info[0], info[1], kernel32.GetDriveTypeW(root) == DRIVE_REMOVABLE)


def list_drives():
    mask = kernel32.GetLogicalDrives()
    drives = []
    for i, letter in enumerate(string.ascii_uppercase):
        if mask & (1 << i):
            drive = volume_of(f"{letter}:\\")
            if drive:
                drives.append(drive)
    return drives


def find_drive(serial):
    """The root of the drive with this volume serial, or None if it isn't connected."""
    for drive in list_drives():
        if drive.serial == serial:
            return drive.root
    return None


def removable_drives_with_dcim():
    return [d for d in list_drives() if d.removable and (Path(d.root) / "DCIM").is_dir()]
