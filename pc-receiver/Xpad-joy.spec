# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['client.py'],
    pathex=[],
    binaries=[],
    datas=[('icon.ico', '.'), ('C:/Users/26397/AppData/Local/Programs/Python/Python314/Lib/site-packages/vgamepad/win/vigem', 'vgamepad/win/vigem')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Xpad-joy',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['icon.ico'],
)
