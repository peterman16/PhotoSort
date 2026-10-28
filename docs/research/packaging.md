# Packaging research: launching a PySide6 app with one click on Windows

Researched 2026-10-27 while choosing how to install and launch PhotoSort. This note gathers the evidence and gives a recommendation with its tradeoffs.

## TL;DR

- **Every option can give a one-click Start-menu or desktop shortcut with an icon.** What separates them is what happens **after an agent changes the code**.
- **Plain venv + `.lnk` to `pythonw.exe`:** the next launch picks up a code change with no rebuild. It was the slowest to start of the folder-based options in the local test, at about 1 s warm.
- **PyInstaller one-folder** and **Nuitka standalone:** both start in about 0.4–0.5 s warm, but every code change needs a rebuild of about 1 minute.
  - Nuitka's first build took about 10 minutes here, because it downloaded a C compiler (Zig).
  - Qt's own `pyside6-deploy` wraps Nuitka and also needs MSVC's `dumpbin`, which this PC doesn't have.
- **PyInstaller one-file** was the slowest to start: 2.5–4.6 s on every launch, because it unpacks to a temp folder each time. **Briefcase** adds an MSI install step to every update. Neither suits an app the agent keeps changing.
- **Antivirus:** Defender flagged none of the test builds. The primary sources say almost nothing about false positives, so treat this as one observation, not a guarantee. Locally built files don't carry the internet download mark that triggers a SmartScreen reputation check (see below).

## Local measurement (this PC)

Setup:
- **Machine:** Intel i5-1035G7, Windows 11 Home, Defender real-time protection on.
- **Software:** Python 3.13.0, PySide6-Essentials 6.12.0, Pillow 13.0.0, PyInstaller 6.22.3, Nuitka 4.3.1 (backend compiler Zig 0.16.0, downloaded automatically).
- **Test app:** a trivial window that imports `PySide6.QtWidgets` and `PIL.Image`, shows a `QLabel`, and records the time once the event loop runs.
- **What was timed:** from `Start-Process` to that timestamp.

The builds lived in `C:\Temp` and were deleted afterwards, along with Nuitka's download cache (~490 MB in `%LOCALAPPDATA%\Nuitka`).

| Option | Size on disk | First launch after build | Warm launches (ms) | Build time |
|---|---|---|---|---|
| venv + `pythonw.exe app.py` | venv ≈ PySide6 install (no copy) | 4,145 ms (includes `.pyc` compile) | 955, 908, 1129, 891, 1131 | none |
| PyInstaller `--onedir --windowed` | 108 MB folder | 1,520 ms | 609, 482, 515, 525, 502 | 77 s first, 64 s rebuild |
| PyInstaller `--onefile --windowed` | 44 MB single exe | 4,166 ms | 3551, 2654, 3182, 4635, 2552 | 85 s |
| Nuitka `--mode=standalone` + `pyside6` plugin | 83 MB folder | 1,004 ms | 513, 432, 386, 414, 380 | ~10.5 min first (incl. compiler download), 63 s rebuild with cache |

Caveats:
- This is a trivial window. The real app will add its own import and start-up work equally to every option.
- "First launch" here is first-after-build, not a true cold boot.
- Using `PySide6-Essentials` instead of the full `PySide6` keeps the bundles smaller. The full wheel also **failed to install into a deep path** because Windows long paths aren't enabled: pip error on a `PySide6\qml\...\qrc_*.cpp.obj` file. Keep the venv at a short path such as `C:\Projects\PhotoSort\.venv`.
- `Get-MpThreatDetection` showed no Defender detections after building and running all four.

## Options in detail

### 1. Plain venv + shortcut to `pythonw.exe`

