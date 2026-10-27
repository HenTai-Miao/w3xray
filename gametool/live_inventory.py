# -*- coding: utf-8 -*-
"""live_inventory v3: 多策略、版本自适应的英雄背包读取器。

策略 (按序尝试, 互为降级):
  D. 句柄系统直读 gametool.live_handle_chain — 版本偏移命中时最优先: 句柄表 →
     选中单位 (SelectUnit/ClearSelection 反汇编出的选择链) → 背包 6 槽 → 物品四码。
     全图带物品单位一并枚举; 结构经 1.27.0.52240 (KK) 反汇编验证。
  A. 版本偏移表 OFFSET_REFERENCE — 按 Game.dll 文件版本命中已知锚点 (来自 存档盒子
     Get.dll 的版本表与社区逆向; 命中后优先走外部只读链)。
  B. 结构启发式链 gametool.hero_chain — 中文名字串锚点学 def 布局 → 活物品对象 →
     4-6 连续指针=槽位数组 → 英雄验证。版本无关, 经典 1.07~1.31 引擎通用。
  C. 窗口截图 + 图标模板匹配 — PrintWindow 抓屏, 对 全量图标模板库(地图导入 +
     本地 MPQ 原版图标, BLP1/BLP2 自解码) 做 FFT 归一化互相关。UI 可见即通用。

边界: 全程 ReadProcessMemory / PrintWindow 只读; 不注入、不写游戏内存、不碰存档。
"""

# pyright: reportMissingImports=false
import argparse
from contextlib import ExitStack
import ctypes
import ctypes.wintypes as wt
import json
import math
import os
from pathlib import Path
import re
import struct
import sys
import time
from typing import Any, TypedDict

import numpy as np
from PIL import Image

from .live_handle_chain import match_unit_entries
from .static_numbers import format_number

u32 = ctypes.windll.user32
g32 = ctypes.windll.gdi32
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
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
    adv.OpenProcessToken.argtypes = [wt.HANDLE, wt.DWORD, ctypes.POINTER(wt.HANDLE)]
    k32.OpenProcess.restype = wt.HANDLE
    k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    k32.CloseHandle.argtypes = [wt.HANDLE]
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


def find_war3_pids():
    """全部 war3 进程 PID (多实例不猜 — 学自 trainer find_war3:
    Multiple clients -> select an explicit PID)。"""
    import subprocess

    try:
        out = subprocess.check_output(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-Process -Name war3,warcraft* -ErrorAction SilentlyContinue).Id",
            ],
            text=True,
        ).strip()
        return sorted({int(x) for x in out.split() if x.strip().isdigit()})
    except Exception:
        return []


def open_process(pid):
    h_tok = wt.HANDLE()
    if adv.OpenProcessToken(k32.GetCurrentProcess(), 0x28, ctypes.byref(h_tok)):
        try:
            luid = LUID()
            if adv.LookupPrivilegeValueW(None, "SeDebugPrivilege", ctypes.byref(luid)):
                adv.AdjustTokenPrivileges(
                    h_tok, False, ctypes.byref(TOKEN_PRIV(1, luid, 2)), 0, None, None
                )
        finally:
            k32.CloseHandle(h_tok)
    # PROCESS_QUERY_INFORMATION | PROCESS_VM_READ: no write, injection,
    # termination or suspension rights are needed for a read-only probe.
    return k32.OpenProcess(0x0410, False, pid)


# TokenIntegrityLevel RID → 人话 (学自 trainer 的方向性权限预检):
# 只有「工具级别低于游戏」才是真问题 (写上提会被拒); 管理员工具读
# 普通游戏完全正常, 不报。RID 表按 trainer 实测: medium_plus=0x2100。
_INTEGRITY_NAMES = {
    0x1000: "低",
    0x2000: "中",
    0x2100: "中高",
    0x3000: "高",
    0x4000: "系统",
}


def log_live_exception(stage, ex):
    """兜底异常带栈落盘 (fail-open) 并返回提示后缀。

    学自 trainer format_error 三件套 (reason/recovery/diagnostic_log
    _path) 与 describe_error 纪律「绝不把通用 WinError 当根因」——
    str(ex) 常常只是表象, 栈与阶段名才是排查证据。写失败不抛出。
    """
    import traceback

    try:
        from .cache_root import gamexray_cache_root

        root = gamexray_cache_root() / "live"
        root.mkdir(parents=True, exist_ok=True)
        p = root / "errors-v1.log"
        with p.open("a", encoding="utf-8") as fh:
            fh.write(
                "[%s] stage=%s pid=%s\n%s\n"
                % (
                    time.strftime("%Y-%m-%dT%H:%M:%S"),
                    stage,
                    report_pid() or "?",
                    traceback.format_exc(),
                )
            )
        return f" (诊断日志: {p})"
    except Exception:
        return ""


def report_pid():
    """当前探测目标 PID (异常日志用; 无活跃探测返回 None)。"""
    return _active_pid.get("pid")


_active_pid: dict[str, "int | None"] = {"pid": None}


def _process_identity(handle):
    """进程 exe 绝对路径 (身份); 拿不到返回 None (fail-open)。"""
    try:
        buf = ctypes.create_unicode_buffer(0x400)
        if k32.K32GetModuleFileNameExW(handle, None, buf, 0x400):
            return buf.value
    except Exception:
        pass  # 376: psapi 缺失/权限不足 — 返回 None 由调用方 opened_path 分支披露
    return None


def verify_opened_process(handle, opened_path):
    """开启句柄与访问时刻的进程身份比对 (学自 trainer GameSession
    verify_opened_process: process changed between verification and
    access — 拒绝访问替换进程)。返回警示文本或 None。

    PID 复用窗口 (游戏退出后系统把同 PID 发给新进程, 而工具仍持有
    旧句柄指向新进程) 下读数会来自完全无关的进程 — 归因污染。
    """
    now = _process_identity(handle)
    if now is None or opened_path is None:
        return None  # 无法判定 ≠ 已变化, 不虚报
    if now.lower() != opened_path.lower():
        return f"进程身份已变 (开启时 {opened_path} → 访问时 {now}) — 本次读数可能来自已被替换的进程"
    return None


