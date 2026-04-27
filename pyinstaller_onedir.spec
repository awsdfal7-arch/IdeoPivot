# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files


project_root = Path(SPECPATH).resolve()
logo_path = project_root / "logo.png"
icon_path = project_root / "logo.ico"

# 仅打包运行必需资源；docs/ 与使用手册不进入发布产物。
datas = [
    (str(project_root / "reference"), "reference"),
]
if logo_path.exists():
    datas.append((str(logo_path), "."))

# jieba 和 python-docx 都依赖包内数据文件，显式收集更稳妥。
datas += collect_data_files("jieba")
datas += collect_data_files("docx")


a = Analysis(
    ["main.py"],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
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
    [],
    exclude_binaries=True,
    name="思政智题云枢",
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
    icon=str(icon_path) if icon_path.exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="思政智题云枢",
)
