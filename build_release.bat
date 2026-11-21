@echo off
REM Builds a distributable Windows folder in dist\ADB_AppControl\
setlocal
cd /d "%~dp0"

python -m pip install --upgrade pyinstaller || goto :error
python -m PyInstaller --noconfirm --clean appcontrol.spec || goto :error

echo.
echo Build complete: dist\ADB_AppControl\ADB_AppControl.exe
if exist tools\ (
    xcopy /E /I /Y /Q tools "dist\ADB_AppControl\tools" >nul
    echo Copied tools\ (adb, scrcpy, llama, models) next to the executable.
) else (
    echo Note: no tools\ folder found - the app downloads platform-tools on first run.
)
exit /b 0

:error
echo.
echo Build failed. Review the output above.
exit /b 1