def _integrity_rid(process_handle):
    """读取进程 token 完整性 RID; 无法判定返回 None (fail-open)。"""
    tok = wt.HANDLE()
    try:
        adv32 = ctypes.WinDLL("advapi32", use_last_error=True)
        adv32.OpenProcessToken.argtypes = [
            wt.HANDLE,
            wt.DWORD,
            ctypes.POINTER(wt.HANDLE),
        ]
        adv32.GetTokenInformation.argtypes = [
            wt.HANDLE,
            wt.DWORD,
            ctypes.c_void_p,
            wt.DWORD,
            ctypes.POINTER(wt.DWORD),
        ]
        adv32.GetSidSubAuthorityCount.argtypes = [ctypes.c_void_p]
        adv32.GetSidSubAuthority.argtypes = [ctypes.c_void_p, wt.DWORD]
        proc = k32.GetCurrentProcess() if process_handle is None else process_handle
        if not adv32.OpenProcessToken(proc, 0x0008, ctypes.byref(tok)):  # TOKEN_QUERY
            return None
        ret_len = wt.DWORD()
        # TokenIntegrityLevel = 25 (winnt.h)
        # A zero-buffer query normally returns FALSE/ERROR_INSUFFICIENT_BUFFER;
        # its required length, followed by the real read, determines success.
        adv32.GetTokenInformation(tok, 25, None, 0, ctypes.byref(ret_len))
        if ret_len.value < ctypes.sizeof(ctypes.c_void_p):
            return None
        buf = ctypes.create_string_buffer(ret_len.value)
        if not adv32.GetTokenInformation(
            tok, 25, buf, ret_len.value, ctypes.byref(ret_len)
        ):
            return None
        sid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p)).contents.value
        if not sid:
            return None
        adv32.GetSidSubAuthorityCount.restype = ctypes.POINTER(ctypes.c_ubyte)
        cnt = adv32.GetSidSubAuthorityCount(ctypes.c_void_p(sid)).contents.value
        if not cnt:
            return None
        adv32.GetSidSubAuthority.restype = ctypes.POINTER(ctypes.c_ulong)
        return adv32.GetSidSubAuthority(ctypes.c_void_p(sid), cnt - 1).contents.value
    except Exception:
        return None
    finally:
        if tok.value:
            k32.CloseHandle(tok)


def _token_integrity_level(process_handle):
    """读取进程 token 完整性级别名; 无法判定返回 None (fail-open)。"""
    rid = _integrity_rid(process_handle)
    return None if rid is None else _INTEGRITY_NAMES.get(rid, hex(rid))


def snapshot(h, max_addr=0x7FFF0000):
    from .memory_regions import contiguous_regions

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
        if mbi.State == 0x1000 and mbi.Prot in (2, 4, 5, 0x20, 0x40, 0x80):
            chunk_bytes = 16 * 1024 * 1024
            base = mbi.Base or 0
            for offset in range(0, rs, chunk_bytes):
                requested = min(chunk_bytes, rs - offset)
                buf = ctypes.create_string_buffer(requested)
                got = ctypes.c_size_t()
                k32.ReadProcessMemory(
                    h, ctypes.c_void_p(base + offset), buf, requested, ctypes.byref(got)
                )
                if 0 < got.value <= requested:
                    regions.append((base + offset, buf.raw[: got.value]))
                    total += got.value
                if got.value != requested:
                    _snapshot_partial["count"] += 1
        addr = (mbi.Base or 0) + rs
    return list(contiguous_regions(regions)), total


def save_snapshot(regions, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    index = []
    blob_path = os.path.join(out_dir, "snap.bin")
    with open(blob_path, "wb") as f:
        for base, data in regions:
            index.append({"base": base, "off": f.tell(), "len": len(data)})
            f.write(data)
    with open(os.path.join(out_dir, "index.json"), "w", encoding="utf-8") as fh:
        json.dump(index, fh, indent=1)
    return blob_path


def load_snapshot(snap_dir):
    with open(os.path.join(snap_dir, "index.json"), encoding="utf-8") as fh:
        index = json.load(fh)
    with open(os.path.join(snap_dir, "snap.bin"), "rb") as fh:
        blob = fh.read()
    return [(e["base"], blob[e["off"] : e["off"] + e["len"]]) for e in index]


# ---------------------------------------------------------------------------
# 版本探测: 枚举进程模块 -> Game.dll 路径/基址 -> 磁盘文件 VS_FIXEDFILEINFO


class _MODULEINFO(ctypes.Structure):
    _fields_ = [
        ("lpBaseOfDll", ctypes.c_void_p),
        ("SizeOfImage", wt.DWORD),
        ("EntryPoint", ctypes.c_void_p),
    ]


def enum_modules(h):
    """枚举进程模块 -> [(路径, 基址, 镜像字节数)]。镜像大小用于量出扫描窗口。

    先量后分: 第一趟拿 needed 字节数, 按量得大小精确分配再枚举, 不设
    1024 之类的数量上限 (模块再多也全量); 列表增长时按新尺寸重试一趟。
    """
    psapi = ctypes.WinDLL("psapi")
    needed = wt.DWORD()
    if not psapi.EnumProcessModulesEx(
        h, None, 0, ctypes.byref(needed), 0x03
    ) and not psapi.EnumProcessModules(h, None, 0, ctypes.byref(needed)):
        return []
    arr_t = ctypes.c_void_p * (needed.value // ctypes.sizeof(ctypes.c_void_p) or 1)
    arr = arr_t()
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
    mi = _MODULEINFO()
    for i in range(count):
        base = arr[i]
        if not base:
            continue
        if psapi.GetModuleFileNameExW(h, ctypes.c_void_p(base), buf, 2048):
            size = 0
            if psapi.GetModuleInformation(
                h, ctypes.c_void_p(base), ctypes.byref(mi), ctypes.sizeof(mi)
            ):
                size = int(mi.SizeOfImage)
            mods.append((buf.value, base, size))
    return mods


def read_file_version(path):
    """VS_FIXEDFILEINFO -> 'a.b.c.d'; 失败返回 None。"""
    try:
        with open(path, "rb") as fh:
            d = fh.read()
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


# 最近一次 snapshot 里失败区域计数 (299=ERROR_PARTIAL_COPY 部分拷贝)。
# 学自 trainer adapter 的不可读精确判定: 进程退出/权限不足/跨页边界时
# ReadProcessMemory 返回部分数据或失败, 光看空列表分不出原因。
_snapshot_partial = {"count": 0}


def load_profile_override(profile_json):
    """显式档案加载 (与 --export-profile 闭环); 返回 (档案或 None, 注文案)。

    坏档案不阻断探测: 失败返回降级注, 调用方回退内置矩阵 (学 trainer
    game_profile 的失败可见化——档案问题必须出现在 notes, 不静默吞)。
    """
    from .live_handle_chain import profile_from_dict

    try:
        p = profile_from_dict(
            json.loads(Path(profile_json).read_text(encoding="utf-8"))
        )
        return p, f"已加载显式档案: {profile_json} (tier={p.tier})"
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return None, f"显式档案不可用 ({type(exc).__name__}: {exc}), 回退内置"


def read_pe_fingerprint(path):
    """PE 头三要素 (machine, timestamp, image_size) -> ProfileFingerprint。

    档案指纹比对用: 读磁盘 Game.dll 的 COFF/Optional 头, 失败返回 None。
    """
    from gametool.live_handle_chain import ProfileFingerprint

    try:
        with open(path, "rb") as f:
            d = f.read(4096)
        e = struct.unpack_from("<I", d, 0x3C)[0]
        if d[e : e + 4] != b"PE\0\0" or e + 24 + 64 > len(d):
            return None
        machine, _numsec, timestamp = struct.unpack_from("<HHI", d, e + 4)
        image_size = struct.unpack_from("<I", d, e + 24 + 56)[0]
        return ProfileFingerprint(
            machine=machine, timestamp=timestamp, image_size=image_size
        )
    except Exception, struct.error:
        return None


def pe_machine(path):
    try:
        with open(path, "rb") as fh:
            d = fh.read(65536)  # PE 头可达 64KB (证书表前移时)
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
    mods = enum_modules(h)
    for path, base, size in mods:
        name = os.path.basename(path).lower()
        if name == "game.dll":
            ver = read_file_version(path)
            info["version"] = ver
            info["arch"] = "x64" if pe_machine(path) == 0x8664 else "x86"
            info["engine"] = "reforged" if info["arch"] == "x64" else "classic"
            info["game_dll"] = {"base": base, "path": path, "size": size}
            break
    if info["game_dll"] is None:
        # 失败可见化 (学 trainer GameModuleNotFoundError 的状态精确区分
        # 「进程活着但已验证映像不可见」+ game_module_base 的模块枚举
        # 交叉验证): 给出实际枚举到的模块名, 排查不再两眼一抹黑。
        info["modules_seen"] = [os.path.basename(p) for p, _b, _s in mods]  # 全量列出
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
    from .pack_query_cli import _object_rows

    nm = {}
    for row in _object_rows(Path(pack_dir), kind)[1:]:
        nm[row[1].encode("latin-1")] = clean(row[4])
    # BASE_NAMES_EN 兜底按 kind 匹配分类 (旧版恒用 item 过滤 → 单位/英雄在无包时全 '?')
    kind_marks = ("item",) if kind == "物品" else ("unit", "hero", "building")
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, repo)
    try:
        from gametool.base_names import BASE_NAMES_EN, BASE_CATEGORIES

        for code, cat in BASE_CATEGORIES.items():
            cat_text = str(cat).lower()
            if cat and any(mark in cat_text for mark in kind_marks):
                n2 = BASE_NAMES_EN.get(code, "")
                if n2 and len(code) == 4:
                    nm.setdefault(code.encode("latin-1"), n2)
    except Exception:
        pass  # 376: base_names 不可用 (隔离环境/import 失败) — 退 TSV 名/问号, 兜底语义
    return nm


def _icon_paths_from_pack(pack_dir):
    from .pack_query_cli import _field_rows

    paths = {}
    for c in _field_rows(Path(pack_dir))[1:]:
        if (
            len(c) >= 6
            and c[0] == "物品"
            and c[3].startswith(("display:icon", "base:art"))
            and c[5].lower().endswith(".blp")
            and "commandbuttons" in c[5].lower()
        ):
            # 同一物品 base: 继承图标行与自定义图标行并存时，自定义行
            # 优先：来源列以 base: 开头的行不得覆盖已 collected 的非继承值
            # （此前靠 TSV 排序碰巧正确，排序翻转就会拿继承图标当模板）。
            if c[1] in paths and len(c) >= 7 and c[6].startswith("base:"):
                continue
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
        cache_dir = os.path.join(os.environ.get("TEMP", "."), "gamexray-icon-cache")
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
            from gametool.archive_source import PathArchiveSource

            archives = []
            failed_roots = []
            for m in _mpq_roots():
                if os.path.exists(m):
                    try:
                        archives.append(PathArchiveSource(m).open())
                    except Exception:
                        # 376: 归档打开失败计入披露 — 不让用户把「归档坏了」
                        # 误读成「图标本来就不存在」
                        failed_roots.append(m)
            if failed_roots and verbose:
                print(f"⚠ MPQ 归档打开失败 {len(failed_roots)} 个: {failed_roots}")
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
                                with open(dst, "wb") as fh:
                                    fh.write(arch.read_file(cand))
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
        with open(path, "rb") as fh:
            img = decode_blp(fh.read())
    except OSError:
        img = None
    if img is None:
        _ICON_CACHE[key] = None
        return None
    img = img.resize((size, size), Image.Resampling.LANCZOS)
    arr = np.asarray(img.convert("L"), dtype=np.float64)
    _ICON_CACHE[key] = arr
    return arr


_WINDOW_ENUM_PROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)


