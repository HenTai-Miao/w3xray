# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('prompts', 'prompts')]   # AI 提示词模板，运行时 AI 质检要读
binaries = []
hiddenimports = []
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