- **How it launches:** a `.lnk` with target `<repo>\.venv\Scripts\pythonw.exe` and argument `<repo>\photosort\main.py` (or `-m photosort`). It has its own icon (`.ico`) and "Start in" folder.
- **Console:** `pythonw` is "a windowed version that avoids creating a console window" ([Python on Windows](https://docs.python.org/3/using/windows.html)). A `.bat` file runs through `cmd.exe` and opens a console window, so point the shortcut at `pythonw.exe`, not a `.bat`.
- **Shortcut placement:** Start-menu shortcuts are shell links placed in the Programs known folder (`FOLDERID_Programs`, per user `%APPDATA%\Microsoft\Windows\Start Menu\Programs`) ([Microsoft: add shortcuts to the Start menu](https://learn.microsoft.com/en-us/windows/win32/shell/how-to-add-shortcuts-to-the-start-menu)). An agent can create the `.lnk` from a script (PowerShell `WScript.Shell` `CreateShortcut`, or pywin32), so the user never types anything.
- **Taskbar identity:**
  - The running process is Python's, so by default Windows groups the window under Python on the taskbar.
  - Microsoft's guidance for an app "running in a host process" is to set an explicit AppUserModelID. It goes on the shortcut (`System.AppUserModel.ID`) and on the process, through `SetCurrentProcessExplicitAppUserModelID`, called "before the application presents any UI" ([AppUserModelIDs](https://learn.microsoft.com/en-us/windows/win32/shell/appids)).
  - Together with `QApplication.setWindowIcon`, that gives PhotoSort its own taskbar button and icon. This is a few lines of code plus the shortcut property. It applies to frozen builds too, but they have their own exe, so it matters less there.
- **Updates:** an agent edits the `.py` files, and the next launch runs the new code. No build step. A dependency change is a `pip install` into the venv.
- **Fragility:**
  - Venvs are "not considered as movable or copyable – you just recreate the same environment in the target location" ([venv docs](https://docs.python.org/3/library/venv.html)).
  - On Windows, the venv's `python[w].exe` are redirectors to the base install ([venv docs](https://docs.python.org/3/library/venv.html), "Changed in version 3.7.2"). This venv's base is the per-user Python 3.13 install (`%LOCALAPPDATA%\Programs\Python\Python313`), so uninstalling or upgrading that Python breaks the venv until it is recreated.
  - Moving the repo also means recreating the venv and the shortcut.
- **Errors are invisible:** `pythonw` has no console, so an uncaught exception at start-up just means "nothing happened". The app must log to a file and should show a Qt error dialog on uncaught exceptions. The same applies to any `--windowed` frozen build.
- **Antivirus:** nothing new is executed. `pythonw.exe` is the signed python.org binary.

### 2. PyInstaller, one-folder (`--onedir`, default)

- **How it works:** "an executable plus all dependencies in one directory". The bootloader starts the bundled interpreter directly, with no extraction ([Operating mode](https://pyinstaller.org/en/stable/operating-mode.html)).
- **Options:** `--windowed` gives no console, `--icon app.ico` sets the exe icon, and `--contents-directory` names the support folder ([Usage](https://pyinstaller.org/en/stable/usage.html)).
- **Version support:** current release 6.22.3 (2026-09-12). Python 3.13 support since 6.10, 3.14 since 6.15 ([changelog](https://pyinstaller.org/en/stable/CHANGES.html)).
- **Qt support:** Qt for Python's deployment page lists PyInstaller as supporting Qt 6 only partially ([Qt for Python: Deployment](https://doc.qt.io/qtforpython-6/deployment/index.html)). PyInstaller's changelog keeps adding PySide6 hooks, for example `QtGraphsWidgets` for 6.8. The trivial test app built and ran cleanly.
- **UPX:** UPX compression is optional and can corrupt binaries. Since 4.3, Qt plugins are excluded from it automatically ([Usage](https://pyinstaller.org/en/stable/usage.html)). Leave UPX off; it saves little here and is a common antivirus trigger.
- **Updates:**
  - Every code change means re-running `pyinstaller photosort.spec` (≈ 1 min here) into the same `dist` folder that the shortcut points at.
  - Windows locks a running exe and its DLLs, so **close the app before rebuilding**.
  - PyInstaller's own docs note that in onedir mode you can ship only the changed exe when dependencies are unchanged ([Operating mode](https://pyinstaller.org/en/stable/operating-mode.html)), but a full rebuild is simpler for an agent.
- **No built-in updater:** Qt notes that none of these tools has an update mechanism ([Qt for Python: Deployment](https://doc.qt.io/qtforpython-6/deployment/index.html)). That doesn't matter here, because the build is local.

### 3. PyInstaller, one-file (`--onefile`)

- **How it works:** at each launch the bootloader creates a `_MEIxxxxxx` temp folder, "uncompresses the support files and writes copies into the the temporary folder", and deletes it on exit. It is "a little slower to start than a one-folder app". A crash leaves the folder behind ([Operating mode](https://pyinstaller.org/en/stable/operating-mode.html)).
- **Measured:** "a little slower" was 2.5–4.6 s versus 0.5 s for onedir on this laptop, with high variance. Antivirus scanning of the freshly extracted files is the likely cause.
- **Antivirus-related changelog entries:**
  - Temp-folder cleanup now retries "if anti-virus or the OS keeps files locked" (6.11.1).
  - Macos onefile `.app` bundles are deprecated because OS security scanning penalises them (6.13.0).
  - ([changelog](https://pyinstaller.org/en/stable/CHANGES.html)).
- **Only advantage:** a single file. That matters for distribution, which is out of scope for PhotoSort.

### 4. Nuitka (`--mode=standalone` or `--mode=onefile`), and `pyside6-deploy`

- **How it works:** Nuitka compiles Python to C and links it against libpython. It supports Python 3.4–3.14 ([Nuitka user manual](https://nuitka.net/user-documentation/user-manual.html)).
- **Compiler requirements on Windows:**
  - Visual Studio 2022+, its bundled clang-cl, MinGW64, or Zig (x64 only) ([user manual](https://nuitka.net/user-documentation/user-manual.html)).
  - "MinGW64 does not work with Python 3.13 or higher" without an experimental flag (same source).
  - With `--assume-yes-for-downloads`, Nuitka fetched Zig and Dependency Walker by itself here. No Visual Studio was needed.
- **Relevant options:**
  - `--enable-plugin=pyside6` handles the Qt plugins.
  - `--windows-console-mode=disable` gives no console window.
  - `--windows-icon-from-ico` accepts `.ico` or `.png`.
  - (All from the [user manual](https://nuitka.net/user-documentation/user-manual.html).)
- **Onefile:**
  - By default it unpacks to `{TEMP}/onefile_{PID}_{TIME}` and deletes that afterwards.
  - `--onefile-tempdir-spec="{CACHE_DIR}/{COMPANY}/{PRODUCT}/{VERSION}"` keeps a cached unpack, which avoids re-extracting on every run. Microsoft's firewall is the stated reason to use a stable path ([Nuitka use cases](https://nuitka.net/user-documentation/use-cases.html)).
  - `--onefile-cache-mode` (`auto` / `cached` / `temporary`) arrived in early 2025 ([Nuitka blog, Feb 2025](https://nuitka.net/posts/nuitka-this-week-16.html)).
  - Onefile wasn't measured here.
- **Measured:**
  - Fastest warm start of all options (≈ 0.4 s) and the smallest folder (83 MB).
  - Slowest first build (~10.5 min, including downloads).
  - A rebuild with a warm cache took 63 s, about the same as PyInstaller. Deleting the cache brings back the slow first build.
- **`pyside6-deploy`:**
  - This is Qt for Python's own tool, and the one Qt recommends: "easier to use and also to get the most optimized executable" ([Qt for Python: Deployment](https://doc.qt.io/qtforpython-6/deployment/index.html)).
  - It wraps Nuitka (default Nuitka 4.1.1). Its settings live in a `pysidedeploy.spec`, or `[tool.pyside6.deploy]` in `pyproject.toml`, which you can keep under version control.
  - **Since 6.12 its default mode is standalone (a `.dist` folder), no longer onefile** ([pyside6-deploy](https://doc.qt.io/qtforpython-6/deployment/deployment-pyside6-deploy.html)).
  - On Windows it requires `dumpbin` from MSVC on PATH ("Run vcvarsall.bat"; same page). That means installing VS Build Tools on this PC. Plain Nuitka with Zig avoided that.
- **Antivirus:**
  - Nuitka's official docs don't discuss false positives.
  - Claims that Nuitka builds are "never flagged" come from third-party sites, some selling competing tools, and are unverified.
  - Nuitka's onefile uses the same self-extracting pattern as PyInstaller's onefile.

### 5. Briefcase (BeeWare)

- **Setup:** `briefcase new` offers a PySide6 bootstrap ([Briefcase `new`](https://briefcase.beeware.org/en/stable/reference/commands/new/)).
- **How it bundles:** on Windows it builds an app folder around the **python.org Windows embeddable distribution** and a precompiled stub binary.
- **Packaging:** `briefcase package` produces an **MSI** (WiX Toolset) or, with `-p zip`, a ZIP. The MSI creates the launcher menu entry with the `.ico` (16–256 px), plus an optional desktop shortcut ([Briefcase Windows reference](https://briefcase.beeware.org/en/stable/reference/platforms/windows/index.html)).
- **Qt support:** Qt for Python lists Briefcase as supporting Qt 6 only partially ([Qt for Python: Deployment](https://doc.qt.io/qtforpython-6/deployment/index.html)).
- **Updates:**
  - `briefcase dev` runs from source in its own venv ([Briefcase `dev`](https://briefcase.beeware.org/en/stable/reference/commands/dev/)). That's like option 1, but without a shortcut.
  - Getting a one-click shortcut means running `briefcase update`, `briefcase build` and `briefcase package`, then **installing the MSI** after each change.
  - It also needs a `pyproject.toml` in Briefcase's layout.
  - This is the heaviest loop of all the options, for features (installer, cross-platform, mobile) that PhotoSort lists as out of scope.
- Not measured.

## Antivirus false positives: what the sources actually say

- **No primary source quantifies false-positive rates** for PyInstaller, Nuitka or Briefcase. Neither PyInstaller's troubleshooting page nor Nuitka's manual mentions antivirus software.
- PyInstaller's changelog shows the project works *around* antivirus interference: build retries and temp cleanup retries ([changelog](https://pyinstaller.org/en/stable/CHANGES.html)).
- **SmartScreen** checks "downloaded files", and items with no reputation get a warning ([SmartScreen overview](https://learn.microsoft.com/en-us/windows/security/operating-system-security/virus-and-threat-protection/microsoft-defender-smartscreen/)). PhotoSort is built on this PC and never downloaded, so this path doesn't apply.
- **If Defender does flag a build,** Microsoft's route is to submit the file at the [Security Intelligence submission portal](https://www.microsoft.com/wdsi/filesubmission/). A file exclusion is a temporary mitigation, and Microsoft warns that "Every exclusion lowers your level of protection" ([Defender false positives](https://learn.microsoft.com/en-us/defender-endpoint/defender-endpoint-false-positives-negatives)). Rebuilds produce new hashes, so a frozen build could be re-flagged after any change.
- **Ranking by exposure:**
  - venv + `pythonw` (signed python.org exe, no new binaries) has the least exposure.
  - Onedir frozen builds (PyInstaller, Nuitka) come next.
  - Onefile self-extractors have the most.

## Comparison table

Ratings: ++ strong, + good, 0 neutral, − weak, −− poor.

| Criterion | venv + `.lnk` → `pythonw` | PyInstaller onedir | PyInstaller onefile | Nuitka standalone / `pyside6-deploy` | Briefcase (MSI) |
|---|---|---|---|---|---|
| Warm start (trivial window, measured) | 0 ~0.9–1.1 s | + ~0.5 s | −− 2.5–4.6 s every launch | ++ ~0.4 s | not measured (embedded CPython, expect ≈ venv) |
| First launch after change | − ~4 s once (`.pyc` compile) | + ~1.5 s | −− ~4 s | + ~1.0 s | not measured |
| Size on disk | 0 shares venv; no extra copy | − 108 MB | + 44 MB | 0 83 MB | − folder + MSI |
| Antivirus exposure | ++ signed python.org exe only | + none seen; new unsigned exe per build | − self-extractor pattern | + none seen; onefile same caveat as PyInstaller | + none known; new MSI per build |
| Update after agent edits code | ++ nothing; next launch uses it | − rebuild ~1 min, close app first | − rebuild ~1.5 min | − rebuild ~1 min (first build ~10 min); `pyside6-deploy` needs MSVC | −− update + build + package + install MSI |
| Ease of rebuilding for an agent | ++ n/a | + one command with a `.spec` file | + one command | 0 one command, compiler toolchain to keep | − several commands + installer |
| Start-menu/desktop shortcut with icon | + script creates `.lnk`; set AppUserModelID + window icon for own taskbar button | + `--icon`; script creates `.lnk` to exe | + same | + `--windows-icon-from-ico`; script creates `.lnk` | ++ MSI creates menu entry (+ optional desktop) |
| Robustness to environment changes | − breaks if base Python is removed/upgraded or repo moves (recreate venv) | ++ self-contained | ++ self-contained | ++ self-contained | ++ self-contained |
| Diagnosing crashes | 0 needs file log (no console) | 0 same with `--windowed` | 0 same | 0 same | 0 same |
| Fits "agent changes code, user clicks" loop | ++ | 0 | − | 0 | −− |

## Recommendation with tradeoffs (input to ticket 014, not a decision)

**Front-runner: plain venv + a Start-menu/desktop `.lnk` to `pythonw.exe`**, created by a script the agent runs. The app sets an AppUserModelID and window icon so it looks like its own program on the taskbar.

- **Why:** the user's loop is "the agent edits, I click". This is the only option where an edit can never leave a stale build behind the shortcut, and where nothing has to be rebuilt, re-signed or reinstalled. It also has the least antivirus exposure.
- **Tradeoffs:**
  - Start-up is about 0.5 s slower than a frozen build (≈ 1 s versus 0.5 s for a trivial window).
  - The first launch after a code change pays a one-off `.pyc` compile.
  - The venv must be recreated if the base Python 3.13 is removed or upgraded, or if the repo moves. A small "setup" script the agent can re-run covers this: create the venv, `pip install`, write the shortcut.
  - Uncaught errors are silent unless the app logs to a file and shows an error dialog. The app needs that anyway.

**Runner-up: PyInstaller one-folder**, if start-up speed or independence from the installed Python matters more than a zero-step update.

- **Tradeoffs:**
  - Every agent change must end with a rebuild of about a minute, with the app closed. Skip it and the shortcut runs old code.
  - It adds a 108 MB folder and a new unsigned exe after every build. None were flagged in testing, but that isn't guaranteed.

**Nuitka standalone** is the fastest to start, but brings a C toolchain (a Zig download, or MSVC for `pyside6-deploy`) and a ~10-minute first build, for about 0.1 s over PyInstaller. Worth it only if the frozen route is chosen and start-up becomes a real complaint.

**Not recommended:**
- **PyInstaller onefile:** multi-second start on every launch.
- **Briefcase:** an MSI install per update, and features PhotoSort doesn't need.

**A hybrid is possible:** develop and run daily from the venv shortcut, and keep a PyInstaller `.spec` in the repo for an occasional frozen snapshot. That is extra surface for little gain unless 014 wants a "known good" build to fall back on.

## Open questions / not verified

- Start-up times for the *real* app: imports, thumbnail cache, `python-exiv2` / pywin32 hooks. PyInstaller and Nuitka hooks for `python-exiv2` weren't tested. Its wheel bundles libexiv2 DLLs, which a frozen build must pick up.
- True cold-boot launch times (after a reboot) weren't measured, only first-after-build and warm.
- Nuitka onefile with a cached temp dir, and Briefcase, weren't built or timed.
- Antivirus behaviour beyond Windows Defender on this PC, and over time (signature updates), is unknown.
