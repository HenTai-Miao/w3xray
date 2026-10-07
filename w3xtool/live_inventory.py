# -*- coding: utf-8 -*-
"""live_inventory v3: 多策略、版本自适应的英雄背包读取器。

策略 (按序尝试, 互为降级):
  D. 句柄系统直读 w3xtool.live_handle_chain — 版本偏移命中时最优先: 句柄表 →
     选中单位 (SelectUnit/ClearSelection 反汇编出的选择链) → 背包 6 槽 → 物品四码。
     全图带物品单位一并枚举; 结构经 1.27.0.52240 (KK) 反汇编验证。
  A. 版本偏移表 OFFSET_REFERENCE — 按 Game.dll 文件版本命中已知锚点 (来自 存档盒子
     Get.dll 的版本表与社区逆向; 命中后优先走外部只读链)。
  B. 结构启发式链 w3xtool.hero_chain — 中文名字串锚点学 def 布局 → 活物品对象 →
     4-6 连续指针=槽位数组 → 英雄验证。版本无关, 经典 1.07~1.31 引擎通用。
  C. 窗口截图 + 图标模板匹配 — PrintWindow 抓屏, 对 全量图标模板库(地图导入 +
     本地 MPQ 原版图标, BLP1/BLP2 自解码) 做 FFT 归一化互相关。UI 可见即通用。

边界: 全程 ReadProcessMemory / PrintWindow 只读; 不注入、不写游戏内存、不碰存档。
"""

# pyright: reportMissingImports=false
import argparse
import ctypes
import ctypes.wintypes as wt
import json
import os
import re
import struct
import sys
from typing import Any, TypedDict

import numpy as np
from PIL import Image

from .live_handle_chain import HANDLE_CHAIN_OFFSETS, match_unit_entries

u32 = ctypes.windll.user32
g32 = ctypes.windll.gdi32
k32 = ctypes.windll.kernel32
adv = ctypes.WinDLL("advapi32", use_last_error=True)

# ---------------------------------------------------------------------------
# 已知版本锚点表 (只读参考; 注入锚点仅作结构定位线索, 本工具不执行注入)
# 来源: 魔兽多功能存档盒子1.8.0.9 Get.dll 版本表 (静态解析)
OFFSET_REFERENCE: dict[str, dict[str, object]] = {
    "1.24.4.6387": {
        "engine": "classic",
        "game_dll_rvas": [0x416598, 0x4164C9, 0x4940D3],
        "source": "Get.dll 注入锚点(未验证外部可用)",
    },
    "1.27.0.52240": {
        "engine": "classic",
        "game_dll_rvas": [0xE09B62, 0xEBCB67],
        "source": "Get.dll 注入锚点; 本地 1.27 Game.dll 12.8MB 越界, 疑为 1.3x 表;"
        " 另: 句柄链偏移已反汇编验证 (live_handle_chain.HANDLE_CHAIN_OFFSETS)",
    },
}


class LUID(ctypes.Structure):
    _fields_ = [("Lo", wt.DWORD), ("Hi", wt.LONG)]


class TOKEN_PRIV(ctypes.Structure):
    _fields_ = [("N", wt.DWORD), ("Luid", LUID), ("A", wt.DWORD)]


class MBI(ctypes.Structure):
    _fields_ = [
        ("Base", ctypes.c_void_p),
        ("AB", ctypes.c_void_p),
        ("AP", wt.DWORD),
        ("_1", wt.DWORD),
        ("Size", ctypes.c_size_t),
        ("State", wt.DWORD),
        ("Prot", wt.DWORD),
        ("Type", wt.DWORD),
        ("_2", wt.DWORD),
    ]


def mem_setup():
    k32.GetCurrentProcess.restype = wt.HANDLE
    k32.OpenProcessToken.argtypes = [wt.HANDLE, wt.DWORD, ctypes.POINTER(wt.HANDLE)]
    k32.OpenProcess.restype = wt.HANDLE
    k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    k32.VirtualQueryEx.argtypes = [
        wt.HANDLE,
        ctypes.c_void_p,
        ctypes.POINTER(MBI),
        ctypes.c_size_t,
    ]
    k32.ReadProcessMemory.argtypes = [
        wt.HANDLE,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    adv.LookupPrivilegeValueW.argtypes = [wt.LPCWSTR, wt.LPCWSTR, ctypes.POINTER(LUID)]
    adv.AdjustTokenPrivileges.argtypes = [
        wt.HANDLE,
        wt.BOOL,
        ctypes.POINTER(TOKEN_PRIV),
        wt.DWORD,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]


def find_war3_pid():
    import subprocess

    try:
        out = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-Process -Name war3,warcraft* -ErrorAction SilentlyContinue | Select-Object -First 1).Id",
            ],
            text=True,
        ).strip()
        return [int(out)] if out else []
    except Exception:
        return []


