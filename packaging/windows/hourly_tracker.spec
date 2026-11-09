from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

project_root = Path(SPECPATH).resolve().parents[1]
src = project_root / "src"
icon = project_root / "packaging" / "windows" / "hourly-tracker.ico"
tray_icon = src / "hourly_tracker" / "assets" / "hourly-tracker.png"

a = Analysis(
    [str(src / "hourly_tracker" / "__main__.py")],
    pathex=[str(src)],
    binaries=[],
    datas=[(str(tray_icon), "hourly_tracker/assets")],
    hiddenimports=collect_submodules("pystray") + collect_submodules("winotify"),
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
    name="HourlyTracker",
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
    icon=str(icon),
)
