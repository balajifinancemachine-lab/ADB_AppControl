# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller build definition for ADB AppControl.

Build with:  pyinstaller --noconfirm --clean appcontrol.spec
Output:      dist/ADB_AppControl/ADB_AppControl.exe

The app is shipped as a one-directory build on purpose: the tools/ payload
(platform-tools, scrcpy, llama runtime, optional GGUF model) and the data/
write root live next to the executable, not inside a self-extracting archive.
build_release.bat copies tools/ into dist/ADB_AppControl/ for you.
"""
from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files("customtkinter")

a = Analysis(
    ["appcontrol.pyw"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=["PIL._tkinter_finder"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "matplotlib", "numpy"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ADB_AppControl",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ADB_AppControl",
)