def _capture_setup():
    """Use pointer-sized GDI/window handles on both 32-bit and 64-bit Python."""
    for api, name, arguments, result in (
        (u32, "EnumWindows", [_WINDOW_ENUM_PROC, wt.LPARAM], wt.BOOL),
        (u32, "GetWindowTextLengthW", [wt.HWND], ctypes.c_int),
        (u32, "GetWindowTextW", [wt.HWND, wt.LPWSTR, ctypes.c_int], ctypes.c_int),
        (
            u32,
            "GetWindowThreadProcessId",
            [wt.HWND, ctypes.POINTER(wt.DWORD)],
            wt.DWORD,
        ),
        (u32, "IsIconic", [wt.HWND], wt.BOOL),
        (u32, "GetClientRect", [wt.HWND, ctypes.POINTER(wt.RECT)], wt.BOOL),
        (u32, "GetDC", [wt.HWND], wt.HDC),
        (u32, "ReleaseDC", [wt.HWND, wt.HDC], ctypes.c_int),
        (u32, "PrintWindow", [wt.HWND, wt.HDC, wt.UINT], wt.BOOL),
        (g32, "CreateCompatibleDC", [wt.HDC], wt.HDC),
        (
            g32,
            "CreateCompatibleBitmap",
            [wt.HDC, ctypes.c_int, ctypes.c_int],
            wt.HBITMAP,
        ),
        (g32, "SelectObject", [wt.HDC, wt.HANDLE], wt.HANDLE),
        (g32, "DeleteObject", [wt.HANDLE], wt.BOOL),
        (g32, "DeleteDC", [wt.HDC], wt.BOOL),
        (
            g32,
            "GetDIBits",
            [
                wt.HDC,
                wt.HBITMAP,
                wt.UINT,
                wt.UINT,
                ctypes.c_void_p,
                ctypes.c_void_p,
                wt.UINT,
            ],
            ctypes.c_int,
        ),
    ):
        function = getattr(api, name)
        function.argtypes = arguments
        function.restype = result


def _window_title(hwnd):
    length = u32.GetWindowTextLengthW(hwnd)
    if not length:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    copied = u32.GetWindowTextW(hwnd, buffer, length + 1)
    # Win32 may overestimate a caption length for mixed ANSI/Unicode windows.
    # Growth beyond the allocated buffer still makes this enumeration unstable.
    if copied <= 0 or copied > length or u32.GetWindowTextLengthW(hwnd) > length:
        raise RuntimeError(f"窗口 0x{hwnd:X} 标题读取不完整或正在变化")
    return buffer.value


def _window_process_id(hwnd):
    owner = wt.DWORD()
    if not u32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner)) or not owner.value:
        raise RuntimeError(f"无法确认窗口 0x{hwnd:X} 的 PID")
    return owner.value


