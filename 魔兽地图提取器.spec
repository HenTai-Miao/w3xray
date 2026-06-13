# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = []
binaries = []
# w3xtool 多个子模块在 api.py/fields.py 里是“函数内懒加载”(如 _add_preplaced 里 from .doo import)，
# 显式列入 hiddenimports 确保 PyInstaller 一定收进去(含大数据模块 field_meta/base_*/westrings)。
hiddenimports = [
    'w3xtool.doo', 'w3xtool.imp', 'w3xtool.w3i', 'w3xtool.wct',
    'w3xtool.field_meta', 'w3xtool.fields', 'w3xtool.slk', 'w3xtool.textobj',
    'w3xtool.script_scan', 'w3xtool.wts', 'w3xtool.w3obj', 'w3xtool.blp',
    'w3xtool.icons', 'w3xtool.huffman', 'w3xtool.explode', 'w3xtool.mpq',
    'w3xtool.base_names', 'w3xtool.base_objects', 'w3xtool.westrings',
    'w3xtool.single_instance',
]
tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


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