def open_process(pid):
    h_tok = wt.HANDLE()
    k32.OpenProcessToken(k32.GetCurrentProcess(), 0x28, ctypes.byref(h_tok))
    luid = LUID()
    adv.LookupPrivilegeValueW(None, "SeDebugPrivilege", ctypes.byref(luid))
    adv.AdjustTokenPrivileges(
        h_tok, False, ctypes.byref(TOKEN_PRIV(1, luid, 2)), 0, None, None
    )
    return k32.OpenProcess(0x1FFFFF, False, pid)


def snapshot(h, max_addr=0x7FFF0000):
    regions = []
    addr = 0x10000
    mbi = MBI()
    total = 0
    while addr < max_addr:
        if not k32.VirtualQueryEx(
            h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)
        ):
            break
        rs = mbi.Size or 0x1000
        if (
            mbi.State == 0x1000
            and mbi.Prot in (2, 4, 5, 0x20, 0x40, 0x80)
            and rs <= 32 * 1024 * 1024
        ):
            buf = ctypes.create_string_buffer(rs)
            got = ctypes.c_size_t()
            if (
                k32.ReadProcessMemory(
                    h, ctypes.c_void_p(mbi.Base or 0), buf, rs, ctypes.byref(got)
                )
                and got.value
            ):
                regions.append(((mbi.Base or 0), buf.raw[: got.value]))
                total += got.value
        addr = (mbi.Base or 0) + rs
    return regions, total


def save_snapshot(regions, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    index = []
    blob_path = os.path.join(out_dir, "snap.bin")
    with open(blob_path, "wb") as f:
        for base, data in regions:
            index.append({"base": base, "off": f.tell(), "len": len(data)})
            f.write(data)
    json.dump(index, open(os.path.join(out_dir, "index.json"), "w"), indent=1)
    return blob_path


def load_snapshot(snap_dir):
    index = json.load(open(os.path.join(snap_dir, "index.json")))
    blob = open(os.path.join(snap_dir, "snap.bin"), "rb").read()
    return [(e["base"], blob[e["off"] : e["off"] + e["len"]]) for e in index]


# ---------------------------------------------------------------------------
# 版本探测: 枚举进程模块 -> Game.dll 路径/基址 -> 磁盘文件 VS_FIXEDFILEINFO


def enum_modules(h):
    psapi = ctypes.WinDLL("psapi")
    arr = (ctypes.c_void_p * 1024)()
    needed = wt.DWORD()
    ok = psapi.EnumProcessModulesEx(
        h, arr, ctypes.sizeof(arr), ctypes.byref(needed), 0x03
    )
    if not ok:
        ok = psapi.EnumProcessModules(h, arr, ctypes.sizeof(arr), ctypes.byref(needed))
    if not ok:
        return []
    count = needed.value // ctypes.sizeof(ctypes.c_void_p)
    mods = []
    buf = ctypes.create_unicode_buffer(2048)
    for i in range(min(count, 1024)):
        base = arr[i]
        if not base:
            continue
        if psapi.GetModuleFileNameExW(h, ctypes.c_void_p(base), buf, 2048):
            mods.append((buf.value, base))
    return mods


def read_file_version(path):
    """VS_FIXEDFILEINFO -> 'a.b.c.d'; 失败返回 None。"""
    try:
        d = open(path, "rb").read(64 * 1024 * 1024)
    except OSError:
        return None
    pos = d.find(b"\xbd\x04\xef\xfe")
    if pos < 0 or pos + 24 > len(d):
        m = re.search(rb"(\d+\.\d+\.\d+\.\d+)", d)
        return m.group(1).decode() if m else None
    ms, ls = struct.unpack_from("<II", d, pos + 8)

    def hi(v):
        return (v >> 16) & 0xFFFF

    def lo(v):
        return v & 0xFFFF

    return f"{hi(ms)}.{lo(ms)}.{hi(ls)}.{lo(ls)}"


def pe_machine(path):
    try:
        d = open(path, "rb").read(4096)
        e = struct.unpack_from("<I", d, 0x3C)[0]
        return struct.unpack_from("<H", d, e + 4)[0]
    except OSError, struct.error:
        return 0


def detect_version(h):
    info: dict[str, object] = {
        "engine": "unknown",
        "version": None,
        "arch": "x86",
        "game_dll": None,
    }
    for path, base in enum_modules(h):
        name = os.path.basename(path).lower()
        if name == "game.dll":
            ver = read_file_version(path)
            info["version"] = ver
            info["arch"] = "x64" if pe_machine(path) == 0x8664 else "x86"
            info["engine"] = "reforged" if info["arch"] == "x64" else "classic"
            info["game_dll"] = {"base": base, "path": path}
            break
    if isinstance(info["version"], str) and info["version"] in OFFSET_REFERENCE:
        info["known_offsets"] = OFFSET_REFERENCE[info["version"]]
    return info


# ---------------------------------------------------------------------------
# 名字/图标数据


def clean(s):
    o, i = [], 0
    while i < len(s):
        if s.startswith("|c", i) and len(s) - i >= 10:
            i += 10
        elif s.startswith("|r", i):
            i += 2
        else:
            o.append(s[i])
            i += 1
    return "".join(o)


def load_names(pack_dir, kind="物品"):
    nm = {}
    p = os.path.join(pack_dir, "对象ID", f"{kind}.tsv")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8").read().splitlines()[1:]:
            c = line.split("\t")
            if len(c) > 4 and len(c[1]) == 4:
                nm[c[1].encode()] = clean(c[4])
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, repo)
    try:
        from w3xtool.base_names import BASE_NAMES_EN, BASE_CATEGORIES

        for code, cat in BASE_CATEGORIES.items():
            if cat and "item" in str(cat).lower():
                n2 = BASE_NAMES_EN.get(code, "")
                if n2 and len(code) == 4:
                    nm.setdefault(code.encode(), n2)
    except Exception:
        pass
    return nm