def _select_capture_window(title, pid):
    candidates = []
    diagnostics = []

    @_WINDOW_ENUM_PROC
    def collect(hwnd, _parameter):
        # ctypes callbacks cannot propagate Python exceptions across the C call.
        try:
            if _window_title(hwnd) == title:
                candidates.append((hwnd, _window_process_id(hwnd)))
        except Exception as exc:
            diagnostics.append(str(exc))
        return True

    if not u32.EnumWindows(collect, 0):
        raise RuntimeError("EnumWindows 未完成；无法唯一确认游戏窗口")
    if diagnostics:
        raise RuntimeError("窗口枚举证据不完整：" + "; ".join(diagnostics))
    matches = [
        (hwnd, owner) for hwnd, owner in candidates if pid is None or owner == pid
    ]
    target = f"PID {pid} 的" if pid is not None else ""
    if not matches:
        raise RuntimeError(f"未找到{target}窗口 {title}")
    if len(matches) != 1:
        detail = ", ".join(f"PID {owner}/HWND 0x{hwnd:X}" for hwnd, owner in matches)
        raise RuntimeError(f"检测到多个{target}同标题窗口，无法唯一选择：{detail}")
    return matches[0]


def _verify_capture_window(hwnd, title, pid):
    current, owner = _select_capture_window(title, pid)
    if current != hwnd or owner != pid:
        raise RuntimeError("捕获窗口身份已变化；丢弃本次图像，请重新探针")


