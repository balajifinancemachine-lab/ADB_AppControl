@echo off
rem ADB AppControl launcher: picks a working Python interpreter, then starts the GUI.
setlocal
cd /d "%~dp0"

rem Prefer Gold Standard Python 3.12, then project venv, then system pyw.
set "PYW="
set "PYCLI="

if exist "C:\Program Files\Python312\pythonw.exe" (
    set "PYW=C:\Program Files\Python312\pythonw.exe"
    set "PYCLI=C:\Program Files\Python312\python.exe"
)
if not defined PYW if exist "%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe" (
    set "PYW=%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"
    set "PYCLI=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
)
if not defined PYW (
    py -3.12 -c "import sys" >nul 2>nul && set "PYW=py -3.12" && set "PYCLI=py -3.12"
)
if not defined PYW (
    if exist ".venv\Scripts\pythonw.exe" (
        ".venv\Scripts\pythonw.exe" -c "import sys" >nul 2>nul && set "PYW=.venv\Scripts\pythonw.exe" && set "PYCLI=.venv\Scripts\python.exe"
    )
)
if not defined PYW (
    pythonw -c "import sys" >nul 2>nul && set "PYW=pythonw" && set "PYCLI=python"
)
if not defined PYW (
    python -c "import sys" >nul 2>nul && set "PYW=python" && set "PYCLI=python"
)
if not defined PYW (
    echo Python was not found. Install Python 3.10+ from https://www.python.org/downloads/
    echo then run:  python -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

rem If CLI arguments are provided (e.g. --test, --audit, --organize, --heal), run in console mode.
if not "%~1"=="" (
    "%PYCLI%" "appcontrol.pyw" %*
    exit /b %ERRORLEVEL%
)

start "" "%PYW%" "appcontrol.pyw"