def _icon_paths_from_pack(pack_dir):
    paths = {}
    p2 = os.path.join(pack_dir, "对象字段.tsv")
    for line in open(p2, encoding="utf-8", errors="replace"):
        c = line.rstrip("\n").split("\t")
        if (
            len(c) >= 6
            and c[0] == "物品"
            and c[5].lower().endswith(".blp")
            and "commandbuttons" in c[5].lower()
        ):
            paths[c[1]] = c[5].replace("\\", "/")
    return paths


def _mpq_roots():
    base = r"C:\Program Files (x86)\Warcraft III\Warcraft III Frozen Throne"
    return [
        os.path.join(base, n)
        for n in ("war3.mpq", "War3x.mpq", "War3xLocal.mpq", "War3Patch.mpq")
    ]


def build_templates(pack_dir, cache_dir=None, verbose=False):
    """合并 地图导入图标 + 本地 MPQ 提取的原版图标 -> {物品ID: 文件路径}"""
    if cache_dir is None:
        cache_dir = os.path.join(os.environ.get("TEMP", "."), "w3xray-icon-cache")
    names = load_names(pack_dir)
    paths = _icon_paths_from_pack(pack_dir)
    # 包内文件索引 (全 replaceabletextures 树, 小写文件名)
    cbroot = os.path.join(pack_dir, "资源", "素材文件", "replaceabletextures")
    index = {}
    for root, _dirs, files in os.walk(cbroot):
        for f in files:
            index[f.lower()] = os.path.join(root, f)
    templates = {}
    missing = []
    for iid, p in paths.items():
        b = os.path.basename(p).lower()
        if b in index:
            templates[iid] = index[b]
        else:
            missing.append(p)
    if verbose:
        print(f"包内图标 {len(templates)}/{len(paths)}, 缺 {len(set(missing))}")
    if missing:
        os.makedirs(cache_dir, exist_ok=True)
        try:
            from w3xtool.archive_source import PathArchiveSource

            archives = []
            for m in _mpq_roots():
                if os.path.exists(m):
                    try:
                        archives.append(PathArchiveSource(m).open())
                    except Exception:
                        pass
            for p in sorted(set(missing)):
                fn = p.replace("/", "_").lower()
                dst = os.path.join(cache_dir, fn)
                if os.path.exists(dst):
                    templates.setdefault(_iid_for_path(paths, p), dst)
                    continue
                for arch in archives:
                    for cand in (p, p.replace("/", "\\"), p.lower().replace("/", "\\")):
                        try:
                            if arch.has_file(cand):
                                open(dst, "wb").write(arch.read_file(cand))
                                templates.setdefault(_iid_for_path(paths, p), dst)
                                break
                        except Exception:
                            continue
                    else:
                        continue
                    break
        except Exception as ex:
            if verbose:
                print("MPQ 提取跳过:", ex)
    if verbose:
        print(f"模板总数 {len(templates)}")
    return templates, names