def capture_window(title="Warcraft III", *, pid=None):
    _capture_setup()
    hwnd, window_pid = _select_capture_window(title, pid)
    if u32.IsIconic(hwnd):
        raise RuntimeError("游戏窗口已最小化；当前无法识别图标，不能判定背包是否为空")
    rc = wt.RECT()
    if not u32.GetClientRect(hwnd, ctypes.byref(rc)):
        raise RuntimeError("GetClientRect 失败；当前无法取得游戏窗口大小")
    w, h = rc.right - rc.left, rc.bottom - rc.top
    if w <= 0 or h <= 0:
        raise RuntimeError("窗口客户区为空；当前无法识别图标，不能判定背包是否为空")
    with ExitStack() as cleanup:
        hdc = u32.GetDC(hwnd)
        if not hdc:
            raise RuntimeError("GetDC 失败；当前无法捕获游戏画面")
        cleanup.callback(u32.ReleaseDC, hwnd, hdc)
        md = g32.CreateCompatibleDC(hdc)
        if not md:
            raise RuntimeError("CreateCompatibleDC 失败；当前无法捕获游戏画面")
        bmp = None

        def release_gdi():
            # Deleting the DC also releases any selection if restoring it failed.
            try:
                g32.DeleteDC(md)
            finally:
                if bmp:
                    g32.DeleteObject(bmp)

        cleanup.callback(release_gdi)
        bmp = g32.CreateCompatibleBitmap(hdc, w, h)
        if not bmp:
            raise RuntimeError("CreateCompatibleBitmap 失败；当前无法捕获游戏画面")
        old = g32.SelectObject(md, bmp)
        failed_handle = ctypes.c_void_p(-1).value
        if not old or old in (-1, failed_handle):
            raise RuntimeError("SelectObject 失败；当前无法捕获游戏画面")
        selected = True

        def restore_bitmap():
            nonlocal selected
            if selected:
                previous = g32.SelectObject(md, old)
                if not previous or previous in (-1, failed_handle):
                    return False
                selected = False
            return True

        cleanup.callback(restore_bitmap)
        _verify_capture_window(hwnd, title, window_pid)
        # Client dimensions need PW_CLIENTONLY together with PW_RENDERFULLCONTENT.
        if not u32.PrintWindow(hwnd, md, 1 | 2):
            raise RuntimeError(
                "PrintWindow 未成功 (返回 0)；当前无法捕获游戏画面，不能判定背包是否为空"
            )
        # GetDIBits requires the bitmap to be deselected from every DC first.
        if not restore_bitmap():
            raise RuntimeError("SelectObject 恢复失败；当前无法读取完整图像")
        bi = ctypes.create_string_buffer(
            struct.pack("<IiiHHIIiiII", 40, w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        )
        buf = ctypes.create_string_buffer(w * h * 4)
        copied = g32.GetDIBits(md, bmp, 0, h, buf, bi, 0)
        if copied != h:
            raise RuntimeError(
                f"GetDIBits 未取得完整图像 (请求 {h} 行，读取 {copied} 行)；当前无法识别图标"
            )
        _verify_capture_window(hwnd, title, window_pid)
        arr = np.frombuffer(buf.raw, dtype=np.uint8).reshape(h, w, 4)
        rgb = arr[:, :, :3]
        if np.array_equal(rgb.min(axis=(0, 1)), rgb.max(axis=(0, 1))):
            raise RuntimeError(
                "游戏窗口捕获为纯色空帧；当前无法识别图标，不能判定背包是否为空。"
                "请保持游戏正常显示后重试"
            )
        return Image.fromarray(rgb[:, :, ::-1].copy()), (w, h)


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
        _ones_fft, S1, varw = cache[(h, w)]
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
    pid: "int | None"
    version: "dict[str, object] | None"
    slots: list[Any]
    notes: list[str]
    selected_unit: Any
    units: list[Any]
    unit_matches: list[Any]
    owner_counts: "dict[int, int] | None"
    owned_units: "list[dict[str, object]] | None"
    all_units: "list[dict[str, object]] | None"
    resources: "list[dict[str, object]] | None"
    player_rows: "list[str] | None"
    nick_raw: "str | None"
    input_error: bool


def _icons_memory_requests(
    *,
    save_snapshot_dir=None,
    load_snapshot_dir=None,
    unit_query=None,
    players=False,
    all_units=False,
    resources=None,
    nick=None,
    export_profile=None,
    profile_json=None,
):
    return [
        option
        for option, active in (
            ("--players", players),
            ("--all-units", all_units),
            ("--resources", resources is not None),
            ("--unit", unit_query is not None),
            ("--nick", nick is not None),
            ("--profile-json", profile_json is not None),
            ("--export-profile", export_profile is not None),
            ("--save-snapshot", save_snapshot_dir is not None),
            ("--load-snapshot", load_snapshot_dir is not None),
        )
        if active
    ]


def _read_icon_slots(report, pack_dir, verbose):
    if pack_dir is None:
        report["notes"].append("图标匹配跳过 (离线快照无图标模板目录)")
        return []
    if report["pid"] is None:
        report["notes"].append("图标匹配跳过 (没有可绑定的游戏 PID，不能猜测当前窗口)")
        return []
    try:
        templates, names = build_templates(pack_dir, verbose=verbose)
        if not templates:
            report["notes"].append("无图标模板")
            return []
        img, wh = capture_window(pid=report["pid"])
        if verbose:
            print(f"窗口 {wh[0]}x{wh[1]}")
        picked = match_inventory(img, templates, names)
        if not picked:
            picked = match_image_full(img, templates, names)
        return [
            {"name": n, "item": i, "score": round(s, 3), "pos": list(pos), "size": sz}
            for s, i, n, pos, sz in picked
        ]
    except Exception as ex:
        report["notes"].append(f"图标匹配异常: {ex}")
        return []


def append_live_journal(rep):
    """把本次探测追加到 journal (cache/live/journal-v1.jsonl)。

    学自 trainer 的 journal-v4 思路: 版本/档案/模式/规模逐次落盘, 坏读数
    可追溯。fail-open: 任何异常静默跳过, 绝不影响探测结果。
    """
    try:
        from .cache_root import gamexray_cache_root

        root = gamexray_cache_root() / "live"
        root.mkdir(parents=True, exist_ok=True)
        ver = rep.get("version") or {}
        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "pid": rep.get("pid"),
            "version": ver.get("version"),
            "engine": ver.get("engine"),
            "strategy": rep.get("strategy_used"),
            "units": len(rep.get("units") or []),
            "owned": len(rep.get("owned_units") or [])
            if rep.get("owned_units")
            else None,
            "resources": len(rep.get("resources") or []) if rep.get("resources") else 0,
            "profile_note": next(
                (n for n in rep.get("notes") or [] if str(n).startswith("偏移档案")),
                None,
            ),
        }
        with (root / "journal-v1.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        # 376: journal 是可追溯性资产 — 失败不得双重静默, 留痕 errors-v1.log
        import traceback as _tb

        try:
            from .cache_root import gamexray_cache_root

            _log = gamexray_cache_root() / "live" / "errors-v1.log"
            _log.parent.mkdir(parents=True, exist_ok=True)
            with _log.open("a", encoding="utf-8") as _fh:
                _fh.write(
                    "[%s] stage=journal-fail\n%s\n"
                    % (time.strftime("%Y-%m-%dT%H:%M:%S"), _tb.format_exc())
                )
        except Exception:
            pass  # 最终兜底: 磁盘不可写时无处分流, 只能静默


def _parse_resources_arg(parts):
    """--resources auto 或 --resources 金币 木材 -> ("auto") / (金, 木) / None。"""
    if not parts:
        return None
    if parts == ["auto"]:
        return "auto"
    if len(parts) != 2:
        raise ValueError("--resources 需要两个数值：金币 木材 (或 auto)")
    try:
        values = (float(parts[0]), float(parts[1]))
    except ValueError as exc:
        raise ValueError("--resources 的金币/木材必须是有限数字") from exc
    if not all(math.isfinite(value) for value in values):
        raise ValueError("--resources 的金币/木材必须是有限数字")
    return values


def read_live(
    pack_dir,
    strategy="auto",
    save_snapshot_dir=None,
    load_snapshot_dir=None,
    verbose=True,
    unit_query=None,
    players=False,
    all_units=False,
    resources=None,
    nick=None,
    export_profile=None,
    profile_json=None,
    pid=None,
):
    """Read one fresh probe and release all of its process handles on every exit."""
    previous_pid = _active_pid["pid"]
    _active_pid["pid"] = None
    _snapshot_partial["count"] = 0
    try:
        with ExitStack() as process_scope:
            return _read_live(
                pack_dir,
                strategy,
                save_snapshot_dir,
                load_snapshot_dir,
                verbose,
                unit_query,
                players,
                all_units,
                resources,
                nick,
                export_profile,
                profile_json,
                pid,
                process_scope=process_scope,
            )
    finally:
        _active_pid["pid"] = previous_pid


def _read_live(
    pack_dir,
    strategy="auto",
    save_snapshot_dir=None,
    load_snapshot_dir=None,
    verbose=True,
    unit_query=None,
    players=False,
    all_units=False,
    resources=None,
    nick=None,
    export_profile=None,
    profile_json=None,
    pid=None,
    *,
    process_scope,
):
    """resources: (金币, 木材) 元组为报数校准; "auto" 为自动差分 (免报数)。"""
    report: _LiveReport = {
        "strategy_used": None,
        "pid": None,
        "version": None,
        "slots": [],
        "notes": [],
        "selected_unit": None,
        "units": [],
        "unit_matches": [],
        "owner_counts": None,
        "owned_units": None,
        "all_units": None,
        "resources": None,
        "player_rows": None,
        "nick_raw": nick,
        "input_error": False,
    }
    if strategy == "icons":
        memory_requests = _icons_memory_requests(
            save_snapshot_dir=save_snapshot_dir,
            load_snapshot_dir=load_snapshot_dir,
            unit_query=unit_query,
            players=players,
            all_units=all_units,
            resources=resources,
            nick=nick,
            export_profile=export_profile,
            profile_json=profile_json,
        )
        if memory_requests:
            report["input_error"] = True
            report["notes"].append(
                "参数错误：icons 仅识别窗口图标；"
                + "、".join(memory_requests)
                + " 需要内存读取，请使用 --strategy auto 或 handle"
            )
            return report
    pure_icons = strategy == "icons"
    ver: dict[str, object] | None = None
    h = 0
    opened_path: str | None = None  # 进程身份基线 (离线快照无此概念)
    max_addr = 0x7FFF0000
    if load_snapshot_dir:
        regions, total = load_snapshot(load_snapshot_dir), 0
        total = sum(len(d) for _, d in regions)
        if verbose:
            print(f"离线快照 {len(regions)} 区 {total // 1048576}MB")
    else:
        if not pure_icons:
            mem_setup()
        pids = find_war3_pids()
        if not pids:
            report["notes"].append("war3 未运行")
            return report
        if pid is not None:
            if pid not in pids:
                report["notes"].append(f"--pid {pid} 不在运行中的 war3 进程列表 {pids}")
                return report
            chosen = pid
        elif len(pids) > 1:
            # 多实例不猜 (学自 trainer find_war3: Multiple clients ->
            # select an explicit PID) — 自动选第一个可能读错人。
            report["notes"].append(
                "检测到多个 war3 进程 " + str(pids) + " — 不猜, 用 --pid <PID> 显式选择"
            )
            return report
        else:
            chosen = pids[0]
        report["pid"] = chosen  # 追溯: 本次读的是哪个游戏进程 (多实例排查)
        _active_pid["pid"] = chosen  # 异常日志关联目标进程
        if pure_icons:
            report["notes"].append(
                "图标模式只提供所绑定 PID 窗口中的可见图像匹配；pos 是图像像素，"
                "不提供版本/偏移、单位归属、世界坐标或玩家资源证据"
            )
            slots = _read_icon_slots(report, pack_dir, verbose)
            if slots:
                report["strategy_used"] = "icons"
                report["slots"] = slots
            else:
                report["notes"].append("本次未确认可见图标；不能据此判断背包为空")
            return report
        h = open_process(chosen)
        if not h:
            report["notes"].append("OpenProcess 失败 (需管理员)")
            return report
        process_scope.callback(k32.CloseHandle, h)
        opened_path = _process_identity(
            h
        )  # 身份基线 (防 PID 复用, 学 trainer GameSession)
        game_rid, self_rid = _integrity_rid(h), _integrity_rid(None)
        if game_rid and self_rid and self_rid < game_rid:
            report["notes"].append(
                f"权限不足 (只读访问可能被系统拒绝): 游戏 "
                f"{_INTEGRITY_NAMES.get(game_rid, hex(game_rid))} / 工具 "
                f"{_INTEGRITY_NAMES.get(self_rid, hex(self_rid))} — "
                "请以与游戏相同的权限重新启动工具"
            )
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
        regions, total = snapshot(h, max_addr)
        if verbose:
            print(f"快照 {len(regions)} 区 {total // 1048576}MB")
        if not regions and _snapshot_partial["count"]:
            report["notes"].append(
                f"快照 0 区域可读 ({_snapshot_partial['count']} 个区域部分拷贝/拒绝访问) — "
                "进程可能已退出, 或权限/完整性级别不足"
            )
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

            hc = importlib.import_module("gametool.live_handle_chain")
            gd = ver.get("game_dll")
            dll_base = gd.get("base", 0) if isinstance(gd, dict) else 0
            if not dll_base:
                seen = ver.get("modules_seen")
                hint = (
                    "; 进程内枚举到的模块: " + ", ".join(seen)
                    if isinstance(seen, list) and seen
                    else ""
                )
                report["notes"].append(
                    "未取到 Game.dll 基址 (进程存活但按文件名未命中)" + hint
                )
                return None
            reader = hc.MemoryReader(regions)
            v_str = str(ver.get("version") or "")
            v_engine = str(ver.get("engine") or "classic")
            v_arch = str(ver.get("arch") or "x86")
            profile = hc.resolve_profile(v_str, v_engine, v_arch)
            if profile_json:
                # 显式档案优先 (与 --export-profile 闭环); 失败降级内置并明示。
                loaded, note = load_profile_override(profile_json)
                report["notes"].append(note)
                if loaded is not None:
                    profile = loaded
            # 档案诊断面: exact/rva-table/template/reforged-pending 四档, notes 永远携带。
            report["notes"].append(hc.describe_live_profile(v_str, v_engine, v_arch))
            offsets = profile.handle_chain
            last_stage: list[str] = []  # 推导阶段追踪 (诊断带最后阶段)
            if offsets is not None and (profile.checks or profile.fingerprint):
                disk_fp = None
                _gd = ver.get("game_dll")
                if isinstance(_gd, dict) and _gd.get("path"):
                    disk_fp = read_pe_fingerprint(str(_gd["path"]))
                ok, fails, patches = hc.verify_profile(
                    reader, dll_base, profile, disk_fp
                )
                if patches:
                    report["notes"].append(
                        f"运行时补丁差异 {len(patches)} 处 — 磁盘 PE 指纹匹配证实同版本,"
                        f" 差异为平台加载后所打 (放行; 明细: {'; '.join(patches)})"
                    )
                if not ok:
                    report["notes"].append(
                        "档案自校验失败 ("
                        + "; ".join(fails)
                        + ") — 偏移档案与本进程 Game.dll 不符, 不沿用, 改走结构推导"
                    )
                    offsets = None
            if offsets is None and profile.tier != "reforged-pending":
                # 扫描窗口量出来, 不拍数字: 进程内镜像大小 (GetModuleInformation)
                # -> 磁盘 PE size-of-image -> 兜底扫满用户态。
                gd_raw = ver.get("game_dll")
                gd = gd_raw if isinstance(gd_raw, dict) else {}
                span_end = dll_base + int(gd.get("size") or 0)
                if span_end <= dll_base and gd.get("path"):
                    fp0 = read_pe_fingerprint(str(gd["path"]))
                    if fp0 is not None and fp0.image_size:
                        span_end = dll_base + fp0.image_size
                if span_end <= dll_base:
                    span_end = 0x7FFE0000

                def _track(stage) -> None:  # hc.DiscoveryStage (运行时导入)
                    last_stage.append(stage.name)

                offsets = hc.derive_offsets(
                    reader,
                    dll_base,
                    span_end,
                    budget=None,
                    on_stage=_track,
                )
            if offsets is None:
                reason = (
                    "重制版 x64 档案待建立"
                    if profile.tier == "reforged-pending"
                    else "结构推导失败"
                )
                if last_stage:
                    reason += f", 最后阶段: {last_stage[-1]}"
                report["notes"].append(
                    f"句柄链不可用 ({reason}), 回退 chain/icons 策略"
                )
                return None
            system = hc.HandleSystem(reader, dll_base, offsets)
            if not system.valid:
                report["notes"].append("句柄管理器不可读")
                return None
            if export_profile:
                # 档案固化 (学自 trainer profiles/*.json): 本进程实际工作
                # 着的完整档案写 JSON — 档案命中时原样导出, 结构推导时把
                # 推导出的 handle_chain 填入模板档案, 供升 exact 复用。
                try:
                    from dataclasses import replace as _dc_replace
                    from pathlib import Path as _Path

                    if offsets is profile.handle_chain:
                        eff = profile
                    else:
                        eff = _dc_replace(
                            profile,
                            handle_chain=offsets,
                            source="真机推导固化 (live --export-profile)",
                        )
                    out_p = _Path(export_profile)
                    out_p.parent.mkdir(parents=True, exist_ok=True)
                    out_p.write_text(
                        json.dumps(
                            hc.profile_to_dict(eff),
                            ensure_ascii=False,
                            indent=1,
                        ),
                        encoding="utf-8",
                    )
                    report["notes"].append("档案已固化 -> " + export_profile)
                except OSError as exc:
                    report["notes"].append(
                        f"档案固化失败 ({type(exc).__name__}: {exc})"
                    )
            item_names = load_names(pack_dir)
            unit_names = load_names(pack_dir, "单位")

            def describe(inv):
                px, py = hc.read_unit_pos(reader, inv.unit_addr)
                return {
                    "unit": unit_names.get(inv.code.encode("latin-1"), "?"),
                    "code": inv.code,
                    "addr": inv.unit_addr,
                    "x": px,
                    "y": py,
                    "items": [
                        {
                            "slot": i.slot,
                            "name": item_names.get(i.code.encode("latin-1"), "?"),
                            "code": i.code,
                            "addr": i.item_addr,
                        }
                        for i in inv.items
                        if hc.is_fourcc(i.code)
                    ],
                }

            units = hc.walk_item_units(reader, system, offsets)
            report["units"] = [describe(u) for u in units]
            owned: list[Any] | None = None
            if players:
                owned = hc.walk_owned_units(reader, system, offsets)
                counts, listed = hc.summarize_owners(owned)
                report["owner_counts"] = counts
                report["owned_units"] = [
                    {
                        "owner": u.owner,
                        "unit": unit_names.get(u.code.encode("latin-1"), "?"),
                        "code": u.code,
                        "addr": u.addr,
                        "x": u.x,
                        "y": u.y,
                    }
                    for u in listed
                ]
            if all_units:
                all_rows = hc.walk_owned_units(reader, system, offsets)
                report["all_units"] = [
                    {
                        "owner": u.owner,
                        "unit": unit_names.get(u.code.encode("latin-1"), "?"),
                        "code": u.code,
                        "addr": u.addr,
                        "x": u.x,
                        "y": u.y,
                    }
                    for u in all_rows
                ]
            if resources is not None:
                if resources == "auto":
                    import time as _time

                    readers = [reader]
                    for _ in range(2):  # 差分采样节奏 (非数据上限; 样本越多排名越稳)
                        _time.sleep(3)
                        readers.append(hc.reader_from_snapshot(snapshot(h, max_addr)))
                    found, total_anchors = hc.rank_auto_rows(
                        hc.find_auto_resource_rows(readers)
                    )
                    report["notes"].append(
                        f"auto 锚点共 {total_anchors} 个, 按木/人口可信度排序全量输出"
                    )
                else:
                    found = hc.find_resource_layout(reader, resources[0], resources[1])
                    if hc.cached_resource_hit():
                        report["notes"].append(
                            "资源布局命中上次锚缓存 (±1 值校验通过, 免全扫;"
                            " 换局/搬移会自动失效重扫)"
                        )
                report["resources"] = [
                    {
                        "addr": hex(r.addr),
                        "gold": round(r.gold) if r.gold is not None else None,
                        "lumber": round(r.lumber) if r.lumber is not None else None,
                        "food": r.food,
                    }
                    for r in found
                ]
                # 按玩家号的权威链直读 + 槽位英雄/昵称标注 (每次运行现取,
                # 换局自动跟随新结构)。昵称来自 --nick 大厅号=名字。
                try:
                    chain_rows = hc.read_player_resources_chain(
                        reader.u32, dll_base, str(ver.get("version"))
                    )
                    if chain_rows:
                        me_idx = hc.read_local_player_index(reader, dll_base, offsets)
                        pool = (
                            owned
                            if owned is not None
                            else hc.walk_owned_units(reader, system, offsets)
                        )
                        nicks = hc.parse_nick_overrides(report.get("nick_raw"))
                        lines = hc.format_player_rows(
                            chain_rows,
                            hc.owner_slot_codes(pool),
                            unit_names,
                            me_idx,
                            nicks,
                        )
                        if lines:
                            report["player_rows"] = lines
                except Exception as ex:
                    report["notes"].append(f"按玩家号标注失败: {ex}")
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
        if pack_dir is None:
            report["notes"].append("结构链跳过 (离线快照无知识包, 物品名单不可用)")
            return []
        try:
            import importlib

            hero_chain = importlib.import_module("gametool.hero_chain")
            names = load_names(pack_dir)
            unit_names = load_names(pack_dir, "单位")
            return hero_chain.read_inventory(
                regions, names, unit_names=unit_names, verbose=verbose
            )
        except Exception as ex:
            report["notes"].append(f"结构链异常: {ex}")
            return []

    def try_resources_scan():
        """版本无关的资源读取兜底 (template/reforged 档)。

        报数校准与 auto 差分是纯内存值扫描, 不需要句柄链偏移——
        引擎为每个玩家维护同构 float 结构这一事实跨版本成立。重制版
        等无档案版本借此仍可读全队资源近似值; 归属与权威链标注
        (player_rows) 不可用, notes 必须明示。
        """
        if resources is None:
            return None
        try:
            import importlib
            import time as _time

            hc1 = importlib.import_module("gametool.live_handle_chain")
            total_b = sum(len(d) for _, d in regions)
            reader = hc1.reader_from_snapshot((regions, total_b))
            if resources == "auto":
                readers = [reader]
                for _ in range(2):  # 差分采样节奏 (非数据上限; 样本越多排名越稳)
                    _time.sleep(3)
                    readers.append(hc1.reader_from_snapshot(snapshot(h, max_addr)))
                found, total_anchors = hc1.rank_auto_rows(
                    hc1.find_auto_resource_rows(readers)
                )
                report["notes"].append(
                    f"auto 锚点共 {total_anchors} 个, 按木/人口可信度排序全量输出"
                )
            else:
                found = hc1.find_resource_layout(reader, resources[0], resources[1])
                if hc1.cached_resource_hit():
                    report["notes"].append(
                        "资源布局命中上次锚缓存 (±1 值校验通过, 免全扫)"
                    )
            if found:
                report["resources"] = [
                    {
                        "addr": hex(r.addr),
                        "gold": round(r.gold) if r.gold is not None else None,
                        "lumber": round(r.lumber) if r.lumber is not None else None,
                        "food": r.food,
                    }
                    for r in found
                ]
                report["notes"].append(
                    "资源读取走版本无关扫描 (当前版本无句柄链档案: 数值来自"
                    "同布局结构, 玩家归属与权威链标注不可用)"
                )
                return report["resources"]
            report["notes"].append("资源扫描无结果 (报数与内存值不匹配或已变动)")
            return None
        except Exception as ex:
            report["notes"].append(
                f"资源兜底扫描异常: {ex}" + log_live_exception("try_resources_scan", ex)
            )
            return None

    if strategy in ("auto", "handle"):
        slots = try_handle()
        if slots is not None:
            warn = verify_opened_process(h, opened_path)
            if warn:
                report["notes"].append(warn)
            report["strategy_used"] = "handle"
            return report
    # 资源兜底: 句柄链不可用 (reforged-pending/template) 时资源读取不该陪葬。
    if resources is not None and report.get("resources") is None:
        try_resources_scan()
    if strategy in ("auto", "chain"):
        slots = try_chain()
        if slots:
            warn = verify_opened_process(h, opened_path)
            if warn:
                report["notes"].append(warn)
            report["strategy_used"] = "chain"
            report["slots"] = slots
            return report
    if strategy in ("auto", "icons"):
        slots = _read_icon_slots(report, pack_dir, verbose)
        if slots:
            warn = verify_opened_process(h, opened_path)
            if warn:
                report["notes"].append(warn)
            report["strategy_used"] = "icons"
            report["slots"] = slots
            return report
    warn = verify_opened_process(h, opened_path)
    if warn:
        report["notes"].append(warn)
    report["notes"].append(
        "本次未确认背包内容；请按上述进程/档案/图像诊断重探，不能据此判断背包为空"
    )
    return report


def campaign_locate_hint(rep: dict[str, Any]) -> str:
    """从一次实时读数压出战役 locate 命令模板 (特征码交集定位任务关)。

    战役工作流第④步 (码 × 子地图交集) 此前靠手工从 live 输出抄码:
    本函数取 当前选中单位码+其全部背包物品码 (war3 背包 6 格, 不截 4
    — 第 5/6 格的关键任务物品漏出会定位错关), 再补全部匹配单位码,
    去重满量, 返回 "码1;码2;…" —— 玩家直接在 pack-query locate 后
    使用; locate 端满量无上限 (del limit), 模板截断零收益。"""
    codes: list[str] = []
    sel = rep.get("selected_unit") or {}
    if sel.get("code"):
        codes.append(str(sel["code"]))
    for it in sel.get("items") or []:
        if it.get("code"):
            codes.append(str(it["code"]))
    for u in rep.get("unit_matches") or []:
        if u.get("code"):
            codes.append(str(u["code"]))
    uniq = list(dict.fromkeys(codes))
    return ";".join(uniq)


def campaign_locate_command(pack: str, rep: dict[str, Any]) -> str:
    """把定位模板具体化成可直接复制执行的命令 (带上 live 已知的包路径)。

    占位符 `<战役包>` 还要人填路径——而 live 的 --pack 参数本身就是
    当前图的知识包 (战役时为容器包, locate 自动逐关聚合)。"""
    codes = campaign_locate_hint(rep)
    if not codes:
        return ""
    return 'pack-query "' + pack + '" locate ' + codes


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
        "--all-units",
        action="store_true",
        help="全对象扫描: 场上全部单位 (所有者+四码+坐标), 不按物品/玩家号过滤",
    )
    ap.add_argument(
        "--resources",
        nargs="+",
        metavar=("金币|auto", "木材"),
        help="读取全部玩家资源: 报数校准 (--resources 169 808) 或自动差分 (--resources auto)",
    )
    ap.add_argument(
        "--nick",
        metavar="大厅号=名字",
        help="按玩家号标注时的真实玩家名覆盖, 如 --nick 「1=飞信对信,2=大白海岸,3=萌新」",
    )
    ap.add_argument(
        "--export-profile",
        metavar="JSON路径",
        help="句柄链可用时把本进程实际工作的档案固化为 JSON (升 exact 复用)",
    )
    ap.add_argument(
        "--profile-json",
        metavar="JSON路径",
        help="显式档案文件优先于内置 (--export-profile 固化结果的复用端)",
    )
    ap.add_argument(
        "--pid",
        type=int,
        help="多实例时显式指定游戏进程 PID (多实例不给则不猜报错)",
    )
    args = ap.parse_args(argv)
    try:
        resource_request = _parse_resources_arg(args.resources)
    except ValueError as exc:
        ap.error(str(exc))
    if args.strategy == "icons":
        memory_requests = _icons_memory_requests(
            save_snapshot_dir=args.save_snapshot,
            load_snapshot_dir=args.load_snapshot,
            unit_query=args.unit,
            players=args.players,
            all_units=args.all_units,
            resources=resource_request,
            nick=args.nick,
            export_profile=args.export_profile,
            profile_json=args.profile_json,
        )
        if memory_requests:
            ap.error(
                "icons 仅识别窗口图标；"
                + "、".join(memory_requests)
                + " 需要内存读取，请使用 --strategy auto 或 handle"
            )
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
        all_units=args.all_units,
        resources=resource_request,
        nick=args.nick,
        export_profile=args.export_profile,
        profile_json=args.profile_json,
        pid=args.pid,
    )
    append_live_journal(rep)
    if rep.get("input_error"):
        print(json.dumps(rep, ensure_ascii=False, indent=1, default=str))
        return 2
    counts = rep.get("owner_counts") or {}
    if counts:
        print("== 所有者分布 ==")
        print("  " + "  ".join(f"P{o}:{n}" for o, n in sorted(counts.items())))
    res = rep.get("resources")
    if res is not None:
        print(f"== 玩家资源 (同布局结构 {len(res)} 个) ==")
        for r2 in res:
            food = f" 人口~{r2['food']}" if r2.get("food") is not None else ""
            gold = r2["gold"] if r2.get("gold") is not None else "?"
            lumber = r2["lumber"] if r2.get("lumber") is not None else "?"
            print(f"  {r2['addr']}: 金{gold} 木{lumber}{food}")
    prows = rep.get("player_rows")
    owned_units = rep.get("owned_units")
    if (args.players or args.resources) and owned_units is None:
        print("== 单位归属不可读 ==")
        print("  ⚠ 本次未取得单位归属记录；请检查下方进程/权限/档案诊断并重探。")
        print("    禁止把场上单位/背包断言为某玩家的; 操作者只能以'当前选中'+复探位移")
        print("    推断, 且必须向玩家明示不确定。")
    if args.resources and prows is None:
        print("== 资源归属不可读 ==")
        print("  未取得按玩家号的资源/本地玩家证据；同布局结构值不能指认为具体玩家。")
        print(
            "  可用 --resources 金币 木材 校准，或在资源变化时用 --resources auto 重探。"
        )
    if prows is not None:
        print("== 按玩家号 (权威链直读, 玩家号=大厅号) ==")
        for line in prows:
            print("  " + line)
        if res is None:
            print("  未定位到资源结构; 确认金币/木材数值没变后重试")
    if owned_units is not None:
        print(f"== 玩家单位 (全槽位, 共{len(owned_units)}个) ==")
        for u in owned_units:
            print(
                f"  P{u['owner']} {u['unit']} [{u['code']}] @ ({format_number(u['x'])}, {format_number(u['y'])})"
            )
    if rep.get("unit_matches"):
        for u in rep["unit_matches"]:
            pos = (
                f" @ ({format_number(u['x'])}, {format_number(u['y'])})"
                if u.get("x") is not None
                else ""
            )
            print(f"匹配单位: {u['unit']} [{u['code']}]{pos}")
            for it in u["items"]:
                print(f"  槽{it['slot']}: {it['name']} [{it['code']}]")
    elif rep.get("strategy_used") == "handle" and rep.get("selected_unit"):
        sel = rep["selected_unit"]
        pos = (
            f" @ ({format_number(sel['x'])}, {format_number(sel['y'])})"
            if sel.get("x") is not None
            else ""
        )
        owner_known = sel.get("addr") is not None and any(
            u.get("addr") == sel["addr"] for u in owned_units or []
        )
        label = "当前选中" if owner_known else "当前选中(归属未知)"
        print(f"{label}: {sel['unit']} [{sel['code']}]{pos}")
        for it in sel["items"]:
            print(f"  槽{it['slot']}: {it['name']} [{it['code']}]")
        if sel.get("x") is not None:
            print(
                f"坐标反查模板：near {format_number(sel['x'])} {format_number(sel['y'])}"
            )
        others = [u for u in rep.get("units", []) if u != sel]
        if others:
            print("其余带物品单位:")
            for u in others:
                names_txt = "、".join(f"{i['name']}" for i in u["items"])
                upos = (
                    f" @ ({format_number(u['x'])}, {format_number(u['y'])})"
                    if u.get("x") is not None
                    else ""
                )
                print(f"  {u['unit']} [{u['code']}]{upos}: {names_txt}")
    all_rows = rep.get("all_units")
    if all_rows:
        combo: dict[tuple[int, str], int] = {}
        names: dict[tuple[int, str], str] = {}
        for u in all_rows:
            key = (u["owner"], u["code"])
            combo[key] = combo.get(key, 0) + 1
            names[key] = u["unit"]
        print(f"== 全部单位 ({len(all_rows)}个, 按 所有者+四码 聚合) ==")
        for (o2, c2), n2 in sorted(combo.items()):
            print(f"  P{o2} {names[(o2, c2)]} [{c2}] ×{n2}")
    if all_rows:
        first_pos = next((u for u in all_rows if u.get("x") is not None), None)
        if first_pos is not None:
            print(
                f"坐标反查模板：near {format_number(first_pos['x'])} {format_number(first_pos['y'])}"
            )
    locate_cmd = campaign_locate_command(args.pack, rep)
    if locate_cmd:
        print("== 战役定位 (若当前为 .w3n 战役, 直接复制本行定位任务关) ==")
        print("  " + locate_cmd)
    print(json.dumps(rep, ensure_ascii=False, indent=1, default=str))
    if rep["slots"]:
        return 0
    if rep["strategy_used"] == "handle" and (
        rep.get("selected_unit") is not None or rep.get("unit_matches")
    ):
        return 0  # A confirmed empty inventory is a successful read.
    if args.players and (
        owned_units is not None or rep.get("owner_counts") is not None
    ):
        return 0
    if args.all_units and rep.get("all_units") is not None:
        return 0
    if args.resources and rep.get("resources") is not None:
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
