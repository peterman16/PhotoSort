r"""Writes PhotoSort's desktop and Start-menu shortcuts. Run by setup.bat.

Each shortcut starts the base Python's pythonw.exe (no console window) with tools\launch.pyw,
which uses the venv's packages (see that file for why). Each carries PhotoSort's
AppUserModelID so the taskbar groups it as its own program.
"""
import os
import sys
from pathlib import Path

import pythoncom
from win32com.client import Dispatch
from win32com.propsys import propsys, pscon
from win32com.shell import shell, shellcon

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
from photosort import APP_ID, APP_NAME  # noqa: E402

LAUNCHER = REPO / "tools" / "launch.pyw"
ICON = REPO / "photosort" / "resources" / "photosort.ico"


def base_pythonw():
    """pythonw.exe of the Python the venv was made from (the "home" line in pyvenv.cfg)."""
    for line in (REPO / ".venv" / "pyvenv.cfg").read_text().splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "home":
            return Path(value.strip()) / "pythonw.exe"
    raise SystemExit(r".venv\pyvenv.cfg has no home line; run setup.bat")


def shortcut_folders():
    # Ask Windows: the Desktop may be redirected (e.g. into OneDrive).
    return [Path(shell.SHGetFolderPath(0, folder, None, 0))
            for folder in (shellcon.CSIDL_DESKTOPDIRECTORY, shellcon.CSIDL_PROGRAMS)]


def write_shortcut(path):
    path = os.path.abspath(path)  # the shell property API rejects forward slashes
    link = Dispatch("WScript.Shell").CreateShortcut(str(path))
    link.TargetPath = str(base_pythonw())
    link.Arguments = f'"{LAUNCHER}"'
    link.WorkingDirectory = str(REPO)
    link.Description = "Cull JPGs and export the Picks' RAWs"
    if ICON.exists():
        link.IconLocation = str(ICON)
    link.Save()

    store = propsys.SHGetPropertyStoreFromParsingName(
        str(path), None, shellcon.GPS_READWRITE, propsys.IID_IPropertyStore)
    store.SetValue(pscon.PKEY_AppUserModel_ID, propsys.PROPVARIANTType(APP_ID, pythoncom.VT_LPWSTR))
    store.Commit()


def main():
    if not base_pythonw().exists():
        sys.exit(f"{base_pythonw()} is missing; run setup.bat")
    for folder in shortcut_folders():
        path = folder / f"{APP_NAME}.lnk"
        write_shortcut(path)
        print(f"  wrote {path}")


if __name__ == "__main__":
    main()