def _iid_for_path(paths, p):
    for iid, q in paths.items():
        if q == p:
            return iid
    return "unknown"


# ---------------------------------------------------------------------------
# 图标匹配 (策略 C)


def decode_blp(data):
    import io

    if data[:4] == b"BLP1":
        typ = struct.unpack_from("<I", data, 4)[0]
        alpha_depth = struct.unpack_from("<I", data, 8)[0]
        w, h = struct.unpack_from("<II", data, 12)
        offs = struct.unpack_from("<16I", data, 0x1C)
        sizes = struct.unpack_from("<16I", data, 0x5C)
        pal_off = 0x9C
    elif data[:4] == b"BLP2":
        typ = struct.unpack_from("<I", data, 4)[0]
        alpha_depth = data[8]
        w, h = struct.unpack_from("<II", data, 12)
        offs = struct.unpack_from("<16I", data, 0x14)
        sizes = struct.unpack_from("<16I", data, 0x54)
        pal_off = 0x94
    else:
        return None
    if w == 0 or h == 0 or not offs or offs[0] >= len(data):
        return None
    if typ == 0:
        seg = data[offs[0] : offs[0] + sizes[0]]
        try:
            return Image.open(io.BytesIO(seg)).convert("RGBA")
        except Exception:
            return None
    pal = data[pal_off : pal_off + 1024]
    seg = data[offs[0] : offs[0] + sizes[0]]
    if len(pal) < 1024 or len(seg) < w * h:
        return None
    idx = np.frombuffer(seg[: w * h], dtype=np.uint8)
    rgb = np.frombuffer(pal, dtype=np.uint8).reshape(256, 4)
    px = rgb[idx]
    if alpha_depth >= 8 and len(seg) >= w * h * 2:
        a = np.frombuffer(seg[w * h : w * h * 2], dtype=np.uint8).reshape(-1, 1).copy()
    else:
        a = px[:, 3:4].copy()
    if a.max() == 0:
        a[:] = 255
    img = np.concatenate([px[:, 2:3], px[:, 1:2], px[:, 0:1], a], axis=1).reshape(
        h, w, 4
    )
    return Image.fromarray(img.astype(np.uint8), "RGBA")


_ICON_CACHE = {}


def get_icon_array(path, size):
    key = (path, size)
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]
    try:
        img = decode_blp(open(path, "rb").read())
    except OSError:
        img = None
    if img is None:
        _ICON_CACHE[key] = None
        return None
    img = img.resize((size, size), Image.Resampling.LANCZOS)
    arr = np.asarray(img.convert("L"), dtype=np.float64)
    _ICON_CACHE[key] = arr
    return arr


