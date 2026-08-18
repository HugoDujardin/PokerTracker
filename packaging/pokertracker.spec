# -*- mode: python ; coding: utf-8 -*-
"""Recette PyInstaller: produit dist/PokerTracker/PokerTracker.exe (Windows 11)."""
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

a = Analysis(
    ["../run.py"],
    pathex=[".."],
    binaries=[],
    datas=[],
    hiddenimports=collect_submodules("pokertracker"),
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.Qt3DCore", "PySide6.QtQuick3D"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PokerTracker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,            # application fenetree: pas de console Windows
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="PokerTracker",
)
