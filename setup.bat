@echo off
rem Builds (or rebuilds) PhotoSort's Python environment and its shortcuts.
rem Double-click this if PhotoSort stops starting, e.g. after a Python upgrade.
setlocal
cd /d "%~dp0"

echo Setting up PhotoSort in %CD%
echo.

py -3.13 --version >nul 2>&1
if errorlevel 1 (
    echo Python 3.13 was not found. Install it from python.org, then run setup.bat again.
    goto :fail
)

if exist .venv (
    echo Removing the old environment...
    rmdir /s /q .venv
    if exist .venv (
        echo Could not remove .venv. Close PhotoSort and try again.
        goto :fail
    )
)

echo Creating the environment...
py -3.13 -m venv .venv || goto :fail
.venv\Scripts\python -m pip install --quiet --upgrade pip || goto :fail

echo Installing packages (this takes a minute)...
.venv\Scripts\python -m pip install --quiet -r requirements.txt -r requirements-dev.txt || goto :fail

echo Making the icon and shortcuts...
.venv\Scripts\python tools\make_icon.py || goto :fail
.venv\Scripts\python tools\make_shortcuts.py || goto :fail

echo.
echo Done. Start PhotoSort from the desktop shortcut or the Start menu.
pause
exit /b 0

:fail
echo.
echo Setup failed. See the messages above.
pause
exit /b 1
