# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules
from w3xtool.casclib_dist import validate_casclib_dist_assets

datas = []
binaries = []
# w3xtool 大量模块通过函数内懒加载连接 GUI/CLI 分析能力。自动收集整个包，
# 防止 exe 在点击某个报告或打开特定地图格式时才暴露缺模块。
hiddenimports = collect_submodules('w3xtool')
tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]
hiddenimports = sorted(set(hiddenimports + tmp_ret[2]))

if sys.platform == 'win32':
    spec_root = Path(SPECPATH)
    validate_casclib_dist_assets(spec_root, system='Windows')
    binaries.append((str(spec_root / 'third_party/CascLib/bin/win-x64/CascLib.dll'), '.'))
    datas.append((str(spec_root / 'third_party/CascLib/LICENSE'), 'licenses/CascLib'))


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 运行时用不到的标准库，裁掉以缩小体积（保留 tkinter/PIL/customtkinter）
        'unittest', 'test', 'pydoc', 'doctest', 'pdb',
        'lib2to3', 'distutils', 'setuptools', 'pip', 'xmlrpc',
        'build_field_labels',     # 离线生成脚本，运行时用不到
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,     # onedir：依赖交给 COLLECT，启动几乎无解压开销
    name='魔兽地图提取器',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                 # 关闭 UPX：加快启动、减少杀软误报
    upx_exclude=[],
    runtime_tmpdir=None,
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
    name='魔兽地图提取器',
)
