# -*- coding: utf-8 -*-
"""运行中游戏内存的对象表全量导出 (live --dump-objects)。

地图文件被平台壳加密 (如 KK 平台 CAME 伪装 MPQ 头) 时静态解析不可用,
但游戏加载完成后整张解密对象表以 SLK 派生文本驻留进程内存:
块头形如 ``\\n\\r\\n[n00M\\x00`` (区域首个块可为 ``\\r\\n[四码\\x00``),
字段形如 ``\\n字段键\\x00值\\x00`` 依次排列 (多级值内层 \\x00 分隔)。

本模块对只读内存快照做块切分与字段解析, 落盘为知识包兼容 TSV
(对象ID/物品.tsv、对象ID/单位.tsv、对象字段.tsv 等), 之后可直接用
``main.py pack-query <目录> ...`` 查询——货架(Sellitems)、价格(igol)、
描述等字段与静态导出的知识包同构复用。

边界: 全程 ReadProcessMemory 只读; 不注入、不写游戏内存、不解密壳算法——
读的是游戏自己解密后驻留的明文。分类按四码首字母推断 (无法从内存块
拿到基础ID列, 该列留空并在来源说明中注明)。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import os
import re
import time

from .presentation_safety import tsv_cell
from dataclasses import dataclass

__all__ = (
    "LiveObjectDumpResult",
    "category_of",
    "dump_live_objects",
    "extract_affix_definitions",
    "extract_registered_records",
    "parse_slk_blocks",
    "write_object_pack",
)

# 区域扫描上限: war3 x86 单区域不会超过 256MB; 静态 snapshot() 的 32MB 上限
# 会整区跳过大区域导致对象表丢失, 这里放宽 (满量纪律: 有多少收多少)。
_MAX_REGION_BYTES = 0x10000000

# 块头: \n\r\n[四码]\x00 (表首块可为区域开头 \r\n[四码]\x00)
_BLOCK_HEADER = re.compile(rb"(?:\n\r\n|\A\r\n)\[([A-Za-z0-9@]{4})\x00")
# 字段: \n<键>\x00<值>\x00 — 值不跨行; 多级值内层 \x00 由值段容纳
_FIELD = re.compile(rb"\n([^\n\x00]{1,64})\x00([^\n]*?)\x00(?=\n|$)")

# ---------------------------------------------------------------------------
# Lua 数据层 (云消息/词缀表) — 模式驱动, 无地图特定词表。
#
# Lua 架构地图把运行时配置 (装备词条/掉落池/商店) 以 JSON 云消息与 Lua
# 常量池驻留内存。两类通用结构可无词表提取:
#   A) JSON 云消息: {"page":..,"info":"{\"name\":\"<消息名>\",\"params\":[..]}"}
#      —— 按「消息名」聚合去重; 消息名本身也是从内存收集的, 不硬编码。
#   B) 词缀/词条定义: 「XX：提供（LV*N）YYY」/「XX：提供（LV*N）的YYY」形态的
#      公式化描述行 —— 倍率与属性名从原文捕获, 不猜。

_JSON_MSG = re.compile(rb'\{"page"[^\x00]{0,4000}?(?:\x00|\Z)')
_AFFIX_PATTERN = re.compile(
    "([\u4e00-\u9fff]{1,4})：提供\\|cff00ff00（LV\\*([\\d.]+)）\\|r(?:点|的)?([\\u4e00-\\u9fff/%/]*)"
)

# 四码首字母 → 知识包分类。I/A/B/H/S/R/T 是稳定约定; 其余前缀 (含
# 小写种族单位 h/o/e/n/u、大写自定义 HENOU 变体、以及 L/Y/F/V/D 等
# 自选前缀) 实测都是单位/物品体系里的单位 → 归「单位」并在来源中注明推断。
_CATEGORY_BY_PREFIX = {
    "I": "物品",
    "A": "技能",
    "B": "增益",
    "H": "英雄",
    "S": "科技",
    "R": "科技",
    "T": "道具技能",
}

_OBJECT_ID_HEADER = "分类\tID\t10进制\t基础ID\t名称\t自定义\t说明"
_FIELD_HEADER = "分类\tID\t名称\t字段键\t字段名\t值\t来源"


@dataclass(frozen=True, slots=True)
class LiveObjectDumpResult:
    """一次内存对象表导出的结果摘要。"""

    pid: int
    regions: int
    scanned_mb: int
    objects: int
    duplicates: int
    categories: dict[str, int]
    out_dir: str
    files: int
    notes: tuple[str, ...] = ()


def category_of(code: str) -> str:
    """按四码首字母推断知识包分类; 其余归「单位」(实测含自选前缀单位)。"""
    first = code[:1]
    if first.islower():
        # 小写前缀是原版种族单位体系 (h/o/e/n/u), 一律单位
        return "单位"
    return _CATEGORY_BY_PREFIX.get(first, "单位")


def parse_slk_blocks(
    regions: list[tuple[int, bytes]],
) -> tuple[dict[str, dict[str, str]], int]:
    """从内存区域列表切分 SLK 对象块 → (四码→字段字典, 重复块数)。

    同一张表在内存常有多份拷贝; 首份为准, 其余计重复。区域边界把块
    截断时, 该块在下一区域无块头会缺失——但同名表多拷贝使实际丢失
    概率极低, 且有重复计数旁证。
    """
    blocks: dict[str, dict[str, str]] = {}
    duplicates = 0
    for _base, data in regions:
        starts = list(_BLOCK_HEADER.finditer(data))
        if not starts:
            continue
        for index, match in enumerate(starts):
            code = match.group(1).decode("ascii")
            end = starts[index + 1].start() if index + 1 < len(starts) else len(data)
            if code in blocks:
                duplicates += 1
                continue
            blocks[code] = _parse_fields(data[match.end() : end])
    return blocks, duplicates


def _parse_fields(body: bytes) -> dict[str, str]:
    fields: dict[str, str] = {}
    for match in _FIELD.finditer(body):
        key = match.group(1).decode("ascii", "replace")
        if key in fields:
            continue
        raw = match.group(2)
        value = raw.replace(b"\x00", b" | ").decode("utf-8", "replace").strip()
        fields[key] = value
    return fields


def extract_registered_records(
    regions: list[tuple[int, bytes]],
) -> dict[str, dict[str, list[object]]]:
    """收集内存中全部 JSON 云消息记录, 按消息名聚合去重 (无词表)。

    Lua 架构地图用 ``{"page":..,"info":"{\"name\":\"<名>\",\"params\":[..]}"}``
    云消息同步运行时配置 (如装备词条注册)。同一消息会因多拷贝/重发重复;
    以完整 JSON 文本哈希去重。消息名不做硬编码——收到什么名就归什么名。
    解析失败的片段跳过 (fail-open), 不中断全量收集。
    """
    by_name: dict[str, dict[str, list[object]]] = {}
    seen_texts: set[bytes] = set()
    for _base, data in regions:
        for match in _JSON_MSG.finditer(data):
            raw = match.group(0).rstrip(b"\x00")
            if raw in seen_texts:
                continue
            seen_texts.add(raw)
            try:
                outer = json.loads(raw.decode("utf-8", "replace"))
                info = json.loads(outer.get("info", ""))
                name = str(info.get("name", ""))
                if not name:
                    continue
                params = info.get("params")
                if not isinstance(params, list) or not params:
                    continue
            except ValueError, TypeError, KeyError:
                continue
            bucket = by_name.setdefault(name, {"records": [], "count": []})  # type: ignore[assignment]
            # 每条记录的完整 params 列表; 同名不同 params 都保留 (不同实例)
            key = json.dumps(params, ensure_ascii=False, sort_keys=True)
            count_list = bucket["count"]
            assert isinstance(count_list, list)
            if key in count_list:
                continue
            count_list.append(key)
            records = bucket["records"]
            assert isinstance(records, list)
            records.append(params)
    for bucket in by_name.values():
        bucket.pop("count")
    return by_name


def extract_affix_definitions(
    regions: list[tuple[int, bytes]],
) -> dict[str, dict[str, str]]:
    """收集「词缀名：提供（LV*倍率）属性」公式定义 (无词表, 模式匹配)。

    Lua 架构地图的装备词条系统在内存常量池里带公式化说明文本。
    UTF-8 词名必须按字符对齐匹配, bytes 正则的字节计数会跨字错位——
    因此先按 \x00 切片、整体尝试 utf-8 解码后再用 str 模式匹配。
    同名词条取首次捕获 (多拷贝同文); 返回 名→{multiplier, stat}。
    解码/匹配失败的片段跳过 (fail-open)。
    """
    defs: dict[str, dict[str, str]] = {}
    # 直接在 bytes 上找「词名前边界」: 词名以 UTF-8 汉字三字节组开头。
    # 用 (?:^|[^\x80-\xbf]) 锚定三字节组首, 避免逐字节 probe 的 O(n²)。
    lead = re.compile(
        rb"(?:\A|[^\x80-\xbf])(([\xe4-\xe9][\x80-\xbf]{2}){1,4})"
        + "：提供".encode("utf-8")
    )
    for _base, data in regions:
        for match in lead.finditer(data):
            name_bytes = match.group(1)
            tail_start = match.end()
            tail_end = data.find(b"\x00", tail_start)
            tail = data[tail_start : tail_end if tail_end >= 0 else tail_start + 200]
            try:
                tail_text = tail.decode("utf-8")
            except UnicodeDecodeError:
                continue
            m2 = re.search(
                "\\|cff00ff00（LV\\*([\\d.]+)）\\|r(?:点|的)?([\\u4e00-\\u9fff/%/]*)",
                tail_text,
            )
            if not m2:
                continue
            try:
                name = name_bytes.decode("utf-8")
            except UnicodeDecodeError:
                continue
            if name not in defs:
                defs[name] = {
                    "multiplier": m2.group(1),
                    "stat": m2.group(2).strip(),
                }
    return defs


def _description(fields: dict[str, str]) -> str:
    """说明列: Ubertip(提示) > Description(描述) > Tip(建造/雇佣提示)。"""
    for key in ("Ubertip", "Description", "Tip"):
        value = fields.get(key, "")
        if value:
            return value
    return ""


def write_object_pack(
    blocks: dict[str, dict[str, str]],
    out_dir: str,
    *,
    provenance: dict[str, object] | None = None,
) -> int:
    """把解析出的对象块写成知识包兼容 TSV; 返回写入文件数。

    产出: 对象ID/<分类>.tsv (load_items/load_units 直接可读)、
    对象字段.tsv (load_shop_stocks/load_item_gold_overrides 直接可读)、
    对象来源.txt (证据与边界说明)。
    """
    os.makedirs(out_dir, exist_ok=True)
    id_dir = os.path.join(out_dir, "对象ID")
    os.makedirs(id_dir, exist_ok=True)

    categories: dict[str, list[str]] = {}
    for code in sorted(blocks):
        categories.setdefault(category_of(code), []).append(code)

    files = 0
    field_rows: list[str] = [_FIELD_HEADER]
    for category, codes in sorted(categories.items()):
        rows = [_OBJECT_ID_HEADER]
        for code in codes:
            fields = blocks[code]
            name = fields.get("Name") or fields.get("Tip") or code
            decimal = int.from_bytes(code.encode("latin-1", "replace"), "big")
            rows.append(
                "\t".join(
                    (
                        tsv_cell(category),
                        tsv_cell(code),
                        str(decimal),
                        "",  # 基础ID: 内存文本块不携带, 见对象来源.txt
                        tsv_cell(name),
                        "是",
                        tsv_cell(_description(fields)),
                    )
                )
            )
            for key, value in sorted(fields.items()):
                field_rows.append(
                    "\t".join(
                        (
                            tsv_cell(category),
                            tsv_cell(code),
                            tsv_cell(name),
                            tsv_cell(key),
                            tsv_cell(key),
                            tsv_cell(value),
                            "内存对象表",
                        )
                    )
                )
        path = os.path.join(id_dir, f"{category}.tsv")
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write("\n".join(rows) + "\n")
        files += 1

    with open(
        os.path.join(out_dir, "对象字段.tsv"), "w", encoding="utf-8", newline=""
    ) as handle:
        handle.write("\n".join(field_rows) + "\n")
    files += 1

    notes = dict(provenance or {})
    notes.setdefault(
        "边界",
        "ReadProcessMemory 只读快照; 分类按四码首字母推断; "
        "基础ID列与数值SLK字段 (C;X;Y;K 单元格) 不在文本块内, 本版不导出",
    )
    with open(os.path.join(out_dir, "对象来源.txt"), "w", encoding="utf-8") as handle:
        for key, value in notes.items():
            handle.write(f"{key}: {value}\n")
    files += 1
    return files


def _snapshot_regions(
    handle: int, max_addr: int
) -> tuple[list[tuple[int, bytes]], int]:
    """VirtualQueryEx + ReadProcessMemory 全量区域读取 (上限 _MAX_REGION_BYTES)。"""
    k32 = ctypes.WinDLL("kernel32")

    class _MBI(ctypes.Structure):
        _fields_ = [
            ("Base", ctypes.c_void_p),
            ("AllocationBase", ctypes.c_void_p),
            ("AllocationProtect", wt.DWORD),
            ("RegionSize", ctypes.c_size_t),
            ("State", wt.DWORD),
            ("Protect", wt.DWORD),
            ("Type", wt.DWORD),
        ]

    regions: list[tuple[int, bytes]] = []
    total = 0
    addr = 0x10000
    mbi = _MBI()
    while addr < max_addr:
        if not k32.VirtualQueryEx(
            handle, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)
        ):
            break
        rs = mbi.RegionSize or 0x1000
        if (
            mbi.State == 0x1000
            and mbi.Protect in (2, 4, 5, 0x20, 0x40, 0x80)
            and rs <= _MAX_REGION_BYTES
        ):
            buf = ctypes.create_string_buffer(rs)
            got = ctypes.c_size_t()
            if (
                k32.ReadProcessMemory(
                    handle, ctypes.c_void_p(mbi.Base or 0), buf, rs, ctypes.byref(got)
                )
                and got.value
            ):
                regions.append((mbi.Base or 0, buf.raw[: got.value]))
                total += got.value
        addr = (mbi.Base or 0) + rs
    return regions, total


def _write_registered_data_tsv(
    by_name: dict[str, dict[str, list[object]]], out_dir: str
) -> int:
    """云消息注册数据 → 注册数据.tsv (消息名, 序号, 记录JSON)。

    记录以完整 JSON 列形式落盘 (无损); 消费方按需解析字段。
    """
    if not by_name:
        return 0
    path = os.path.join(out_dir, "注册数据.tsv")
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write("消息名\t序号\t记录JSON\n")
        for name in sorted(by_name):
            for index, params in enumerate(by_name[name]["records"]):
                handle.write(
                    "\t".join(
                        (
                            tsv_cell(name),
                            str(index),
                            tsv_cell(json.dumps(params, ensure_ascii=False)),
                        )
                    )
                    + "\n"
                )
    return 1


def _write_affixes_tsv(defs: dict[str, dict[str, str]], out_dir: str) -> int:
    """词缀公式定义 → 词缀表.tsv (词缀名, 倍率, 属性)。"""
    if not defs:
        return 0
    path = os.path.join(out_dir, "词缀表.tsv")
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write("词缀名\t倍率\t属性\n")
        for name in sorted(defs):
            handle.write(
                "\t".join(
                    (
                        tsv_cell(name),
                        tsv_cell(defs[name]["multiplier"]),
                        tsv_cell(defs[name]["stat"]),
                    )
                )
                + "\n"
            )
    return 1


def dump_live_objects(
    out_dir: str,
    pid: int | None = None,
    verbose: bool = True,
) -> LiveObjectDumpResult:
    """对运行中的 war3 做只读内存快照并全量导出对象表。

    返回摘要; 进程缺失/打开失败时 notes 说明原因并返回空结果 (退出码
    由调用方按 objects==0 判定)。
    """
    from .live_inventory import (
        detect_version,
        find_war3_pids,
        mem_setup,
        open_process,
    )

    notes: list[str] = []
    mem_setup()
    pids = find_war3_pids()
    if not pids:
        return LiveObjectDumpResult(0, 0, 0, 0, 0, {}, out_dir, 0, ("war3 未运行",))
    if pid is not None:
        if pid not in pids:
            return LiveObjectDumpResult(
                pid,
                0,
                0,
                0,
                0,
                {},
                out_dir,
                0,
                (f"--pid {pid} 不在运行中的 war3 进程列表 {pids}",),
            )
        chosen = pid
    elif len(pids) > 1:
        return LiveObjectDumpResult(
            0,
            0,
            0,
            0,
            0,
            {},
            out_dir,
            0,
            (f"检测到多个 war3 进程 {pids} — 不猜, 用 --pid <PID> 显式选择",),
        )
    else:
        chosen = pids[0]

    handle = open_process(chosen)
    if not handle:
        return LiveObjectDumpResult(
            chosen, 0, 0, 0, 0, {}, out_dir, 0, ("OpenProcess 失败 (需管理员)",)
        )
    try:
        version = detect_version(handle)
        max_addr = 0x7FFFFFFEFFFF if version["arch"] == "x64" else 0x7FFF0000
        regions, total = _snapshot_regions(handle, max_addr)
    finally:
        ctypes.WinDLL("kernel32").CloseHandle(handle)

    blocks, duplicates = parse_slk_blocks(regions)
    categories: dict[str, int] = {}
    for code in blocks:
        cat = category_of(code)
        categories[cat] = categories.get(cat, 0) + 1
    # Lua 数据层 (云消息注册数据 + 词缀公式) — 无词表, 收到什么导什么
    registered = extract_registered_records(regions)
    affixes = extract_affix_definitions(regions)
    files = write_object_pack(
        blocks,
        out_dir,
        provenance={
            "来源": "live --dump-objects (运行中游戏内存 SLK 对象表, 只读)",
            "pid": chosen,
            "游戏版本": version.get("version"),
            "导出时间": time.strftime("%Y-%m-%d %H:%M:%S"),
            "扫描区域": f"{len(regions)} 区 / {total // 1048576}MB",
            "对象数": len(blocks),
            "重复块跳过": duplicates,
            "分类": json.dumps(categories, ensure_ascii=False),
        },
    )
    files += _write_registered_data_tsv(registered, out_dir)
    files += _write_affixes_tsv(affixes, out_dir)
    if verbose:
        print(
            f"对象表导出: {len(blocks)} 个对象 "
            f"({len(regions)} 区 {total // 1048576}MB, 重复跳过 {duplicates})"
        )
        for cat, count in sorted(categories.items()):
            print(f"  {cat}: {count}")
        if registered:
            total_records = sum(len(b["records"]) for b in registered.values())
            print(f"注册数据: {total_records} 条 / {len(registered)} 种消息名")
        if affixes:
            print(f"词缀公式: {len(affixes)} 条")
        print(f"知识包就绪 -> {out_dir} ({files} 个文件)")
        print(
            f'查询示例: uv run python -X utf8 main.py pack-query "{out_dir}" item <名称或四码>'
        )
    return LiveObjectDumpResult(
        chosen,
        len(regions),
        total // 1048576,
        len(blocks),
        duplicates,
        categories,
        out_dir,
        files,
        tuple(notes),
    )
