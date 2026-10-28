# PhotoSort

Cull a Shoot's JPGs with the keyboard (or an Xbox controller), then export only the Picks'
Companion RAWs (`.CR3`, `.CR2`) from the Card. Windows only. The vocabulary is in
[CONTEXT.md](CONTEXT.md), and background research is in [docs/research](docs/research).

## Install

You need Windows 10 or 11 and [Python 3.13](https://www.python.org/downloads/) installed with the
`py` launcher (the python.org installer's default).

1. Clone or download this repository.
2. Double-click `setup.bat`. It creates `.venv`, installs the pinned packages, and adds a
   PhotoSort shortcut to the desktop and the Start menu.

## Start it

Double-click **PhotoSort** on the desktop or in the Start menu. If it stops starting (for
example after a Python upgrade), double-click `setup.bat`. It rebuilds `.venv`, the icon and
the shortcuts. Code changes apply on the next launch with no rebuild.

To pin PhotoSort to the taskbar, right-click its taskbar button once and choose Pin. Windows
doesn't let programs pin themselves.

## The workflow

1. **Import from Card…** lists the card's photos by capture day. It skips photos that are
   already imported and copies the JPGs to `<Library>\YYYY\YYYY_MM_DD[ description]`. RAWs stay on the
   card. Grid thumbnails are built while copying.
2. **Cull.** Use ← → to move and A / S / D to Pick / Reject / Unmark. T turns on auto-advance,
   Z or a double-click zooms to 100%, R cycles the filter, and Tab switches between Filmstrip
   and Grid. Press `?` to see every key and controller button. Marks save as you make them.
3. **Export…** copies each Pick's RAW from the card (found by its volume serial, even under a
   new drive letter) and checks every copy against its checksum. You can rename the RAWs.
   PhotoSort then offers to send the verified Picks' JPGs and all Rejects' JPGs to the Recycle
   Bin, leaving a folder of RAWs.

PhotoSort never writes to the card. Deletes only go to the Recycle Bin.

## Trying it safely

To try it without touching real Shoots, change the **Destination** in the Import dialog to a
test folder, e.g. `C:\PhotoSortTest`. Use **Open folder as Shoot…** only on a *copy* of an
existing folder: Export recycles that folder's JPGs.

The Library is your Pictures folder by default. Pick another folder (for example an external
drive) as the Destination in the Import dialog.

## Where things live

| What | Where |
|---|---|
| A Shoot's marks and Export record | hidden `.photosort.json` in the Shoot folder (kept after Export) |
| Grid thumbnails | hidden `.photosort\thumbs` in the Shoot folder (deleted after Export) |
| Preferences, Shoot list, log, mark backups | `%LOCALAPPDATA%\PhotoSort` |

If something goes wrong, PhotoSort shows a dialog naming the log file:
`%LOCALAPPDATA%\PhotoSort\photosort.log`.

## For developers

- Code: `photosort/`. Each module starts with a docstring saying what it's for.
  - `shoot.py`: the state file.
  - `library.py`: the home screen's list of Shoots.
  - `importer.py` and `exporter.py`: Import and Export logic.
  - `images.py`: decoding and caches.
  - `gamepad.py`: the Xbox controller.
  - `ui/`: the screens.
- Run the tests with `.venv\Scripts\python -m pytest`. They use tiny generated JPGs, never real photos.
- To support another RAW format, add its extension to `RAW_EXTENSIONS` in `photosort/formats.py`.
- Set `PHOTOSORT_APPDATA` to a scratch folder to run with separate preferences and Shoot list.
- The shortcuts run the base `pythonw.exe` with `tools\launch.pyw`, not the venv's
  `pythonw.exe`. On Python 3.13.0 the venv's `pythonw.exe` opens a console window.

## License

MIT. See [LICENSE](LICENSE).