def capture_window(title="Warcraft III"):
    hwnd = u32.FindWindowW(None, title)
    if not hwnd:
        raise RuntimeError(f"未找到窗口 {title}")
    rc = wt.RECT()
    u32.GetClientRect(hwnd, ctypes.byref(rc))
    w, h = rc.right - rc.left, rc.bottom - rc.top
    if w <= 0 or h <= 0:
        raise RuntimeError("窗口客户区为空")
    hdc = u32.GetDC(hwnd)
    md = g32.CreateCompatibleDC(hdc)
    bmp = g32.CreateCompatibleBitmap(hdc, w, h)
    old = g32.SelectObject(md, bmp)
    u32.PrintWindow(hwnd, md, 2)
    bi = struct.pack("<IiiHHIIiiII", 40, w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    g32.GetDIBits(md, bmp, 0, h, buf, bi, 0)
    g32.SelectObject(md, old)
    g32.DeleteObject(bmp)
    g32.DeleteDC(md)
    u32.ReleaseDC(hwnd, hdc)
    arr = np.frombuffer(buf.raw, dtype=np.uint8).reshape(h, w, 4)
    return Image.fromarray(arr[:, :, :3].copy(), "RGB"), (w, h)


def ncc_best(region, tmpl):
    H, W = region.shape
    h, w = tmpl.shape
    if h > H or w > W:
        return -1.0, (0, 0)
    fh, fw = 1 << (H - 1).bit_length(), 1 << (W - 1).bit_length()
    A = np.fft.rfft2(region, (fh, fw))
    B = np.fft.rfft2(tmpl[::-1, ::-1], (fh, fw))
    cross = np.fft.irfft2(A * B, (fh, fw))
    ones = np.ones((h, w))
    ones_fft = np.fft.rfft2(ones[::-1, ::-1], (fh, fw))
    S1 = np.fft.irfft2(A * ones_fft, (fh, fw))
    S2 = np.fft.irfft2(np.fft.rfft2(region**2, (fh, fw)) * ones_fft, (fh, fw))
    n = float(h * w)
    tmean = tmpl.mean()
    tstd = tmpl.std()
    if tstd < 1e-6:
        return -1.0, (0, 0)
    varw = np.maximum(S2 - S1 * S1 / n, 1e-9)
    score = (cross - S1 * tmean) / (np.sqrt(varw) * tstd * n)
    sub = score[: H - h + 1, : W - w + 1]
    idx = int(np.argmax(sub))
    y, x = divmod(idx, sub.shape[1])
    return float(sub[y, x]), (int(x), int(y))


def match_image_full(
    img,
    templates,
    names,
    min_score=0.45,
    downscale=2,
    sizes=(13, 16, 19, 22, 26, 32),
    topk=12,
):
    """整图半分辨率匹配 (UI 位置未知的通用模式)。"""
    W, H = img.size
    small = img.resize(
        (W // downscale, H // downscale), Image.Resampling.LANCZOS
    ).convert("L")
    region = np.asarray(small, dtype=np.float64)
    Hr, Wr = region.shape
    fh = 1 << (Hr - 1).bit_length()
    fw = 1 << (Wr - 1).bit_length()
    A0 = np.fft.rfft2(region, (fh, fw))
    A2 = np.fft.rfft2(region**2, (fh, fw))
    cache = {}

    def ncc_fast(t):
        h, w = t.shape
        if h > Hr or w > Wr:
            return -1.0, (0, 0)
        if (h, w) not in cache:
            o = np.ones((h, w))
            ones_fft0 = np.fft.rfft2(o[::-1, ::-1], (fh, fw))
            s1 = np.fft.irfft2(A0 * ones_fft0, (fh, fw))
            s2 = np.fft.irfft2(A2 * ones_fft0, (fh, fw))
            n0 = float(h * w)
            varw0 = np.maximum(s2 - s1 * s1 / n0, 1e-9)
            cache[(h, w)] = (ones_fft0, s1, varw0)
        ones_fft, S1, varw = cache[(h, w)]
        B = np.fft.rfft2(t[::-1, ::-1], (fh, fw))
        cross = np.fft.irfft2(A0 * B, (fh, fw))
        n = float(h * w)
        tmean = t.mean()
        tstd = t.std()
        if tstd < 1e-6:
            return -1.0, (0, 0)
        score = (cross - S1 * tmean) / (np.sqrt(varw) * tstd * n)
        sub = score[: Hr - h + 1, : Wr - w + 1]
        idx = int(np.argmax(sub))
        y, x = divmod(idx, sub.shape[1])
        return float(sub[y, x]), (int(x), int(y))

    cands = []
    for iid, path in templates.items():
        best: tuple[float, tuple[int, int], int] = (-1.0, (0, 0), 0)
        for s in sizes:
            t = get_icon_array(path, s)
            if t is None:
                continue
            sc, pos = ncc_fast(t)
            if sc > best[0]:
                best = (sc, pos, s)
        if best[0] > min_score:
            cands.append(
                (best[0], iid, names.get(iid, iid), best[1], best[2] * downscale)
            )
    cands.sort(reverse=True)
    picked = []
    for sc, iid, name, pos, s in cands:
        if any(
            abs(pos[0] - p[2][0]) < 20 and abs(pos[1] - p[2][1]) < 20 for p in picked
        ):
            continue
        picked.append((sc, iid, name, (pos[0] * downscale, pos[1] * downscale), s))
        if len(picked) >= topk:
            break
    return picked


def match_inventory(img, templates, names, max_slots=6, min_score=0.5):
    """右下角经典控制台区域匹配 (标准 UI)。"""
    W, H = img.size
    crop = img.crop((int(W * 0.62), int(H * 0.60), W, H)).convert("L")
    region = np.asarray(crop, dtype=np.float64)
    cand = []
    for iid, path in templates.items():
        best: tuple[float, tuple[int, int], int] = (-1.0, (0, 0), 0)
        for s in (22, 26, 30, 34, 38, 44):
            t = get_icon_array(path, s)
            if t is None:
                continue
            sc, pos = ncc_best(region, t)
            if sc > best[0]:
                best = (sc, pos, s)
        if best[0] > min_score:
            cand.append((best[0], iid, names.get(iid, iid), best[1], best[2]))
    cand.sort(reverse=True)
    picked = []
    for sc, iid, name, pos, s in cand:
        if any(
            abs(pos[0] - p[3][0]) < 18 and abs(pos[1] - p[3][1]) < 18 for p in picked
        ):
            continue
        picked.append((sc, iid, name, pos, s))
        if len(picked) >= max_slots:
            break
    picked.sort(key=lambda p: (p[3][1] // 30, p[3][0]))
    return picked


# ---------------------------------------------------------------------------
# 总编排


class _LiveReport(TypedDict):
    strategy_used: "str | None"
    version: "dict[str, object] | None"
    slots: list[Any]
    notes: list[str]
    selected_unit: Any
    units: list[Any]
    unit_matches: list[Any]
    owner_counts: "dict[int, int] | None"
    owned_units: "list[dict[str, object]] | None"
    resources: "list[dict[str, object]] | None"


def _parse_resources_arg(parts):
    """--resources auto 或 --resources 金币 木材 -> ("auto") / (金, 木) / None。"""
    if not parts:
        return None
    if parts == ["auto"]:
        return "auto"
    if len(parts) != 2:
        return None
    try:
        return (float(parts[0]), float(parts[1]))
    except ValueError:
        return None


def read_live(
    pack_dir,
    strategy="auto",
    save_snapshot_dir=None,
    load_snapshot_dir=None,
    verbose=True,
    unit_query=None,
    players=False,
    resources=None,
):
    """resources: (金币, 木材) 元组为报数校准; "auto" 为自动差分 (免报数)。"""
    report: _LiveReport = {
        "strategy_used": None,
        "version": None,
        "slots": [],
        "notes": [],
        "selected_unit": None,
        "units": [],
        "unit_matches": [],
        "owner_counts": None,
        "owned_units": None,
        "resources": None,
    }
    ver: dict[str, object] | None = None
    h = 0
    max_addr = 0x7FFF0000
    if load_snapshot_dir:
        regions, total = load_snapshot(load_snapshot_dir), 0
        total = sum(len(d) for _, d in regions)
        if verbose:
            print(f"离线快照 {len(regions)} 区 {total // 1048576}MB")
    else:
        mem_setup()
        pids = find_war3_pid()
        if not pids:
            report["notes"].append("war3 未运行")
            return report
        h = open_process(pids[0])
        if not h:
            report["notes"].append("OpenProcess 失败 (需管理员)")
            return report
        ver = detect_version(h)
        report["version"] = ver
        if verbose:
            gd = ver.get("game_dll")
            gd_base = gd.get("base", 0) if isinstance(gd, dict) else 0
            print(
                f"检测: {ver['engine']} {ver['version']} {ver['arch']} Game.dll@0x{gd_base:X}"
                + (" [已知偏移表]" if ver.get("known_offsets") else "")
            )
        max_addr = 0x7FFFFFFEFFFF if ver["arch"] == "x64" else 0x7FFF0000
        if resources is not None and not players and not unit_query:
            import ctypes as _ct
            import struct as _st

            k = k32

            def _ru32(a):
                buf = _ct.create_string_buffer(4)
                got = _ct.c_size_t()
                if (
                    k.ReadProcessMemory(h, _ct.c_void_p(a), buf, 4, _ct.byref(got))
                    and got.value == 4
                ):
                    return _st.unpack("<I", buf.raw)[0]
                return None

            import importlib as _il

            _hc0 = _il.import_module("w3xtool.live_handle_chain")
            gd0 = ver.get("game_dll")
            dll0 = gd0.get("base", 0) if isinstance(gd0, dict) else 0
            chain_rows = _hc0.read_player_resources_chain(
                _ru32, dll0, str(ver.get("version") or "")
            )
            if chain_rows:
                report["resources"] = chain_rows
                if verbose:
                    print("权威链直读全队资源完成 (免扫描免报数)")
                return report
        regions, total = snapshot(h, max_addr)
        if verbose:
            print(f"快照 {len(regions)} 区 {total // 1048576}MB")
        if save_snapshot_dir:
            p = save_snapshot(regions, save_snapshot_dir)
            if verbose:
                print("快照已存:", p)

    def try_handle():
        """策略 D: 句柄系统直读 (需要运行中的游戏 + 已知版本偏移)。"""
        if load_snapshot_dir or not ver:
            report["notes"].append("handle 策略需要运行中的游戏 (版本探测)")
            return None
        try:
            import importlib

            hc = importlib.import_module("w3xtool.live_handle_chain")
            gd = ver.get("game_dll")
            dll_base = gd.get("base", 0) if isinstance(gd, dict) else 0
            if not dll_base:
                report["notes"].append("未取到 Game.dll 基址")
                return None
            reader = hc.MemoryReader(regions)
            offsets = HANDLE_CHAIN_OFFSETS.get(str(ver.get("version") or ""))
            if offsets is None:
                offsets = hc.derive_offsets(reader, dll_base, dll_base + 0x2000000)
                if offsets is not None:
                    report["notes"].append(
                        f"版本 {ver.get('version')} 未收录, 偏移按结构特征自动推导"
                    )
            if offsets is None:
                report["notes"].append(f"版本 {ver.get('version')} 暂无句柄链偏移")
                return None
            system = hc.HandleSystem(reader, dll_base, offsets)
            if not system.valid:
                report["notes"].append("句柄管理器不可读")
                return None
            item_names = load_names(pack_dir)
            unit_names = load_names(pack_dir, "单位")

            def describe(inv):
                return {
                    "unit": unit_names.get(inv.code.encode("latin-1"), "?"),
                    "code": inv.code,
                    "addr": inv.unit_addr,
                    "items": [
                        {
                            "slot": i.slot,
                            "name": item_names.get(i.code.encode("latin-1"), "?"),
                            "code": i.code,
                        }
                        for i in inv.items
                        if hc.is_fourcc(i.code)
                    ],
                }

            units = hc.walk_item_units(reader, system, offsets)
            report["units"] = [describe(u) for u in units]
            if players:
                owned = hc.walk_owned_units(reader, system, offsets)
                counts, listed = hc.summarize_owners(owned)
                report["owner_counts"] = counts
                report["owned_units"] = [
                    {
                        "owner": u.owner,
                        "unit": unit_names.get(u.code.encode("latin-1"), "?"),
                        "code": u.code,
                        "x": round(u.x, 1),
                        "y": round(u.y, 1),
                    }
                    for u in listed
                ]
            if resources is not None:
                if resources == "auto":
                    import time as _time

                    readers = [reader]
                    for _ in range(2):
                        _time.sleep(3)
                        readers.append(hc.reader_from_snapshot(snapshot(h, max_addr)))
                    found = hc.find_auto_resource_rows(readers)
                else:
                    found = hc.find_resource_layout(reader, resources[0], resources[1])
                report["resources"] = [
                    {
                        "addr": hex(r.addr),
                        "gold": round(r.gold),
                        "lumber": round(r.lumber),
                        "food": r.food,
                    }
                    for r in found
                ]
            if unit_query:
                pool = list(report["units"])
                sel = hc.selected_unit(reader, system, offsets, dll_base)
                if sel is not None:
                    sel_desc = describe(sel)
                    report["selected_unit"] = sel_desc
                    pool.append(sel_desc)
                dedup: dict[int, Any] = {}
                for entry in pool:
                    dedup.setdefault(int(entry["addr"]), entry)
                matches = match_unit_entries(list(dedup.values()), unit_query)
                report["unit_matches"] = matches
                if matches:
                    report["slots"] = matches[0]["items"]
                    return report["slots"]
                names = "、".join(str(u["unit"]) for u in report["units"]) or "(无)"
                report["notes"].append(
                    f"未找到单位 {unit_query}; 当前带物品单位: {names}"
                )
                return None
            sel = hc.selected_unit(reader, system, offsets, dll_base)
            if sel is not None:
                report["selected_unit"] = describe(sel)
                report["slots"] = report["selected_unit"]["items"]
                return report["slots"]
            return None
        except Exception as ex:
            report["notes"].append(f"句柄链异常: {ex}")
            return None

    def try_chain():
        try:
            import importlib

            hero_chain = importlib.import_module("w3xtool.hero_chain")
            names = load_names(pack_dir)
            unit_names = load_names(pack_dir, "单位")
            res = hero_chain.read_inventory(
                regions, names, unit_names=unit_names, verbose=verbose
            )
            return res
        except Exception as ex:
            report["notes"].append(f"结构链异常: {ex}")
            return []

    def try_icons():
        try:
            templates, names = build_templates(pack_dir, verbose=verbose)
            if not templates:
                report["notes"].append("无图标模板")
                return []
            img, wh = capture_window()
            if verbose:
                print(f"窗口 {wh[0]}x{wh[1]}")
            picked = match_inventory(img, templates, names)
            if not picked:
                picked = match_image_full(img, templates, names)
            return [
                {
                    "name": n,
                    "item": i,
                    "score": round(s, 3),
                    "pos": list(pos),
                    "size": sz,
                }
                for s, i, n, pos, sz in picked
            ]
        except Exception as ex:
            report["notes"].append(f"图标匹配异常: {ex}")
            return []

    if strategy in ("auto", "handle"):
        slots = try_handle()
        if slots:
            report["strategy_used"] = "handle"
            return report
    if strategy in ("auto", "chain"):
        slots = try_chain()
        if slots:
            report["strategy_used"] = "chain"
            report["slots"] = slots
            return report
    if strategy in ("auto", "icons"):
        slots = try_icons()
        if slots:
            report["strategy_used"] = "icons"
            report["slots"] = slots
            return report
    report["notes"].append("所有策略均未产出 (背包可能为空/结构未识别/UI 不可见)")
    return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=(__doc__ or __name__).splitlines()[0])
    ap.add_argument("--pack", required=True, help="导出的知识包目录")
    ap.add_argument(
        "--strategy", default="auto", choices=("auto", "handle", "chain", "icons")
    )
    ap.add_argument("--test-image", help="用截图代替窗口抓取 (仅 icons 策略)")
    ap.add_argument("--save-snapshot", help="保存内存快照目录 (离线分析用)")
    ap.add_argument("--load-snapshot", help="载入快照目录代替实时读取")
    ap.add_argument("--unit", help="按单位名或四码过滤输出 (如 寒冰游侠 / H004 / 宝宝)")
    ap.add_argument(
        "--players",
        action="store_true",
        help="列出每个真人玩家号下的单位 (所有者+坐标, 地图物件自动归并)",
    )
    ap.add_argument(
        "--resources",
        nargs="+",
        metavar=("金币|auto", "木材"),
        help="读取全部玩家资源: 报数校准 (--resources 169 808) 或自动差分 (--resources auto)",
    )
    args = ap.parse_args(argv)
    if args.test_image:
        templates, names = build_templates(args.pack, verbose=True)
        img = Image.open(args.test_image).convert("RGB")
        picked = match_inventory(img, templates, names) or match_image_full(
            img, templates, names
        )
        out = [
            {"name": n, "item": i, "score": round(s, 3), "pos": list(pos), "size": sz}
            for s, i, n, pos, sz in picked
        ]
        print(json.dumps({"slots": out}, ensure_ascii=False, indent=1))
        return 0
    rep = read_live(
        args.pack,
        args.strategy,
        args.save_snapshot,
        args.load_snapshot,
        unit_query=args.unit,
        players=args.players or bool(args.resources),
        resources=_parse_resources_arg(args.resources),
    )
    counts = rep.get("owner_counts") or {}
    if counts:
        print("== 所有者分布 ==")
        print("  " + "  ".join(f"P{o}:{n}" for o, n in sorted(counts.items())))
    res = rep.get("resources")
    if res is not None:
        print(f"== 玩家资源 (同布局结构 {len(res)} 个: 你+队友+缓存副本) ==")
        for r2 in res:
            food = f" 人口~{r2['food']}" if r2.get("food") is not None else ""
            print(f"  {r2['addr']}: 金{r2['gold']} 木{r2['lumber']}{food}")
        if not res:
            print("  未定位到资源结构; 确认金币/木材数值没变后重试")
        listed = rep.get("owned_units") or []
        print(f"== 玩家单位 (数量少的玩家号, 共{len(listed)}个) ==")
        for u in listed:
            print(
                f"  P{u['owner']} {u['unit']} [{u['code']}] @ ({u['x']:.0f}, {u['y']:.0f})"
            )
    if rep.get("unit_matches"):
        for u in rep["unit_matches"]:
            print(f"匹配单位: {u['unit']} [{u['code']}]")
            for it in u["items"]:
                print(f"  槽{it['slot']}: {it['name']} [{it['code']}]")
    elif rep.get("strategy_used") == "handle" and rep.get("selected_unit"):
        sel = rep["selected_unit"]
        print(f"当前选中: {sel['unit']} [{sel['code']}]")
        for it in sel["items"]:
            print(f"  槽{it['slot']}: {it['name']} [{it['code']}]")
        others = [u for u in rep.get("units", []) if u != sel]
        if others:
            print("其余带物品单位:")
            for u in others:
                names_txt = "、".join(f"{i['name']}" for i in u["items"])
                print(f"  {u['unit']} [{u['code']}]: {names_txt}")
    print(json.dumps(rep, ensure_ascii=False, indent=1, default=str))
    if rep["slots"]:
        return 0
    if args.players and rep.get("owner_counts") is not None:
        return 0
    if args.resources and rep.get("resources") is not None:
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
