# -*- coding: utf-8 -*-
"""pack-query 子命令：一次进程内查询地图知识包（物品/配方/坐标/掉落/任务/全文）。

用法：
    uv run main.py pack-query <资料包目录> <子命令> <查询词> [--limit N] (默认全量输出; --limit N 为显式缩减)

子命令：
    item   <名字|四码>   物品属性（金币价; 装备效果取自携带技能属性字段; 真实提示文本优先于继承模板描述）
    recipe <名字|四码>   相关合成配方（作为产物或材料，自动去重）
    where  <名字|四码>   单位/地面物品/可破坏物的放置坐标
    drop   <名字|四码>   获取途径（掉落/商店/触发奖励; 无记录时回落文案级配方/来源线索）
    quest  <关键词>     任务注册文本与剧情对话
    text   <关键词>     全包 TSV 全行搜索 (--limit N 显式缩减)
    price  <名字|四码>   金币价（igol 地图价优先, 基础ID继承）
    tech   <名字|四码>   科技卡（最大等级/每级金木费用/效果/前置, 自定义字段优先基础继承）
    cmd    <指令文字>    聊天指令效果链（注册->触发器->条件+动作函数体节选, 免手搓脚本）
    refs   <四码|名>     逐对象分类引用与来源；零消耗只说明当前可读索引未发现材料引用

设计动机：避免为每次查询写一次性脚本/起多个进程（文件变更通知会拖垮资源
管理器外壳）；全部查询在单次进程内完成，默认满量输出，可显式 --limit 缩减。
"""

from __future__ import annotations

import bisect
import hashlib
import json
import time
import os
import csv
import re
import sys
import threading
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field as dataclass_field
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, cast

from .cli_output import configure_cli_output
from .csv_fields import full_csv_fields
from .pack_query_options import PackQueryCliOptions
from .pack_query_placement_index import IndexedPlacements, indexed_placements
from .presentation_safety import single_line_text
from .static_numbers import format_number
from .script_lexing import literal_string_value, script_views
from .script_trigger_bindings import CallbackReference, script_trigger_bindings
from .script_function_graph import format_function_graph, script_functions
from .script_trigger_acquisition import (
    format_trigger_acquisitions,
    trigger_acquisitions,
)
from .script_sources import (
    AnalysisScriptSource,
    analysis_script_text,
    script_language,
    script_type_from_report,
)

if TYPE_CHECKING:
    from .pack_query_execution import PackQueryResult
    from .pack_query_spatial import SpatialQueryResult

__all__ = (
    "PackQueryCliOptionError",
    "PackQueryCliOptions",
    "parse_pack_query_cli_options",
    "execute_pack_query",
    "run_pack_query_cli",
)

_COMMANDS = (
    "again",
    "item",
    "recipe",
    "where",
    "drop",
    "quest",
    "text",
    "price",
    "shop",
    "tech",
    "near",
    "cmd",
    "refs",
    "locate",
    "affixes",
    "registered",
    "search",
    "diff",
    "list",
    "doc",
    "buffs",
    "export",
    "stats",
    "synth",
    "skills",
    "units",
    "heroes",
)
_COLOR_RE = re.compile(r"\|c[0-9A-Fa-f]{8}|\|r")


def _clean(text: str) -> str:
    return _COLOR_RE.sub("", text).replace("|n", " ")


_ROWS_CACHE: dict[tuple[str, str], tuple[tuple[int, int, str], list[list[str]]]] = {}
_TABLE_READ_LOCK = threading.RLock()
_QUERY_ROWS: dict[tuple[str, str], list[list[str]]] | None = None
_QUERY_SCRIPTS: dict[str, str | None] | None = None
_QUERY_SCRIPT_SOURCES: dict[str, tuple[tuple[str, str], ...]] | None = None
_QUERY_FILES: set[tuple[str, str]] | None = None

# 本进程内遇到的 OS 级锁死表 (杀软隔离/ACL 损坏): (pack_dir, rel) — 查询出口统一披露
_LOCKED_FILES: set[tuple[str, str]] = set()


def _iter_tsv_lines(path: Path):
    """带瞬态重试与锁死披露的行迭代 (脚本索引类 TSV 共用防线)。"""
    key = (str(path.parent), path.name)
    if _QUERY_FILES is not None:
        _QUERY_FILES.add(key)
    for _attempt in range(1 if key in _LOCKED_FILES else 3):
        try:
            with path.open(encoding="utf-8", errors="replace") as handle:
                lines = list(handle)
            _LOCKED_FILES.discard(key)
            yield from lines
            return
        except OSError:
            time.sleep(0.05)
    _LOCKED_FILES.add(key)


def _read_rows(pack_dir: Path, rel: str) -> list[list[str]]:
    """Read a stable whole-table snapshot; validate every byte on cache hits."""
    with _TABLE_READ_LOCK:
        key = (str(pack_dir), rel)
        if _QUERY_FILES is not None:
            _QUERY_FILES.add(key)
        if _QUERY_ROWS is not None and key in _QUERY_ROWS:
            return _QUERY_ROWS[key]
        rows = _read_rows_locked(pack_dir, rel)
        if _QUERY_ROWS is not None:
            _QUERY_ROWS[key] = rows
        return rows


def _read_rows_locked(pack_dir: Path, rel: str) -> list[list[str]]:
    path = pack_dir / rel
    cache_key = (str(pack_dir), rel)
    # Previously locked files get a cheap new attempt so a transient ACL or
    # antivirus failure never poisons the rest of the GUI process's lifetime.
    attempts = 1 if cache_key in _LOCKED_FILES else 3
    for attempt in range(attempts):
        try:
            with path.open("rb") as handle:
                before = os.fstat(handle.fileno())
                digest = hashlib.file_digest(handle, "sha256").hexdigest()
                after = os.fstat(handle.fileno())
            if _table_identity(before) != _table_identity(after) or _table_identity(
                after
            ) != _table_identity(path.stat()):
                continue
            fingerprint = (after.st_mtime_ns, after.st_size, digest)
            cached = _ROWS_CACHE.get(cache_key)
            if cached is not None and cached[0] == fingerprint:
                _LOCKED_FILES.discard(cache_key)
                return cached[1]
            with full_csv_fields():
                with path.open(encoding="utf-8", newline="") as handle:
                    rows = list(csv.reader(handle, delimiter="\t"))
            if _table_identity(after) != _table_identity(path.stat()):
                continue
            _ROWS_CACHE[cache_key] = (fingerprint, rows)
            _LOCKED_FILES.discard(cache_key)
            return rows
        except FileNotFoundError:
            _ROWS_CACHE.pop(cache_key, None)
            _LOCKED_FILES.discard(cache_key)
            return []
        except OSError, UnicodeError, csv.Error:
            if attempt + 1 < attempts:
                time.sleep(0.05)
    _ROWS_CACHE.pop(cache_key, None)
    _LOCKED_FILES.add(cache_key)
    return []


def _table_identity(stat: os.stat_result) -> tuple[int, int, int, int]:
    # Windows stat/fstat disagree on st_ctime (creation versus change time).
    # Full-content hashes provide invalidation even for preserved mtime/size.
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)


def load_items(pack_dir: Path) -> dict[str, tuple[str, str]]:
    """物品四码 -> (去色名称, 描述)。"""
    out: dict[str, tuple[str, str]] = {}
    for r in _read_rows(pack_dir, "对象ID/物品.tsv"):
        if len(r) > 4 and len(r[1]) == 4:
            out[r[1]] = (_clean(r[4]), _clean(r[6]) if len(r) > 6 else "")
    return out


def load_units(pack_dir: Path) -> dict[str, str]:
    """单位四码 -> 名称。"""
    out: dict[str, str] = {}
    for r in _read_rows(pack_dir, "对象ID/单位.tsv"):
        if len(r) > 4 and len(r[1]) == 4:
            out[r[1]] = _clean(r[4])
    return out


def load_destructables(pack_dir: Path) -> dict[str, str]:
    """可破坏物四码 -> 名称。"""
    return {
        row[1]: _clean(row[4])
        for row in _read_rows(pack_dir, "对象ID/可破坏物.tsv")
        if len(row) > 4 and len(row[1]) == 4
    }


def load_item_bases(pack_dir: Path) -> dict[str, str]:
    """物品四码 -> 基础对象四码（对象ID/物品.tsv 第4列）。"""
    out: dict[str, str] = {}
    for r in _read_rows(pack_dir, "对象ID/物品.tsv"):
        if len(r) > 4 and len(r[1]) == 4 and len(r[3]) == 4:
            out[r[1]] = r[3].lower()
    return out


def load_item_gold_overrides(pack_dir: Path) -> dict[str, str]:
    """地图内逐物品金币覆写：对象字段.tsv 中的金币字段行。

    字段键兼容 igol（w3u 对象导出）与 goldcost（SLK 数据导出，
    如按 SLK 导出物件的系列地图），两者同为物品金币成本字段。
    """
    out: dict[str, str] = {}
    for r in _read_rows(pack_dir, "对象字段.tsv"):
        if len(r) <= 5:
            continue
        if (
            len(r) > 5
            and r[0] == "物品"
            and len(r[1]) == 4
            and r[3].lower() in ("igol", "goldcost")
        ):
            out[r[1]] = r[5].strip()
    return out


def load_shop_stocks(pack_dir: Path) -> list[tuple[str, str, list[str]]]:
    """商店出售清单：[(商店四码, 商店名, [物品四码])]，来自出售物品字段。

    字段名兼容 usei 与 Sellitems（不同地图导出对同一"售出的物品"字段的
    原始码写法不同）。值形如 "I002, I001" 或 "敏捷之书+2(tst2), 银锭(I008)"——
    括号里才是物品四码，裸 token 视为四码本身。

    地图未改过货架的原版商店（如直接摆放的 ngme 地精商店）只有
    base:Sellitems 继承行——继承货架在该单位身上真实生效，同样列出；
    同一单位自定义行优先，有自定义货架时忽略其继承行。
    """
    custom: list[tuple[str, str, list[str]]] = []
    inherited: list[tuple[str, str, list[str]]] = []
    custom_units: set[str] = set()
    for r in _read_rows(pack_dir, "对象字段.tsv"):
        if len(r) <= 5:
            continue
        if len(r) > 5 and r[3].removeprefix("base:") not in ("usei", "Sellitems"):
            continue
        codes = []
        for raw_token in r[5].split(","):
            token = raw_token.strip()
            m = re.search(r"\(([A-Za-z0-9]{4})\)", token)
            if m:
                codes.append(m.group(1))
            elif len(token) == 4:
                codes.append(token)
        if not codes:
            continue
        if r[3].startswith("base:"):
            inherited.append((r[1], _clean(r[2]), codes))
        else:
            custom_units.add(r[1])
            custom.append((r[1], _clean(r[2]), codes))
    return custom + [row for row in inherited if row[0] not in custom_units]


def load_item_tooltips(pack_dir: Path) -> dict[str, str]:
    """物品四码 -> 地图内真实提示文本（自定义 ides/utub 字段，ides 优先）。

    对象ID/物品.tsv 的描述列多为按基础ID继承的模板文本（如
    “装备时英雄的法力恢复速度提高<AIrm,DataA1,%>%”），同名自定义物品
    共用时会互相误导；只有地图自己在 w3t 里写的 ides(描述)/
    utub(提示文本) 才是该物品在地图上的真实效果说明。值可能带
    电子表格转义前缀单引号，展示前剥离。
    """
    best: dict[str, tuple[int, str]] = {}
    for r in _read_rows(pack_dir, "对象字段.tsv"):
        if len(r) <= 5:
            continue
        if (
            len(r) > 5
            and r[0] == "物品"
            and len(r[1]) == 4
            and r[3] in ("ides", "utub")
        ):
            prio = 0 if r[3] == "ides" else 1
            cur = best.get(r[1])
            if cur is None or prio < cur[0]:
                text = _clean(r[5].lstrip("'"))
                if text:
                    best[r[1]] = (prio, text)
    return {code: text for code, (_prio, text) in best.items()}


_ITEM_STAT_FIELDS = {
    "Istr": "力量",
    "Iagi": "敏捷",
    "Iint": "智力",
}
# 二进制导出的等级字段带冒号（Istr:1），SLK 导出直接拼数字（Istr1）。
_ITEM_STAT_FIELD_RE = re.compile(r"(Istr|Iagi|Iint)(?::\d+|\d+)?\Z")


def load_item_equipped_effects(pack_dir: Path) -> dict[str, list[str]]:
    """物品四码 -> 装备真实效果摘要（如 ["+11 力量"]）。

    物品的实际加成由 iabi(携带技能) 指向的技能决定；提示文本可能是
    按基础ID继承的模板（占位符未填、与真实效果完全不符）。只解读
    地图自定义行的属性奖励字段（Istr/Iagi/Iint，中文标签
    “力量/敏捷/智力奖励”，来源 war3map.*），等级后缀兼容二进制
    （Istr:1）与 SLK（Istr1）两种导出形式；继承行的字段码是英文
    原始码（base:DataC1 等），其数值列在不同技能家族指向不同属性，
    不做解读——宁缺毋滥，漏报优于按错列猜数。
    """
    equipped: dict[str, list[str]] = {}
    stat_rows: dict[str, dict[str, str]] = {}
    for r in _read_rows(pack_dir, "对象字段.tsv"):
        if len(r) <= 5:
            continue
        if len(r) < 7 or len(r[1]) != 4:
            continue
        if r[0] == "物品" and r[3] == "iabi":
            codes = [c.strip() for c in r[5].split(",") if len(c.strip()) == 4]
            if codes:
                equipped.setdefault(r[1], []).extend(codes)
        elif r[0] == "技能":
            stat = _ITEM_STAT_FIELD_RE.fullmatch(r[3])
            if stat:
                stat_rows.setdefault(r[1], {}).setdefault(stat.group(1), r[5])
    effects: dict[str, list[str]] = {}
    for item, abilities in equipped.items():
        parts: list[str] = []
        for ab in abilities:
            for field, label in _ITEM_STAT_FIELDS.items():
                val = stat_rows.get(ab, {}).get(field)
                if val and val not in ("-", "'"):
                    parts.append("+" + val + " " + label)
        if parts:
            effects[item] = parts
    return effects


_base_price_cache: dict[str, str] | None = None


def _base_prices() -> dict[str, str]:
    """基础物品四码(小写) -> 金币价（生成表 base_objects.BASE_OBJECTS）。"""
    global _base_price_cache
    if _base_price_cache is None:
        from .base_objects import BASE_OBJECTS

        prices: dict[str, str] = {}
        for code, entry in BASE_OBJECTS.items():
            if entry[0] != "物品":
                continue
            for key, val in entry[1]:
                if key == "金币":
                    prices[code.lower()] = val
                    break
        _base_price_cache = prices
    return _base_price_cache


_tech_base_fields_cache: dict[str, dict[str, str]] | None = None


def _tech_base_fields() -> dict[str, dict[str, str]]:
    """基础科技四码(小写) -> {字段名: 值}（生成表 base_objects.BASE_OBJECTS）。"""
    global _tech_base_fields_cache
    if _tech_base_fields_cache is None:
        from .base_objects import BASE_OBJECTS

        out: dict[str, dict[str, str]] = {}
        for code, entry in BASE_OBJECTS.items():
            if entry[0] != "科技":
                continue
            out[code.lower()] = dict(entry[1])
        _tech_base_fields_cache = out
    return _tech_base_fields_cache


def load_techs(pack_dir: Path) -> dict[str, tuple[str, str]]:
    """科技四码 -> (去色名称, 基础ID小写)。基础ID非四码时为空串。"""
    out: dict[str, tuple[str, str]] = {}
    for r in _read_rows(pack_dir, "对象ID/科技.tsv"):
        if len(r) > 4 and len(r[1]) == 4:
            base = r[3].lower() if len(r[3]) == 4 else ""
            out[r[1]] = (_clean(r[4]), base)
    return out


def load_tech_fields(pack_dir: Path) -> dict[str, dict[str, str]]:
    """科技四码 -> {自定义字段键: 值}（不含 base: 继承行；gub1:N/greq:N 原样保留）。"""
    out: dict[str, dict[str, str]] = {}
    for r in _read_rows(pack_dir, "对象字段.tsv"):
        if len(r) <= 5:
            continue
        if (
            len(r) > 5
            and r[0] == "科技"
            and len(r[1]) == 4
            and not r[3].startswith("base:")
        ):
            out.setdefault(r[1], {})[r[3]] = _clean(r[5].lstrip("'"))
    return out


def _bounded(seq, limit: int):
    """limit=0(默认)不限量; --limit N 为显式缩减。"""
    return seq[:limit] if limit else seq


def _truncated_note(seq, limit: int) -> str:
    """截断披露行: --limit 生效且确有截断时提示还有多少 (空串=未截断)。"""
    if limit and len(seq) > limit:
        return f"  (已达 --limit {limit}, 其余 {len(seq) - limit} 条未显示——去掉 --limit 看全量)"
    return ""


def _limit_result_blocks(blocks: list[list[str]], limit: int) -> list[str]:
    """Select actual result records while keeping their evidence together."""
    lines = [line for block in _bounded(blocks, limit) for line in block]
    note = _truncated_note(blocks, limit)
    return [*lines, *([note] if note else [])]


@dataclass
class _AcquisitionBlocks:
    """Each record counts once; supplemental evidence follows its first record."""

    records: list[list[str]] = dataclass_field(default_factory=list)
    first: dict[str, int] = dataclass_field(default_factory=dict)

    def record(self, code: str, line: str) -> None:
        self.first.setdefault(code, len(self.records))
        self.records.append([line])

    def supplement(self, code: str, lines: list[str]) -> None:
        if not lines:
            return
        if code in self.first:
            self.records[self.first[code]].extend(lines)
        else:
            self.first[code] = len(self.records)
            self.records.append(lines.copy())

    def render(self, limit: int) -> list[str]:
        return _limit_result_blocks(self.records, limit)


def _is_record_code(value: str) -> bool:
    return len(value) == 4 and all(ord(char) <= 255 for char in value)


def _query_tech(pack: Path, query: str, limit: int) -> list[str]:
    techs = load_techs(pack)
    fields = load_tech_fields(pack)
    bases = _tech_base_fields()
    lines: list[str] = []
    matches = [
        (code, name, base_id)
        for code, (name, base_id) in techs.items()
        if _match(query, code, name)
    ]
    for code, name, base_id in _bounded(matches, limit):
        f = fields.get(code, {})
        base_f = bases.get(base_id, {})

        def _num(custom_key: str, base_label: str) -> int | None:
            for v in (f.get(custom_key), base_f.get(base_label)):
                if v and v.lstrip("'") not in ("-", "_", "'"):
                    try:
                        return int(float(v))
                    except ValueError, OverflowError:
                        pass  # 非数值/占位符 — 试下一来源 (base 兑底), 最终 None=未知
            return None

        levels = _num("glvl", "最大等级")
        gold_b = _num("gglb", "基础金")
        gold_i = _num("gglm", "金增量")
        lum_b = _num("glmb", "基础木")
        lum_i = _num("glmm", "木增量")

        lines.append(
            "["
            + code
            + "] "
            + name
            + (("  (基础: " + base_id + ")") if base_id else "")
        )
        if levels:
            lines.append("  最大等级: " + str(levels))
        cost_bits = []
        if gold_b is not None:
            cost_bits.append(
                "金 " + str(gold_b) + (("+" + str(gold_i) + "/级") if gold_i else "")
            )
        if lum_b is not None:
            cost_bits.append(
                "木 " + str(lum_b) + (("+" + str(lum_i) + "/级") if lum_i else "")
            )
        if cost_bits:
            lines.append("  每级费用: " + ", ".join(cost_bits))
        if levels and levels > 1:

            def _cost(n: int) -> str:
                g = str(gold_b + (gold_i or 0) * (n - 1)) if gold_b is not None else "-"
                w = str(lum_b + (lum_i or 0) * (n - 1)) if lum_b is not None else "-"
                return "金" + g + " 木" + w

            lines.append(
                "  级费用: "
                + " | ".join(str(n) + "级 " + _cost(n) for n in range(1, levels + 1))
            )
            gsum = (
                levels * gold_b + (gold_i or 0) * levels * (levels - 1) // 2
                if gold_b is not None
                else None
            )
            wsum = (
                levels * lum_b + (lum_i or 0) * levels * (levels - 1) // 2
                if lum_b is not None
                else None
            )
            if gsum is not None or wsum is not None:
                lines.append(
                    "  满级累计: "
                    + (("金" + str(gsum) + " ") if gsum is not None else "")
                    + (("木" + str(wsum)) if wsum is not None else "")
                )
        tips = {
            int(key.removeprefix("gub1:")): value
            for key, value in f.items()
            if key.startswith("gub1:") and key.removeprefix("gub1:").isdigit()
        }
        if "gub1" in f:
            tips.setdefault(1, f["gub1"])
        for lv, text in sorted(tips.items()):
            if text:
                lines.append("  效果(" + str(lv) + "级): " + text)
        reqs = sorted((k, v) for k, v in f.items() if k.startswith("greq:"))
        if reqs:
            lines.append(
                "  前置: " + ", ".join(k.split(":", 1)[1] + "级←" + v for k, v in reqs)
            )
        lines.append("")
    if note := _truncated_note(matches, limit):
        lines.append(note)
    if lines:
        return lines
    # 未命中时给科技总量提示——「未找到」不代表本图没有科技系统
    if techs:
        return [
            "未找到科技: " + query,
            f"  （本图共 {len(techs)} 项科技; 可用 tech <名称或四码> 查询）",
        ]
    return ["未找到科技: " + query]


def _item_price(
    bases: dict[str, str], code: str, overrides: dict[str, str] | None = None
) -> str:
    """物品商店价：地图 igol 覆写优先，其次按基础ID继承，再次物品本身即基础物品。"""
    if overrides and code in overrides:
        return overrides[code]
    prices = _base_prices()
    base = bases.get(code, "")
    if base and base in prices:
        return prices[base]
    return prices.get(code.lower(), "")


def _call_argument_rows(pack: Path) -> list[tuple[list[str], str, str]]:
    """Read appended index columns by header while accepting headerless old packs."""
    rows = _read_rows(pack, "脚本调用参数索引.tsv")
    header = rows[0] if rows and rows[0][:2] == ["来源", "行号"] else []
    summary_index = header.index("摘要") if "摘要" in header else -1
    offset_index = header.index("调用偏移") if "调用偏移" in header else None
    return [
        (
            row,
            row[summary_index],
            row[offset_index]
            if offset_index is not None and offset_index < len(row)
            else "",
        )
        for row in (rows[1:] if header else rows)
        if row and (summary_index < 0 or summary_index < len(row))
    ]


def _indexed_call_identity(
    row: list[str], summary: str, offset: str
) -> tuple[str, ...]:
    if offset:
        return row[0], offset
    return (*row[:2], summary) if len(row) > 2 else tuple(row)


def _indexed_formula_arguments(rows: list[list[str]]) -> list[tuple[str, ...]]:
    """Recover multiline calls from consecutive complete argument-index rows."""
    groups: list[tuple[str, ...]] = []
    args: list[str] = []
    previous: tuple[str, ...] = ()
    for row in rows:
        key = (*row[:4], row[-1]) if len(row) >= 11 else ()
        position = (
            row[4].lstrip("0")
            if key and row[3] == "YDWENewItemsFormula" and row[4].isdigit()
            else ""
        )
        if key != previous or position != str(len(args) + 1):
            if args:
                groups.append(tuple(args))
            args = []
        previous = key
        if position == str(len(args) + 1):
            value = row[5]
            # Undo only the exporter-added spreadsheet prefix on signed numbers.
            value = (
                re.sub(r"^(\s*)'(?=[+-])", r"\1", value)
                if not value.rstrip().endswith("'")
                else value
            )
            args.append(value)
    if args:
        groups.append(tuple(args))
    return groups


def load_formulas(pack_dir: Path) -> list[tuple[str, list[tuple[str, int]]]]:
    """Read source formulas plus legacy call summaries with exact quantities."""
    from .script_recipes import formula_from_arguments, scan_formulas

    contexts = load_script_contexts(pack_dir)
    source_formulas = [
        formula
        for source, script, lua in contexts
        for formula in scan_formulas(script, source=source, lua=lua)
    ]
    # Index exports have one row per argument. A source/line/summary is one call,
    # while distinct source sites remain available even for identical formulas.
    seen: set[tuple[str, ...]] = set()
    indexed_formulas = []
    available = tuple(source for source, _script, _lua in contexts)
    declared = _pack_script_type(pack_dir)
    entries = _call_argument_rows(pack_dir)
    rows = [row for row, _summary, _offset in entries]
    structured = [
        parsed
        for args in _indexed_formula_arguments(rows)
        if (parsed := formula_from_arguments(args)) is not None
    ]
    for row, summary, offset in entries:
        if "YDWENewItemsFormula" not in summary:
            continue
        key = _indexed_call_identity(row, summary, offset)
        if key in seen:
            continue
        seen.add(key)
        source = row[0] if len(row) > 2 else ""
        indexed_formulas.extend(
            scan_formulas(
                summary,
                source=source,
                lua=script_language(
                    source, available_sources=available, declared_script_type=declared
                ),
            )
        )
    # Raw calls and their index mirrors share occurrences; neither source can
    # hide additional declarations found only in the other evidence channel.
    counts = (
        Counter((row.result, row.ingredients) for row in source_formulas)
        | Counter((row.result, row.ingredients) for row in indexed_formulas)
        | Counter(structured)
    )
    return [(result, list(pairs)) for result, pairs in counts.elements()]


def _indexed_placement_report(
    pack_dir: Path,
    contexts: tuple[AnalysisScriptSource, ...] | None = None,
) -> IndexedPlacements:
    return indexed_placements(
        load_script_contexts(pack_dir) if contexts is None else contexts,
        tuple(
            (tuple(row), summary, offset)
            for row, summary, offset in _call_argument_rows(pack_dir)
        ),
        _pack_script_type(pack_dir),
    )


def load_placements(pack_dir: Path) -> list[tuple[str, float, float, str]]:
    """原文与索引按来源身份互补；镜像调用遵守原文的绑定上下文。"""
    from .pack_query_placements import script_placements

    contexts = load_script_contexts(pack_dir)
    source_rows = [
        placement
        for source, text, lua in contexts
        for placement in script_placements(text, lua=lua)
    ]
    report = _indexed_placement_report(pack_dir, contexts)
    counts = Counter(source_rows) | Counter(report.placements)
    return list(counts.elements())


def load_placement_diagnostics(pack_dir: Path) -> list[str]:
    """Disclose every unresolved creation site and ambiguous index source."""
    from .script_placement_analysis import analyze_script_placements
    from .script_rectangle_analysis import analyze_script_rectangles

    contexts = load_script_contexts(pack_dir)
    return [
        f"  {source}:{row.line} / 偏移{row.offset}: {row.reason}\n    原文: {row.expression}"
        for source, text, lua in contexts
        for row in (
            *analyze_script_placements(text, lua=lua).diagnostics,
            *analyze_script_rectangles(text, lua=lua).diagnostics,
        )
    ] + list(_indexed_placement_report(pack_dir, contexts).diagnostics)


@dataclass(frozen=True, slots=True)
class PackQueryCliOptionError(ValueError):
    """pack-query 参数错误，message 面向命令行用户。"""

    detail: str

    def __str__(self) -> str:
        return single_line_text(self.detail)


def parse_pack_query_cli_options(argv: Sequence[str]) -> PackQueryCliOptions:
    """解析 pack-query 后的参数：<资料包目录> <子命令> <查询词> [--limit N]。

    默认 limit=0 全量输出——不敲 --limit 就拿到全部匹配; --limit N 是显式缩减。"""
    rest = list(argv)
    limit = 0
    if "--limit" in rest:
        i = rest.index("--limit")
        if i + 1 >= len(rest):
            raise PackQueryCliOptionError("--limit 需要一个数字参数")
        try:
            limit = int(rest[i + 1])
        except ValueError as exc:
            raise PackQueryCliOptionError("--limit 需要一个数字参数") from exc
        if limit < 0:
            raise PackQueryCliOptionError("--limit 必须为非负整数 (0=不限量)")
        rest = rest[:i] + rest[i + 2 :]
    as_json = "--json" in rest
    if as_json:
        rest = [x for x in rest if x != "--json"]
    near_kind = ""
    if "--kind" in rest:
        i = rest.index("--kind")
        if i + 1 >= len(rest):
            raise PackQueryCliOptionError("--kind 需要一个值: 单位/装饰/物品/脚本")
        near_kind = rest[i + 1]
        rest = rest[:i] + rest[i + 2 :]
    against = ""
    if "--against" in rest:
        i = rest.index("--against")
        if i + 1 >= len(rest):
            raise PackQueryCliOptionError("--against 需要第二个资料包目录")
        against = rest[i + 1]
        rest = rest[:i] + rest[i + 2 :]
    command = rest[1] if len(rest) > 1 else ""
    if command == "near" and len(rest) in (4, 5):
        rest = [*rest[:2], " ".join(rest[2:])]
    if (
        command
        in (
            "affixes",
            "again",
            "registered",
            "diff",
            "list",
            "buffs",
            "heroes",
            "stats",
            "synth",
            "skills",
            "units",
        )
        and len(rest) == 2
    ):
        # 这些子命令查询词可省 (全量列出)
        rest = [*rest, ""]
    if len(rest) != 3:
        raise PackQueryCliOptionError(
            "用法: pack-query <资料包目录> [--json] <"
            + ",".join(_COMMANDS)
            + "> <查询词>"
            + ("  (near 用法: near <x> <y> [radius])" if command == "near" else "")
            + (
                "  (affixes/registered/list/buffs/heroes/stats/synth/skills/units 查询词可省 = 全量列出; diff 用法: diff <旧包目录>)"
                if command in ("affixes", "registered", "diff", "list", "buffs")
                else ""
            )
        )
    pack_dir, query = rest[0], rest[2]
    if command not in _COMMANDS:
        raise PackQueryCliOptionError(
            "未知子命令: " + command + " (可选: " + ",".join(_COMMANDS) + ")"
        )
    if not query.strip() and command not in (
        "affixes",
        "again",
        "registered",
        "diff",
        "list",
        "buffs",
        "heroes",
        "stats",
        "synth",
        "skills",
        "units",
    ):
        raise PackQueryCliOptionError("查询词不能为空")
    return PackQueryCliOptions(
        pack_dir=pack_dir,
        command=command,
        query=query.strip(),
        limit=limit,
        pack_dir_b=against,
        as_json=as_json,
        near_kind=near_kind,
    )


def _match(query: str, code: str, name: str) -> bool:
    q = query.casefold()
    c = code.casefold()
    n = name.casefold()
    # 空字段不得参与匹配: name="" 时 "" in query 恒真, 空来源关系行
    # (脚本奖励行 来源ID/名称 为空) 会出现在每一个查询里 (来源 [] 噪声)
    return (bool(c) and q == c) or (bool(n) and (q in n or n in q))


def _relation_source_label(r: list[str]) -> str:
    """关系行来源展示: 有来源对象用「分类 ID」, 脚本奖励行回落证据函数/行号。

    脚本奖励行的 来源ID/名称 为空 (接收者不是来源对象), 旧版打印
    "来源 []" 与 " <-  " 尾巴; 真实出处是 r[20] 证据函数 / r[21] 行号。"""
    src = (r[5].strip() + " " + r[6].strip()).strip()
    if src:
        return src
    cols = [r[i].strip() for i in (20, 21) if i < len(r) and r[i].strip()]
    detail = " ".join(cols)
    return detail or "脚本奖励(未标来源)"


def _query_locate(pack: Path, query: str, limit: int) -> list[str]:
    """特征码交集: 多个对象码同时出现在本图时报告命中 (战役任务关识别)。

    战役工作流第④步的机械化: live 拿英雄/随从/物品四码, 用本命令扫
    脚本对象码出现索引.tsv, 「全部码都出现」的子图即候选任务关——
    容器包由 run_pack_query_cli 自动逐关分段 (== 子地图 名 ==)。"""
    del limit  # locate 满量列出全部引用数, 截断不适用
    codes = [c.strip() for c in re.split(r"[;,，；\s]+", query) if c.strip()]
    if not codes:
        return ["用法: locate <码1;码2;...> (特征码交集, 全部码都出现才算命中)"]
    rows = _read_rows(pack, "脚本对象码出现索引.tsv")
    if not rows:
        return [
            "未找到 脚本对象码出现索引.tsv（资料包未导出脚本索引——用 cli <地图> --pack 重导一次即有）"
        ]
    counts: dict[str, int] = {c.lower(): 0 for c in codes}
    for r in rows:
        if len(r) < 4:
            continue
        key = r[3].lower()
        if key in counts:
            counts[key] += 1
    missing = [c for c in codes if counts[c.lower()] == 0]
    if missing:
        lines = ["未找到: 缺少 " + "、".join(missing) + "（特征码未全部出现）"]
        # 部分命中仍有定位价值: 列出已出现码的引用数, 缩小候选范围
        for c in codes:
            if c not in missing:
                lines.append(
                    "  已命中 " + c + ": " + str(counts[c.lower()]) + " 处引用"
                )
        return lines
    lines = ["命中全部 " + str(len(codes)) + " 个特征码: " + "、".join(codes)]
    for c in codes:
        lines.append("  " + c + ": " + str(counts[c.lower()]) + " 处引用")
    return lines


def _query_item(pack: Path, query: str, limit: int) -> list[str]:
    items = load_items(pack)
    bases = load_item_bases(pack)
    overrides = load_item_gold_overrides(pack)
    tooltips = load_item_tooltips(pack)
    equipped_effects = load_item_equipped_effects(pack)
    lines = []
    matches = [
        (code, name, desc)
        for code, (name, desc) in items.items()
        if _match(query, code, name)
    ]
    for code, name, desc in _bounded(matches, limit):
        lines.append("[" + code + "] " + name)
        price = _item_price(bases, code, overrides)
        base = bases.get(code, "")
        if price:
            src = (
                "地图价" if code in overrides else ("继承基础 " + base if base else "")
            )
            lines.append("  金币: " + price + (" (" + src + ")" if src else ""))
        # 装备真实效果（iabi 携带技能的属性字段，自定义行优先）。
        if code in equipped_effects:
            lines.append("  装备效果: " + ", ".join(equipped_effects[code]))
        # 真实提示文本（地图自定义 ides/utub）优先；继承模板描述仅作兜底。
        lines.append("  " + (tooltips.get(code, "") or desc))  # ides/utub 全文
    if note := _truncated_note(matches, limit):
        lines.append(note)
    if lines:
        return lines
    # 未命中时给物品总量提示 (「未找到」不代表本图没有物品表)
    if items:
        return [
            "未找到物品: " + query,
            f"  （本图物品表共 {len(items)} 件; 可用 item <名称或四码> 查询）",
        ]
    return ["未找到物品: " + query]


def _query_price(pack: Path, query: str, limit: int) -> list[str]:
    items = load_items(pack)
    bases = load_item_bases(pack)
    overrides = load_item_gold_overrides(pack)
    lines = []
    matches = [
        (code, name, desc)
        for code, (name, desc) in items.items()
        if _match(query, code, name)
    ]
    for code, name, desc in _bounded(matches, limit):
        price = _item_price(bases, code, overrides)
        base = bases.get(code, code.lower() if code.lower() in _base_prices() else "-")
        src = "地图价" if code in overrides else "继承"
        lines.append(
            "["
            + code
            + "] "
            + name
            + "  金币: "
            + (price or "-")
            + "  ("
            + src
            + ", 基础: "
            + base
            + ")"
        )
    if note := _truncated_note(matches, limit):
        lines.append(note)
    if lines:
        return lines
    if not lines:
        price = _base_prices().get(query.lower())
        if price:
            lines.append("基础物品 [" + query.lower() + "]  金币: " + price)
    if lines:
        return lines
    if items:
        return [
            "未找到物品价格: " + query,
            f"  （本图物品表共 {len(items)} 件; 可用 price <名称或四码> 查询）",
        ]
    return ["未找到物品价格: " + query]


def _query_shop(pack: Path, query: str, limit: int) -> list[str]:
    """按商店列出售清单与逐件真实价格（igol 地图价优先，回落基础继承价）。"""
    items = load_items(pack)
    bases = load_item_bases(pack)
    overrides = load_item_gold_overrides(pack)
    lines: list[str] = []
    blocks: list[tuple[str, int, int]] = []
    stocked: set[str] = set()
    for shop_code, shop_name, codes in load_shop_stocks(pack):
        if not _match(query, shop_code, shop_name):
            continue
        stocked.add(shop_code)
        block_start = len(lines)
        lines.append("== " + shop_name + " [" + shop_code + "]")
        for c in codes:
            name = items.get(c, (c, ""))[0]
            price = _item_price(bases, c, overrides)
            tag = "地图价" if c in overrides else "继承"
            lines.append(
                "  " + name + "  " + (price or "?") + "金  (" + tag + " " + c + ")"
            )
        lines.append("")
        blocks.append((shop_code, block_start, len(lines)))
    # 商店制造 (关系表独立通道): 奇迹古树/神秘藏宝室这类制造商店没有
    # usei 货架, 只靠 stock 扫描会答「未找到商店」
    craft: dict[str, tuple[str, dict[tuple[str, str], None]]] = {}
    for r in _read_rows(pack, "掉落与获取关系.tsv"):
        if len(r) < 8 or r[2] != "商店制造":
            continue
        code = r[6]
        if not code:
            continue
        entry = craft.setdefault(code, (_clean(r[7]) or code, {}))
        pair = (r[3], _clean(r[4]))
        entry[1].setdefault(pair, None)
    for code, (name, entries) in craft.items():
        if not _match(query, code, name):
            continue
        block_start = len(lines)
        lines.append("== " + name + " [" + code + "]  (商店制造)")
        for icode, iname in entries:
            lines.append("  制造 " + iname + " [" + icode + "]")
        lines.append("")
        blocks.append((code, block_start, len(lines)))
    # 关系表「商店出售」行: 货架字段缺失时的另一证据源——战役容器商店
    # (h704 银月配方商) 只有关系行, 对象字段无自定义 usei, 曾答未找到
    sell: dict[str, tuple[str, dict[str, None]]] = {}
    for r in _read_rows(pack, "掉落与获取关系.tsv"):
        if len(r) < 8 or r[2] != "商店出售":
            continue
        code = r[6]
        if not code:
            continue
        entry = sell.setdefault(code, (_clean(r[7]) or code, {}))
        item = _clean(r[4]) + " [" + r[3] + "]"
        entry[1].setdefault(item, None)
    for code, (name, entries) in sell.items():
        if code in stocked or not _match(query, code, name):
            continue
        block_start = len(lines)
        lines.append("== " + name + " [" + code + "]  (关系表出售)")
        for item in entries:
            lines.append("  " + item)
        lines.append("")
        blocks.append((code, block_start, len(lines)))
    if lines:
        if not limit:
            return lines
        shops = list(dict.fromkeys(code for code, _start, _end in blocks))
        selected = set(_bounded(shops, limit))
        output = [
            line
            for code, start, end in blocks
            if code in selected
            for line in lines[start:end]
        ]
        if note := _truncated_note(shops, limit):
            output.append(note)
        return output
    # 口语店名常不含在完整名里 (「商人」不在「银月配方商」中) —— 答「未找到」
    # 前先把本图真实商店列出来, 并加 ⚠ 前缀让容器聚合把容器级结果打印出来
    known: list[str] = []
    seen_codes: set[str] = set()
    for code, name, _codes in load_shop_stocks(pack):
        if code not in seen_codes:
            seen_codes.add(code)
            known.append(f"{name}[{code}]")
    for code, (name, _entries) in craft.items():
        if code not in seen_codes:
            seen_codes.add(code)
            known.append(f"{name}[{code}]")
    for code, (name, _entries) in sell.items():
        if code not in seen_codes:
            seen_codes.add(code)
            known.append(f"{name}[{code}]")
    if known:
        return [
            "⚠ 未找到商店: " + query,
            "  （本图商店: " + "、".join(known) + "）",
        ]
    return ["未找到商店: " + query]


def _recipe_evidence_note(row: list[str]) -> str:
    """Keep an inferred or incomplete recipe visible as such in query output."""
    details: list[str] = []
    if len(row) > 23 and row[23] and row[23] != "已确认":
        details.append(row[23])
    if len(row) > 24 and row[24] and row[24] != "完整":
        details.append(row[24])
    if len(row) > 25 and row[25]:
        details.append(row[25])
    return "  （" + "；".join(details) + "）" if details else ""


def _query_synth(pack: Path, query: str, limit: int) -> list[str]:
    """synth 全图合成总览: 所有配料一屏列完 (成品 <- 材料)。"""
    del query, limit  # synth 无视过滤与截断, 单配方查询走 recipe
    out: list[str] = []
    seen: set[tuple[str, str]] = set()
    seen_formulas: set[tuple[str, tuple[tuple[str, int], ...]]] = set()
    items = load_items(pack)
    for r in _read_rows(pack, "掉落与获取关系.tsv"):
        if len(r) < 19 or r[2] != "合成":
            continue
        prod, pname, mats = r[3], _clean(r[4]), _clean(r[18])
        if not mats or (prod, mats) in seen:
            continue
        seen.add((prod, mats))
        out.append(
            "[" + prod + "] " + pname + "  <-  " + mats + _recipe_evidence_note(r)
        )
    for prod, pairs in load_formulas(pack):
        key = (prod, tuple(sorted(pairs)))
        if key in seen_formulas:
            continue
        seen_formulas.add(key)
        prod_name = items.get(prod, (prod, ""))[0]
        mat_names = [items.get(c, (c, ""))[0] for c, _k in pairs]
        need = " + ".join(
            n + "x" + str(k) for (_c, k), n in zip(pairs, mat_names, strict=False)
        )
        out.append("[" + prod + "] " + prod_name + "  <-  " + need)
    if not out:
        return ["本包无合成配方"]
    return sorted(dict.fromkeys(out), key=str.casefold)


def _query_recipe(pack: Path, query: str, limit: int) -> list[str]:
    items = load_items(pack)
    hits: list[str] = []
    all_recipes: set[str] = set()
    seen: set[tuple[str, tuple[tuple[str, int], ...]]] = set()
    # 关系表「合成」行与脚本公式索引是两套证据: 公式索引只认脚本形态
    # (迷失国度 0 公式但关系表有秘法瓶/万灵药两条完整合成行)——两套都要
    seen_rels: set[tuple[str, str]] = set()
    for r in _read_rows(pack, "掉落与获取关系.tsv"):
        if len(r) < 19 or r[2] != "合成":
            continue
        prod = r[3]
        pname = _clean(r[4])
        mats = _clean(r[18])
        if not mats:
            continue
        rendered = (
            "[" + prod + "] " + pname + "  <-  " + mats + _recipe_evidence_note(r)
        )
        all_recipes.add(rendered)
        if not (
            _match(query, prod, pname)
            or (r[17] and query.casefold() in r[17].casefold())
            or query.casefold() in mats.casefold()
        ):
            continue
        key = (prod, mats)
        if key in seen_rels:
            continue
        seen_rels.add(key)
        hits.append(rendered)
    for prod, pairs in load_formulas(pack):
        key = (prod, tuple(sorted(pairs)))
        if key in seen:
            continue
        seen.add(key)
        prod_name = items.get(prod, (prod, ""))[0]
        mat_names = [items.get(c, (c, ""))[0] for c, _k in pairs]
        need = " + ".join(
            n + "x" + str(k) for (_c, k), n in zip(pairs, mat_names, strict=False)
        )
        rendered = "[" + prod + "] " + prod_name + "  <-  " + need
        all_recipes.add(rendered)
        if _match(query, prod, prod_name) or any(
            _match(query, c, n) for (c, _k), n in zip(pairs, mat_names, strict=False)
        ):
            hits.append(rendered)
    hits = list(dict.fromkeys(hits))
    if hits:
        note = _truncated_note(hits, limit)
        return [*_bounded(hits, limit), *([note] if note else [])]
    # 未命中时给出配方总量与查询提示——「未找到」不代表本图没有合成
    if all_recipes:
        return [
            "未找到相关配方: " + query,
            f"  （本图关系表/公式索引共 {len(all_recipes)} 条合成配方; "
            "可用 recipe <成品或材料名> 查询）",
        ]
    return ["未找到相关配方: " + query]


def _acquisition_script_evidence(
    pack: Path,
    code: str,
    script: str | None,
    items: dict[str, tuple[str, str]],
    units: dict[str, str],
    names: dict[str, str],
) -> tuple[list[str], list[str]]:
    """Shared death and use/pickup evidence for both acquisition queries."""
    if script is None:
        return [], []
    death: list[str] = []
    usage: list[str] = []
    sources = load_script_contexts(pack) or (AnalysisScriptSource("", script, None),)
    legacy_sources: list[str] = []
    for source, text, lua in sources:
        if lua is True:
            records = trigger_acquisitions(text, lua=True)
            for destination, is_death in ((death, True), (usage, False)):
                destination.extend(
                    format_trigger_acquisitions(
                        records,
                        lambda value: names.get(value, value),
                        source=source,
                        target=code,
                        death=is_death,
                    )
                )
            continue
        legacy_sources.append(text)
    if legacy_sources:
        # JASS functions may deliberately be split across exported WCT/main sources.
        # Keep that established linkage, excluding Lua strings from the JASS parser.
        text = "\n".join(legacy_sources)
        helper_records = tuple(
            record
            for record in trigger_acquisitions(text, lua=False)
            if record.graph is not None and (record.node or record.value_proof)
        )
        for destination, is_death in ((death, True), (usage, False)):
            destination.extend(
                format_trigger_acquisitions(
                    helper_records,
                    lambda value: names.get(value, value),
                    source="、".join(
                        source for source, _text, lua in sources if lua is not True
                    ),
                    target=code,
                    death=is_death,
                )
            )
        death.extend(_script_pool_drops(pack, code, script=text))
        if code in units:
            death.extend(_script_unit_direct_drops(text, code, items, units))
            death.extend(_script_unit_random_drops(text, code, items, units))
        if code in items:
            usage.extend(_script_use_item_loot(text, code, names))
            usage.extend(
                _item_trigger_grant_lines(
                    text, [code], lambda value: names.get(value, value)
                )
            )
    return death, usage


def _query_where(pack: Path, query: str, limit: int) -> list[str]:
    from .pack_query_spatial import SpatialSources, preplaced_objects

    items = load_items(pack)
    units = load_units(pack)
    destructables = load_destructables(pack)
    item_names = {code: name for code, (name, _desc) in items.items()}
    names = {**destructables, **units, **item_names}
    placement_names = {"unit": units, "item": item_names, "destructable": destructables}
    blocks = _AcquisitionBlocks()
    sources = cast(SpatialSources, cast(object, sys.modules[__name__]))
    for kind, code, raw_name, (x, y) in preplaced_objects(pack, sources):
        name = names.get(code, _clean(raw_name))
        if _match(query, code, name):
            tag = "可破坏物" if code in destructables and kind == "装饰" else kind
            blocks.record(
                code,
                f"[{code}] {name} ({tag}) -> ({format_number(x)}, {format_number(y)}) [预放置]",
            )
    for code, x, y, kind in load_placements(pack):
        name = placement_names[kind].get(code, code)
        if _match(query, code, name):
            tag = {"unit": "单位", "item": "地面物品", "destructable": "可破坏物"}[kind]
            blocks.record(
                code,
                f"[{code}] {name} ({tag}) -> ({format_number(x)}, {format_number(y)})",
            )
    for row in _read_rows(pack, "掉落与获取关系.tsv"):
        if len(row) < 7 or not _is_record_code(row[3]):
            continue
        code, name = row[3], _clean(row[4])
        if _match(query, code, name):
            blocks.record(
                code, f"{name} [{code}]  {row[2]} <- {_relation_source_label(row)}"
            )
        if (
            len(row) >= 8
            and _is_record_code(row[6])
            and _match(query, row[6], _clean(row[7]))
        ):
            blocks.record(
                row[6], f"来源 {_clean(row[7])}[{row[6]}]: {row[2]} -> {name} [{code}]"
            )
    # Inspect every matching code, even when another code already has records.
    candidates = dict.fromkeys(
        (
            *blocks.first,
            *(code for code, name in names.items() if _match(query, code, name)),
        )
    )
    if _is_record_code(query) and not candidates:
        candidates[query] = None
    script = load_script(pack)
    for code in candidates:
        death, usage = _acquisition_script_evidence(
            pack, code, script, items, units, names
        )
        blocks.supplement(code, [*death, *usage])
    if blocks.records:
        return blocks.render(limit)
    unit_misses = [
        f"未找到 [{code}] {name} 的预放置/关系表记录。"
        for code, name in units.items()
        if _match(query, code, name)
    ]
    if unit_misses:
        return [
            *_limit_result_blocks([[line] for line in unit_misses], limit),
            "单位掉落查询用 drop <单位名或码> (按单位反查死亡触发)。",
        ]
    hints = _tooltip_source_hints(pack, _hint_targets(pack, query))
    if hints:
        head = (
            "⚠ 文案级来源线索 (无预放置/关系表记录"
            + ("; 脚本加密" if _script_encrypted(pack) else "")
            + "; 未脚本验证):"
        )
        return [head, *_limit_result_blocks([["  " + hint] for hint in hints], limit)]
    lines = ["未找到放置记录: " + query]
    hint = _code_home_hint(pack, query)
    if hint:
        lines.append(hint)
    lines.append(
        "  （若有预放置坐标/脚本位置，可用 near <x> <y> 按坐标反查周边掉落与单位）"
    )
    return lines


_DEATH_COND_BLOCK_RE = re.compile(
    r"function\s+(Trig_\w+?)Conditions\s+takes nothing returns boolean(.*?)endfunction",
    re.S,
)
_POOL_ITEM_RE = re.compile(
    r"ItemPoolAddItemType\(\s*(udg_\w+)\[(\d+)\]\s*,\s*(?:'(\w{4})'|\$([0-9A-Fa-f]{8}))\s*,\s*([\d.]+)"
)
_PLACE_POOL_RE = re.compile(r"PlaceRandomItem\(\s*\(?\s*(udg_\w+)\[(\d+)\]")
_ROLL_RE = re.compile(r"GetRandomInt\(\s*1\s*,\s*(\d+)\s*\)")
_DIRECT_PLACE_RE = re.compile(
    r"(?:CreateItemLoc|CreateItem|UnitAddItemByIdSwapped)\("
    r"\s*(?:'(\w{4})'|\$([0-9A-Fa-f]{8}))",
    re.I,
)
_STOCK_ITEM_RE = re.compile(
    r"AddItemToStockBJ\(\s*(?:'(\w{4})'|\$([0-9A-Fa-f]{8}))",
    re.I,
)
_RANDOM_CALL_RE = re.compile(r"GetRandom(?:Real|Int)\([^)]*\)")
_DEATH_UNIT_RE = re.compile(
    r"GetUnitTypeId\(Get(?:Dying|Trigger)Unit\(\)\)\s*==\s*(?:'(\w{4})'|\$([0-9A-Fa-f]{8}))",
    re.I,
)
_DEATH_HANDLE_RE = re.compile(
    r"(?:Get(?:Dying|Trigger)Unit\(\)\s*==\s*(gg_unit_\w+|udg_\w+)"
    r"|(gg_unit_\w+|udg_\w+)\s*==\s*Get(?:Dying|Trigger)Unit\(\))",
    re.I,
)
_RANDOM_STOCK_RE = re.compile(r"ChooseRandomItemExBJ\(\s*(\d+)\s*,\s*([A-Za-z_]+)\s*\)")
_UNIT_VAR_RE = re.compile(
    r"set\s+(udg_\w+)\s*=\s*(?:CreateUnit\([^,]*,\s*(?:'(\w{4})'|\$([0-9A-Fa-f]{8}))"
    r"|(gg_unit_\w+))",
    re.I,
)


def _balanced_call(body: str, start: int) -> str:
    """从 start 起按括号配平取完整调用语句——语句全文, 不截断。"""
    depth = 0
    for i in range(start, len(body)):
        if body[i] == "(":
            depth += 1
        elif body[i] == ")":
            depth -= 1
            if depth == 0:
                return body[start : i + 1]
    return body[start:]


def _fourcc(literal: str, hex_value: str) -> str:
    """四码归一: 引号形态 'h016' 直接取; YDWE 整数形态 $68303136 -> h016。"""
    if literal:
        return literal
    if len(hex_value) == 8:
        try:
            return bytes.fromhex(hex_value).decode("ascii")
        except ValueError, UnicodeDecodeError:
            return ""
    return ""


def _unit_var_codes(script: str) -> dict[str, str]:
    """udg_X 持有的单位四码 (set udg_X=CreateUnit(...,$hex) 或 =gg_unit_码_序号)。

    YDWE 死亡判定常写 GetDyingUnit()==udg_X 或 gg_unit_码_0122==GetDyingUnit(),
    句柄比较本身不带四码, 靠初始化赋值与 gg_unit 变量名反推。"""
    codes: dict[str, str] = {}
    for m in _UNIT_VAR_RE.finditer(script):
        var = m.group(1).lower()
        if m.group(4):
            g = re.match(r"gg_unit_(\w{4})_\d+", m.group(4), re.I)
            if g:
                codes.setdefault(var, g.group(1))
            continue
        code = _fourcc(m.group(2), m.group(3))
        if code:
            codes.setdefault(var, code)
    return codes


def _death_unit_codes(text: str, var_codes: dict[str, str]) -> list[str]:
    """死亡判定里的单位四码: 类型比较 (引号/整数) + 句柄比较 (gg_unit/udg) 归一。"""
    codes: list[str] = []
    for du in _DEATH_UNIT_RE.finditer(text):
        code = _fourcc(du.group(1), du.group(2))
        if code:
            codes.append(code)
    for hm in _DEATH_HANDLE_RE.finditer(text):
        token = (hm.group(1) or hm.group(2) or "").lower()
        if not token:
            continue
        g = re.match(r"gg_unit_(\w{4})_\d+", token)
        if g:
            codes.append(g.group(1))
        elif token in var_codes:
            codes.append(var_codes[token])
    return codes


_USE_ITEM_COND_RE = re.compile(
    r"GetItemTypeId\(GetManipulatedItem\(\)\)\s*==\s*(?:'(\w{4})'|\$([0-9A-Fa-f]{8}))",
    re.I,
)
_ARRAY_POOL_RE = re.compile(
    r"ItemPoolAddItemType\([^;]*?,\s*(udg_\w+)\[\s*GetRandomInt\(\s*1\s*,\s*(\d+)\s*\)\s*\]"
)
_ARRAY_SET_RE = re.compile(
    r"set\s+(udg_\w+)\[(\d+)\]\s*=\s*(?:'(\w{4})'|\$([0-9A-Fa-f]{8}))",
    re.I,
)


def _script_use_item_loot(script: str, code: str, names: dict[str, str]) -> list[str]:
    """使用物品触发的随机产出证据 (宝箱类: GetManipulatedItem 条件 → 数组池抽件)。

    迷失国度 wbc 系统: 使用物品时创建池子, 逐次
    ItemPoolAddItemType(池, udg_ZBSD[GetRandomInt(1,44)], 1) 从 45 件
    数组随机取件, 定时器回调放置——数组内容静态可解, 满量列出。"""
    want = code.lower()
    arrays: dict[str, list[tuple[int, str]]] = {}
    for m in _ARRAY_SET_RE.finditer(script):
        acode = _fourcc(m.group(3), m.group(4))
        if acode:
            arrays.setdefault(m.group(1), []).append((int(m.group(2)), acode))
    if not arrays:
        return []
    # 处理器按注册位置配对: 局部 trigger 变量在初始化函数里反复复用,
    # 全脚本按变量名配对会把无关动作体当产出 (与 _item_trigger_blocks 同源)
    conds, _acts = _registration_maps(script)
    out: list[str] = []
    for m in _DEATH_COND_BLOCK_RE.finditer(script):
        cond_body = " ".join(m.group(2).split())
        hits = {
            _fourcc(x.group(1), x.group(2)).lower()
            for x in _USE_ITEM_COND_RE.finditer(cond_body)
        }
        if want not in hits:
            continue
        stem = m.group(1)
        reg = conds.get(stem + "Conditions")
        if not reg:
            continue
        var, pos = reg
        _scope, scope_body, scope_start = _function_scope_at(script, pos)
        act = _action_after_registration(var, pos, scope_body, scope_start)
        if not act:
            continue
        action_body = _fn_body(script, act)
        for pm in _ARRAY_POOL_RE.finditer(action_body):
            arr, cap = pm.group(1), int(pm.group(2))
            entries = sorted(arrays.get(arr, []))
            if not entries:
                continue
            names_text = "、".join(f"{names.get(c, c)}({c})" for _i, c in entries)
            out.append(
                f"⚠ 使用触发随机产出 ({stem}Conditions 命中该物品): "
                f"从数组池 {arr}[1..{cap}] 随机抽件, 共 {len(entries)} 件: "
                + names_text
            )
    return out


@lru_cache(maxsize=4)
def _item_trigger_blocks(
    script: str,
) -> tuple[tuple[str, tuple[str, ...], str, frozenset[str]], ...]:
    """反应 GetManipulatedItem 的触发块 (stem, 条件物品码, 动作体, 事件集)。

    双形态: ①Trig_*Conditions/Trig_*Actions 成对 (wbc 开箱);
    ②动作体自判 (hxsj TBX/JFDH/SJSRWPGM 兑换系统——条件函数不存在,
    物品判定与发放都在 action 里)。事件集区分拾取/使用维度。
    配对按注册位置: 初始化函数里 t 会被反复 CreateTrigger 复用, 只按
    (作用域, 变量) 会把末个 action 配给所有条件 (YDWE 死亡模板事故)。"""
    conds, acts = _registration_maps(script)
    blocks: list[tuple[str, tuple[str, ...], str, frozenset[str]]] = []
    seen_bodies: set[str] = set()
    for m in _DEATH_COND_BLOCK_RE.finditer(script):
        cond_body = " ".join(m.group(2).split())
        codes = [
            _fourcc(x.group(1), x.group(2))
            for x in _USE_ITEM_COND_RE.finditer(cond_body)
        ]
        codes = [c for c in codes if c]
        if not codes:
            continue
        stem = m.group(1)
        reg = conds.get(stem + "Conditions")
        if not reg:
            continue
        var, pos = reg
        _scope, scope_body, scope_start = _function_scope_at(script, pos)
        act = _action_after_registration(var, pos, scope_body, scope_start)
        if not act:
            continue
        body = _fn_body(script, act)
        if body == "(未找到函数体)":
            continue
        seen_bodies.add(act)
        events = _registration_events(var, pos, scope_body, scope_start)
        blocks.append((stem, tuple(codes), body, frozenset(events)))
    for m in _FN_ALL_RE.finditer(script):
        name = m.group(1)
        if name in seen_bodies:
            continue
        body = m.group(2)
        if "GetManipulatedItem" not in body:
            continue
        codes = [
            _fourcc(x.group(1), x.group(2)) for x in _USE_ITEM_COND_RE.finditer(body)
        ]
        codes = [c for c in codes if c]
        if not codes:
            continue
        reg = acts.get(name)
        if not reg:
            continue
        var, pos = reg
        _scope, scope_body, scope_start = _function_scope_at(script, pos)
        events = _registration_events(var, pos, scope_body, scope_start)
        stem = name[: -len("Actions")] if name.endswith("Actions") else name
        blocks.append((stem, tuple(codes), body, frozenset(events)))
    return tuple(blocks)


def _item_trigger_grant_lines(
    script: str, codes: list[str], name_of, label_all: bool = False
) -> list[str]:
    """GetManipulatedItem 条件触发 (拾取/使用) 的直接发放证据。

    拾取凭证/宝箱 → 给物品是 hxsj 世界商人/铜宝箱系统 (I03O 掷骰
    GetRandomInt(1,300)<=150 给 I01O/I02G/I032 即此类); 与数组池
    (use_item_loot_lines) 并行, 都按「条件命中物品 → 触发器 → 动作」解析。"""
    wants = {c.lower() for c in codes}
    out: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    for stem, cond_codes, body, events in _item_trigger_blocks(script):
        hit = [c for c in cond_codes if label_all or c.lower() in wants]
        if not hit:
            continue
        if "EVENT_PLAYER_UNIT_PICKUP_ITEM" in events:
            kind = "拾取"
        elif "EVENT_PLAYER_UNIT_USE_ITEM" in events:
            kind = "使用"
        else:
            kind = "触发"
        randoms = list(_RANDOM_CALL_RE.finditer(body))
        local: list[tuple[str, str]] = []
        for dm in _DIRECT_PLACE_RE.finditer(body):
            icode = _fourcc(dm.group(1), dm.group(2))
            if not icode:
                continue
            prior = [r for r in randoms if r.end() <= dm.start()]
            gate = _balanced_call(body, prior[-1].start()) if prior else ""
            key = (stem, icode, gate)
            if key in seen:
                continue
            seen.add(key)
            local.append((icode, gate))
        if not local:
            continue
        note = " (同一触发器内多分支, 未必同时获得)" if len(local) > 1 else ""
        users = "、".join(f"{name_of(c)}({c})" for c in hit)
        for icode, gate in local:
            suffix = f" ({gate})" if gate else ""
            out.append(
                f"⚠ {kind}触发产出 ({stem} 命中 {users}): "
                f"获取 {name_of(icode)}({icode}){suffix}{note}"
            )
    return out


def use_item_loot_lines(script: str, name_of) -> list[str]:
    """guide「开箱与随机产出」段: 使用物品触发的数组池随机产出, 一遍聚合。

    与 where 的 _script_use_item_loot 同源: 条件 `GetManipulatedItem` 命中的
    物品列表 + 动作注册的数组池 (`udg_X[GetRandomInt(1,N)]`) → 数组内容
    静态全解满量列出 (迷失国度 wbc 系统 45/10/10/27 件四池即此法实证)。"""
    arrays: dict[str, list[tuple[int, str]]] = {}
    for m in _ARRAY_SET_RE.finditer(script):
        acode = _fourcc(m.group(3), m.group(4))
        if acode:
            arrays.setdefault(m.group(1), []).append((int(m.group(2)), acode))
    if not arrays:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for stem, cond_codes, action_body, events in _item_trigger_blocks(script):
        if not cond_codes:
            continue
        kind = "拾取" if "EVENT_PLAYER_UNIT_PICKUP_ITEM" in events else "使用"
        users = "、".join(f"{name_of(c)}({c})" for c in cond_codes)
        for pm in _ARRAY_POOL_RE.finditer(action_body):
            arr, cap = pm.group(1), int(pm.group(2))
            entries = sorted(arrays.get(arr, []))
            if not entries:
                continue
            line = (
                f"- {kind} {users} 随机产出: 从数组池 {arr}[1..{cap}] 随机抽件, "
                f"共 {len(entries)} 件: "
                + "、".join(f"{name_of(c)}({c})" for _i, c in entries)
            )
            if line in seen:
                continue
            seen.add(line)
            out.append(line)
    return out


def _script_pool_drops(
    pack: Path, code: str, *, script: str | None = None
) -> list[str]:
    """死亡触发兜底: 关系表无该单位掉落行时, 扫 GetDyingUnit 条件的两种形态。

    ①奖池 PlaceRandomItem —— 输出仍是"池子 N 选 1"形态, 不写成固定掉落;
    ②直落 CreateItemLoc/UnitAddItemByIdSwapped —— 奖池扫描看不见的
    "死亡位置直发"写法 (BossFH 直落 I01F 曾被漏报为"无掉落记录")。"""
    script = load_script(pack) if script is None else script
    if script is None or len(code) != 4:
        return []
    want = "'" + code.lower() + "'"
    want_hex = "$" + code.encode("ascii", "replace").hex()
    var_codes = _unit_var_codes(script)
    # 处理器按注册位置配对 (变量复用问题同 _script_use_item_loot)
    conds, _acts = _registration_maps(script)
    pools: dict[tuple[str, str], list[tuple[str, float]]] = {}
    for pm in _POOL_ITEM_RE.finditer(script):
        pcode = _fourcc(pm.group(3), pm.group(4))
        if not pcode:
            continue
        pools.setdefault((pm.group(1), pm.group(2)), []).append(
            (pcode, float(pm.group(5)))
        )
    items = load_items(pack)
    units = load_units(pack)
    out: list[str] = []
    for m in _DEATH_COND_BLOCK_RE.finditer(script):
        body = m.group(2)
        lower = body.lower()
        matched = want in lower or want_hex.lower() in lower
        if not matched:
            matched = any(
                c.lower() == code.lower() for c in _death_unit_codes(body, var_codes)
            )
        if not matched or "GetDyingUnit" not in body:
            continue
        reg = conds.get(m.group(1) + "Conditions")
        if not reg:
            continue
        var, pos = reg
        _scope, scope_body, scope_start = _function_scope_at(script, pos)
        act = _action_after_registration(var, pos, scope_body, scope_start)
        if not act:
            continue
        action_body = _fn_body(script, act)
        placed = _PLACE_POOL_RE.findall(action_body)
        if not placed:
            continue
        denom = _ROLL_RE.findall(action_body)
        chance = f"1~{denom[0]} 掷骰" if denom else "掷骰"
        if denom and re.search(rf"SaveInteger.*?,\s*{denom[0]}\s*\)", action_body):
            chance = f"{denom[0]}/{denom[0]}=必掉"
        label = units.get(code, units.get(code.upper(), code))
        out.append(f"{label} [{code}]  ⚠ 脚本死亡奖池 (脚本证据):")
        for pvar, pidx in placed:  # 全部奖池
            entries = pools.get((pvar, pidx), [])
            total = sum(w for _, w in entries) or 1.0
            out.append(
                f"  死亡{chance}掉1件, 池 {pvar}[{pidx}] 共{len(entries)}件 (权重/总权重):"
            )
            prices = load_item_gold_overrides(pack)
            shelves_by_item: dict[str, list[str]] = {}
            for _sc, sname, stocks in load_shop_stocks(pack):
                for c in stocks:
                    shelves_by_item.setdefault(c, []).append(sname)
            name_counts: dict[str, int] = {}
            for _uc, (un, _ud) in items.items():
                name_counts[un] = name_counts.get(un, 0) + 1
            acq_by_item: dict[str, list[str]] = {}
            rel_rows = _read_rows(pack, "掉落与获取关系.tsv")
            if rel_rows:
                hdr = rel_rows[0]
                try:
                    ci = hdr.index("装备ID")
                    ck = hdr.index("关系类型")
                    cn = hdr.index("来源名称")
                except ValueError:
                    ci = ck = cn = -1
                if ci >= 0:
                    for r in rel_rows[1:]:
                        if len(r) <= max(ci, ck, cn):
                            continue
                        kind = r[ck]
                        src = r[cn].strip()
                        tag = ""
                        if kind == "合成":
                            tag = "可合成"
                        elif kind == "商店制造":
                            tag = "商店制造" + (("@" + src) if src else "")
                        elif kind == "脚本/触发奖励" and src:
                            tag = "脚本获取@" + src
                        if tag:
                            lst = acq_by_item.setdefault(r[ci], [])
                            if tag not in lst:
                                lst.append(tag)
            for icode, w in entries:
                iname, idesc = items.get(icode, (icode, ""))
                qm = re.search(r"品质[：:]\s*([\w\u4e00-\u9fff]+)", idesc)
                tag = "·" + qm.group(1) if qm else ""
                slot = _item_slot_by_name(iname)
                if slot:
                    tag += "·" + slot + "(名推断)"
                p = prices.get(icode, "")
                shelves = shelves_by_item.get(icode, [])
                if p and p != "0":
                    if not shelves:
                        price_disp = "估值" + p + "金(无货架记录)"
                    elif len(shelves) == 1:
                        price_disp = "在售" + p + "金@" + shelves[0]
                    else:
                        price_disp = p + "金@" + "/".join(shelves)  # 全部货架
                else:
                    price_disp = "非卖品"
                acq = acq_by_item.get(icode, [])
                if acq:
                    price_disp += "·" + "/".join(acq)  # 全部获取途径
                if name_counts.get(iname, 1) > 1:
                    price_disp += "·同名异码价随码"
                out.append(
                    f"    - {iname} [{icode}]  {w:g}/{total:g}  {price_disp}{tag}"
                )
        out.append("")
    out.extend(_script_direct_death_drops(script, code, items, units))
    out.extend(_script_random_dist_item_drops(script, code, items, units))
    return out


_FN_ALL_RE = re.compile(
    r"function\s+(\w+)\s+takes[^\n]*\n(.*?)endfunction",
    re.S,
)


@lru_cache(maxsize=4)
def _death_blocks(script: str) -> tuple[tuple[str, str, str, str], ...]:
    """死亡处理块 (stem, label, cond_text, body)。

    两种真实形态都要发现: ①Trig_*Conditions/Trig_*Actions 成对;
    ②动作体自判——无独立条件函数, GetDyingUnit 判定写在 action 里
    (hxsj Trig_____________ZZ2Actions 的 CreateItem('I07H') 曾被整类漏扫)。
    label 是证据行展示名: 成对形态用「死亡条件 {stem}Conditions」。"""
    blocks: list[tuple[str, str, str, str]] = []
    done: set[str] = set()
    for m in _DEATH_COND_BLOCK_RE.finditer(script):
        stem = m.group(1)
        fname = stem + "Actions"
        action = _fn_body(script, fname)
        if action == "(未找到函数体)":
            continue
        done.add(fname)
        label = f"死亡条件 {stem}Conditions"
        blocks.append((stem, label, " ".join(m.group(2).split()), action))
    for m in _FN_ALL_RE.finditer(script):
        fname = m.group(1)
        if fname in done:
            continue
        sig = m.group(0)[: m.group(0).find("\n")]
        if "returns boolean" in sig:
            continue
        body = m.group(2)
        if "GetDyingUnit()" not in body:
            continue
        done.add(fname)
        stem = fname[: -len("Actions")] if fname.endswith("Actions") else fname
        blocks.append((stem, f"死亡处理函数 {fname} (动作体内判定)", "", body))
    return tuple(blocks)


_UNIT_DEATH_REG_RE = re.compile(
    r"TriggerRegisterUnitEvent\(\s*([A-Za-z_]\w*)\s*,\s*([A-Za-z_]\w*)\s*,"
    r"\s*EVENT_UNIT_DEATH\s*\)"
)
_CREATE_UNIT_VAR_RE = re.compile(
    # 第一个实参常是 Player(0) 这类带括号表达式, 不能用 [^)] 截断;
    # 按第一个逗号切到单位码参数
    r"set\s+([A-Za-z_]\w*)\s*=\s*CreateUnit\(\s*[^,\n]+,\s*(?:'(\w{4})'|\$([0-9A-Fa-f]{8}))"
)
_RANDOM_DIST_ADD_RE = re.compile(
    r"RandomDistAddItem\(\s*(?:'(\w{4})'|\$([0-9A-Fa-f]{8}))\s*,\s*(\d+)\s*\)"
)


@lru_cache(maxsize=4)
def _unit_death_random_drops(
    script: str,
) -> tuple[tuple[str, str, tuple[tuple[str, int], ...]], ...]:
    """YDWE 每单位死亡掉落模板: (单位码, 处理函数, [(物品码, 权重)])。

    该模板用 bj_lastDyingWidget 取死亡单位、RandomDistAddItem 配权重,
    动作体里既无 GetDyingUnit() 也无 CreateItem 调用——现有两种死亡形态
    都扫不到 (永歌余烬 E601 的 Unit000078_DropItems 即此法实证)。
    关联方式: 同函数内 EVENT_UNIT_DEATH 注册的 unit 变量取其前最近的
    set u=CreateUnit(...,'码',...) 单位码; 触发器变量取 TriggerAddAction。"""
    out: dict[tuple[str, str], list[tuple[str, int]]] = {}
    for hm in _FN_HEAD_RE.finditer(script_views(script).syntax):
        end = script_views(script).syntax.find("endfunction", hm.start())
        body = script[hm.start() : len(script) if end < 0 else end]
        creates = list(_CREATE_UNIT_VAR_RE.finditer(body))
        if not creates:
            continue
        for rm in _UNIT_DEATH_REG_RE.finditer(body):
            trigger_var, unit_var = rm.group(1), rm.group(2)
            code = ""
            for cm in creates:
                if cm.start() > rm.start():
                    break
                if cm.group(1) == unit_var:
                    code = _fourcc(cm.group(2), cm.group(3))
            if not code:
                continue
            # 处理器必须取注册语句之后最近的一个: 初始化函数里往往有几十处
            # TriggerAddAction (CreateNeutralHostile 41 处), 从函数头搜会
            # 把无关处理器配给每个单位 (o604/o605/o606 曾共用 196)
            fn = _action_after_registration(
                trigger_var, hm.start() + rm.start(), body, hm.start()
            )
            if not fn:
                continue
            regs = [
                (_fourcc(im.group(1), im.group(2)), int(im.group(3)))
                for im in _RANDOM_DIST_ADD_RE.finditer(_fn_body(script, fn))
            ]
            regs = [(c, w) for c, w in regs if c]
            if not regs:
                continue
            out.setdefault((code, fn), []).extend(regs)
    return tuple((code, fn, tuple(regs)) for (code, fn), regs in out.items())


def _script_unit_random_drops(
    script: str,
    unit_code: str,
    items: dict[str, tuple[str, str]],
    units: dict[str, str],
) -> list[str]:
    """单位维度: 该单位的 YDWE 死亡随机掉落模板内容 (权重满量)。"""
    del units  # 签名与关系表单位维度统一; 匹配靠 unit_code
    want = unit_code.lower()
    out: list[str] = []
    for ucode, fn, regs in _unit_death_random_drops(script):
        if ucode.lower() != want:
            continue
        total = sum(w for _c, w in regs) or 1
        inner = "、".join(
            f"{items.get(c, (c, ''))[0]}({c}) {w}/{total}" for c, w in regs
        )
        out.append(f"  死亡触发 {fn} 随机掉落 (权重满量): {inner}")
    return out


def _script_random_dist_item_drops(
    script: str,
    code: str,
    items: dict[str, tuple[str, str]],
    units: dict[str, str],
) -> list[str]:
    """物品维度: 该物品出现在哪些 YDWE 每单位死亡随机掉落模板里。"""
    del items  # 签名与单位维度统一; 匹配靠 code, units 用于单位名展示
    want = code.lower()
    out: list[str] = []
    for ucode, fn, regs in _unit_death_random_drops(script):
        hit = [(c, w) for c, w in regs if c.lower() == want]
        if not hit:
            continue
        uname = units.get(ucode) or units.get(ucode.upper()) or ucode
        total = sum(w for _c, w in regs) or 1
        out.append(
            "⚠ 脚本死亡随机掉落 (YDWE 每单位模板, 关系表无行): "
            + uname
            + " ["
            + ucode
            + "] 死亡触发 "
            + fn
            + f" 权重 {hit[0][1]}/{total}"
        )
    return out


def _script_direct_death_drops(
    script: str,
    code: str,
    items: dict[str, tuple[str, str]],
    units: dict[str, str],
) -> list[str]:
    """死亡位置直落兜底: GetDyingUnit 条件的动作体里直发该物品。

    CreateItemLoc(码, 死亡位置) 与 UnitAddItemByIdSwapped(码, 击杀者) 两种
    写法奖池扫描都看不见。掷骰门槛只列「同函数掷骰」原文, 门槛是否套用
    本物品不猜, 以函数体全文为准 (防呆五闸④: 含随机数不写保底配方)。"""
    if len(code) != 4:
        return []
    want = code.lower()
    iname = next((un for c, (un, _ud) in items.items() if c.lower() == want), code)
    out: list[str] = []
    seen: set[tuple[str, str]] = set()
    for stem, label, cond_body, action_body in _death_blocks(script):
        if "GetDyingUnit" not in cond_body + action_body:
            continue
        randoms = list(_RANDOM_CALL_RE.finditer(action_body))
        death_units = list(_DEATH_UNIT_RE.finditer(action_body))
        hits: list[list[str]] = []
        for dm in _DIRECT_PLACE_RE.finditer(action_body):
            if _fourcc(dm.group(1), dm.group(2)).lower() != want:
                continue
            cs = action_body.rfind("call ", max(0, dm.start() - 5), dm.start())
            snippet = _balanced_call(action_body, cs if cs >= 0 else dm.start())
            if (stem, snippet) in seen:
                continue
            seen.add((stem, snippet))
            prior = [r for r in randoms if r.end() <= dm.start()]
            gate = (
                "同函数掷骰: "
                + _balanced_call(action_body, prior[-1].start())
                + " (门槛是否套用本物品以函数体为准)"
                if prior
                else "同函数掷骰: 无(本语句之前)"
            )
            verb = (
                "死亡直落语句"
                if dm.group(0).lower().startswith("createitem")
                else "死亡触发发放"
            )
            lines = [f"  死亡触发 {stem} -> {verb}: {snippet}"]
            killers = [du for du in death_units if du.end() <= dm.start()]
            if killers:
                ducode = _fourcc(killers[-1].group(1), killers[-1].group(2))
                uname = units.get(ducode) or units.get(ducode.upper()) or ducode
                lines.append(f"    死亡单位判定: {uname} [{ducode}]")
            lines.append("    " + gate)
            hits.append(lines)
        if hits:
            out.append(f"{iname} [{code}]  ⚠ 脚本死亡位置直落 (脚本证据):")
            out.append(f"  {label}: {cond_body}" if cond_body else f"  {label}")
            for hit_lines in hits:
                out.extend(hit_lines)
    return out


def _script_unit_direct_drops(
    script: str,
    unit_code: str,
    items: dict[str, tuple[str, str]],
    units: dict[str, str],
) -> list[str]:
    """按单位反查死亡直落: 该单位死亡触发创建的全部物品。

    「打 X 掉什么」按单位名问时, 物品维度的直落扫描(匹配
    CreateItemLoc 物品参数)反不进去——奖池扫描能命中条件体单位码,
    直落证据却缺席。以 GetUnitTypeId(Get(Dying|Trigger)Unit())==
    \'码\' 在条件体或动作体出现为准, 满量列出该触发器内全部直落
    语句与各自掷骰门槛 (不写保底配方)。"""
    want = unit_code.lower()
    iname = units.get(unit_code) or units.get(unit_code.upper()) or unit_code
    var_codes = _unit_var_codes(script)
    out: list[str] = []
    seen: set[tuple[str, str, str]] = set()
    for stem, label, cond_body, action_body in _death_blocks(script):
        if not any(
            c.lower() == want
            for c in _death_unit_codes(cond_body + "\n" + action_body, var_codes)
        ):
            continue
        randoms = list(_RANDOM_CALL_RE.finditer(action_body))
        rows: list[str] = []
        for dm in _DIRECT_PLACE_RE.finditer(action_body):
            icode = _fourcc(dm.group(1), dm.group(2))
            cs = action_body.rfind("call ", max(0, dm.start() - 5), dm.start())
            snippet = _balanced_call(action_body, cs if cs >= 0 else dm.start())
            key = (stem, snippet, icode)
            if key in seen:
                continue
            seen.add(key)
            prior = [r for r in randoms if r.end() <= dm.start()]
            gate = (
                "同函数掷骰: "
                + _balanced_call(action_body, prior[-1].start())
                + " (门槛是否套用本物品以函数体为准)"
                if prior
                else "同函数掷骰: 无(本语句之前)"
            )
            dname = next(
                (n for c, (n, _d) in items.items() if c.lower() == icode.lower()),
                icode,
            )
            rows.append(f"  死亡触发 {stem} -> 直落: {dname} [{icode}]: {snippet}")
            rows.append("    " + gate)
        if rows:
            if not out:
                out.append(
                    f"{iname} [{unit_code}]  ⚠ 按单位反查死亡直落 (该单位死亡触发创建的物品):"
                )
            out.append(f"  {label}: {cond_body}" if cond_body else f"  {label}")
            out.extend(rows)
            continue
        # 无固定物品, 但死亡触发在运行时随机补货——如实报机制, 不报成
        # 「无死亡证据」(迷失国度 drs 死亡触发给商店随机上架即此类)。
        stock_counts: dict[tuple[str, str], int] = {}
        for level, kind in _RANDOM_STOCK_RE.findall(action_body):
            key = (level, kind)
            stock_counts[key] = stock_counts.get(key, 0) + 1
        stock_items: list[str] = []
        for sm in _STOCK_ITEM_RE.finditer(action_body):
            scode = _fourcc(sm.group(1), sm.group(2))
            if scode and scode not in stock_items:
                stock_items.append(scode)
        if not stock_counts and not stock_items:
            continue
        if not out:
            tail = "见运行时随机" if stock_counts else "死亡触发上架商店"
            out.append(
                f"{iname} [{unit_code}]  ⚠ 按单位反查死亡触发 (无固定掉落, {tail}):"
            )
        out.append(f"  死亡条件 {stem}Conditions: {cond_body}")
        for scode in stock_items:
            sname = next(
                (n for c, (n, _d) in items.items() if c.lower() == scode.lower()),
                scode,
            )
            out.append(f"  死亡触发 {stem} -> 上架商店: {sname} [{scode}]")
        for (level, kind), count in stock_counts.items():
            suffix = f" ×{count}" if count > 1 else ""
            out.append(
                f"  死亡触发 {stem} -> 随机补货: ChooseRandomItemExBJ({level}, {kind})"
                + suffix
                + " (运行时随机选物, 无固定物品码)"
            )
    return out


def _item_label(code: str, name_of) -> str:
    """物品展示: 名字与码相同时只显示码 (避免 I609(I609) 冗余)。"""
    name = name_of(code)
    return f"{name}({code})" if name and name != code else f"[{code}]"


def script_death_drop_lines(script: str, name_of) -> list[str]:
    """guide drops 段的脚本死亡掉落附录: 一遍走全脚本按判定单位聚合。

    与按码查询的 _script_direct_death_drops/_script_unit_direct_drops
    同正则族, 面向 guide 全量报告——每触发器一行: 直落语句带同函数掷骰
    门槛原文, 奖池保持「池子 N 选 1+权重」措辞 (防呆五闸④), 关系表
    UNIT_DROP 行之外的全部脚本死亡证据在此满量浮出。"""
    pool_items: dict[tuple[str, str], list[tuple[str, float]]] = {}
    for pm in _POOL_ITEM_RE.finditer(script):
        pcode = _fourcc(pm.group(3), pm.group(4))
        if not pcode:
            continue
        pool_items.setdefault((pm.group(1), pm.group(2)), []).append(
            (pcode, float(pm.group(5)))
        )
    var_codes = _unit_var_codes(script)
    out: list[str] = []
    seen: set[str] = set()
    for stem, label, cond_body, action_body in _death_blocks(script):
        unit_codes: list[str] = []
        seen_units: set[str] = set()
        for code in _death_unit_codes(cond_body + "\n" + action_body, var_codes):
            if code.lower() in seen_units:
                continue
            seen_units.add(code.lower())
            unit_codes.append(code)
        if not unit_codes:
            continue
        randoms = list(_RANDOM_CALL_RE.finditer(action_body))
        direct: list[str] = []
        seen_entries: set[str] = set()
        for dm in _DIRECT_PLACE_RE.finditer(action_body):
            icode = _fourcc(dm.group(1), dm.group(2))
            cs = action_body.rfind("call ", max(0, dm.start() - 5), dm.start())
            snippet = _balanced_call(action_body, cs if cs >= 0 else dm.start())
            if snippet in seen_entries:
                continue
            seen_entries.add(snippet)
            prior = [r for r in randoms if r.end() <= dm.start()]
            gate = _balanced_call(action_body, prior[-1].start()) if prior else "无掷骰"
            direct.append(f"{name_of(icode)}({icode}) 掷骰:{gate}")
        pools: list[str] = []
        for pvar, pidx in _PLACE_POOL_RE.findall(action_body):
            regs = pool_items.get((pvar, pidx), [])
            if not regs:
                continue
            total = sum(w for _, w in regs) or 1.0
            inner = "、".join(f"{name_of(ic)}({ic}) {w:g}/{total:g}" for ic, w in regs)
            pools.append(f"池 {pvar}[{pidx}] 共{len(regs)}件N选1: {inner}")
        stock_counts: dict[tuple[str, str], int] = {}
        for level, kind in _RANDOM_STOCK_RE.findall(action_body):
            key = (level, kind)
            stock_counts[key] = stock_counts.get(key, 0) + 1
        stock_items = [
            _fourcc(sm.group(1), sm.group(2))
            for sm in _STOCK_ITEM_RE.finditer(action_body)
        ]
        stock_items = [sc for sc in stock_items if sc]
        if not direct and not pools and not stock_counts and not stock_items:
            continue
        header = "、".join(f"{name_of(uc)}({uc})" for uc in unit_codes)
        parts: list[str] = []
        if direct:
            parts.append("直落 " + "；".join(direct))
        if pools:
            parts.append("；".join(pools))
        if stock_items:
            parts.append(
                "上架商店 " + "、".join(f"{name_of(sc)}({sc})" for sc in stock_items)
            )
        if stock_counts:
            parts.append(
                "；".join(
                    f"随机补货 ChooseRandomItemExBJ({level}, {kind})"
                    + (f" ×{count}" if count > 1 else "")
                    + " (运行时随机, 无固定码)"
                    for (level, kind), count in stock_counts.items()
                )
            )
        line = f"- {header}  ⚠ 脚本死亡掉落 ({stem}, 关系表外证据): " + "；".join(parts)
        if line in seen:
            continue
        seen.add(line)
        out.append(line)
    # YDWE 每单位死亡模板: bj_lastDyingWidget + RandomDistAddItem——动作体
    # 无 GetDyingUnit()/CreateItem, 上面两种形态都发现不了 (永歌余烬 002 实证)
    for code, fn, regs in _unit_death_random_drops(script):
        total = sum(w for _c, w in regs) or 1
        inner = "、".join(
            (_item_label(ic, name_of) + f" 权重{w}/{total}") for ic, w in regs
        )
        out.append(f"- {name_of(code)}[{code}] 死亡随机掉落 ({fn}): {inner}")
    return out


_SLOT_PATTERNS: tuple[tuple[str, str], ...] = (
    ("手套|拳套|手甲|扳指", "手部"),
    ("靴|鞋", "脚部"),
    ("面具|头盔|头环|面纱|帽|冠", "头部"),
    ("宝典|书|卷|册|礼盒", "书籍/杂物"),
    ("链|项链|戒指|戒|坠|锁|长命", "饰品"),
    ("爪|剑|刀|斧|锤|弓|杖|枪|弩|刃", "武器"),
    ("甲|铠|衣|袍|斗篷|风衣|皮|鳞", "身体"),
)


def _item_slot_by_name(name: str) -> str:
    """物品类型（部位）按名称形态推断——地图无槽位字段(icla)，输出带(名推断)标记。"""
    for pat, slot in _SLOT_PATTERNS:
        if re.search(pat, name):
            return slot
    return ""


def _query_drop(pack: Path, query: str, limit: int) -> list[str]:
    items = load_items(pack)
    units = load_units(pack)
    names = {**units, **{code: name for code, (name, _desc) in items.items()}}
    blocks = _AcquisitionBlocks()
    kinds: dict[str, set[str]] = {}
    target_codes: dict[str, None] = {}
    for row in _read_rows(pack, "掉落与获取关系.tsv"):
        if len(row) < 7 or not _is_record_code(row[3]):
            continue
        code, name = row[3], _clean(row[4])
        if _match(query, code, name):
            target_codes[code] = None
            kinds.setdefault(code, set()).add(row[2])
            blocks.record(
                code, f"{name} [{code}]  {row[2]} <- {_relation_source_label(row)}"
            )
        if (
            len(row) >= 8
            and _is_record_code(row[6])
            and _match(query, row[6], _clean(row[7]))
        ):
            blocks.record(
                row[6], f"{_clean(row[7])}[{row[6]}] {row[2]} -> {name} [{code}]"
            )
    candidates = dict.fromkeys(
        (
            *blocks.first,
            *target_codes,
            *(code for code, name in names.items() if _match(query, code, name)),
        )
    )
    if _is_record_code(query) and not candidates:
        candidates[query] = None
    script = load_script(pack)
    for code in candidates:
        death, usage = _acquisition_script_evidence(
            pack, code, script, items, units, names
        )
        supplemental: list[str] = []
        code_kinds = kinds.get(code, set())
        if code_kinds and not any("掉落" in kind for kind in code_kinds):
            if death:
                supplemental.append(
                    "⚠ 防呆: 关系表无 Boss/单位死亡掉落行, 但脚本死亡触发有直发证据(见下); NPC 随身携带仍不构成掉落证据"
                )
            else:
                supplemental.append(
                    "⚠ 防呆: 该物品无 Boss/单位死亡掉落记录(仅 "
                    + "/".join(sorted(code_kinds))
                    + ")——不得断言打怪掉落; NPC 随身携带不构成掉落证据"
                )
        blocks.supplement(code, [*supplemental, *death, *usage])
    if blocks.records:
        return blocks.render(limit)
    unit_misses = [
        f"[{code}] {name} 无死亡触发直落/奖池证据。"
        for code, name in units.items()
        if _match(query, code, name)
    ]
    if unit_misses:
        return [
            *_limit_result_blocks([[line] for line in unit_misses], limit),
            "位置/获取查询用 where <词>。",
        ]
    hints = _tooltip_source_hints(pack, _hint_targets(pack, query))
    if hints:
        head = (
            "⚠ 文案级配方/来源线索 (关系表与脚本奖池无记录"
            + ("; 脚本加密" if _script_encrypted(pack) else "")
            + "; 未脚本验证——合成/掉落触发以实际游戏为准):"
        )
        return [head, *_limit_result_blocks([["  " + hint] for hint in hints], limit)]
    lines = ["未找到获取途径: " + query]
    if items or units:
        lines.append(
            f"  （本图物品表 {len(items)} 件 / 单位表 {len(units)} 种; 可换四码或关键词再查）"
        )
    hint = _code_home_hint(pack, query)
    if hint:
        lines.append(hint)
    lines.append(
        "  （若有预放置坐标/脚本位置，可用 near <x> <y> 按坐标反查周边掉落与单位）"
    )
    return lines


def _query_quest(pack: Path, query: str, limit: int) -> list[str]:
    lines = []
    path = pack / "脚本字符串索引.tsv"
    if path.exists():
        for line in _iter_tsv_lines(path):
            if query.casefold() in line.casefold() and (
                "CreateQuestBJ" in line or "DisplayTimedTextToForce" in line
            ):
                lines.append(_clean(line.rstrip("\n")))  # 整行, 不开窗
    if lines:
        return _limit_result_blocks([[line] for line in lines], limit)
    if query:
        # 任务总量提示 + text 改道 (否定断言四维: 总量/换词/数据源)
        total = sum(
            1
            for line in _iter_tsv_lines(path)
            if "CreateQuestBJ" in line or "DisplayTimedTextToForce" in line
        )
        hint = f"本图任务文本共 {total} 条" if total else "本图未捕获到任务文本"
        return [
            "未找到任务文本: " + query,
            f"  （{hint}; 可用 text <词> 全文本索引兜底，或换更短关键词）",
        ]
    return [
        "本图未捕获到任务文本 (无 CreateQuestBJ/DisplayTimedTextToForce 调用)。",
        "  （脚本加密图的任务文本不可读; 或该图确实无任务系统——可用 text <词> 全文本索引兜底）",
    ]


def _query_text(pack: Path, query: str, limit: int) -> list[str]:
    lines = []
    for path in sorted(pack.glob("*.tsv")):
        try:
            for line in _iter_tsv_lines(path):
                if query in line:
                    lines.append(path.name + ": " + _clean(line.rstrip("\n")))  # 整行
        except OSError:
            continue
    if lines:
        note = _truncated_note(lines, limit)
        return [*_bounded(lines, limit), *([note] if note else [])]
    return [
        "未找到文本: " + query + " (扫全部 *.tsv 索引行)",
        "  （可换更短关键词重试; 对象名/效果排查用 search <词> 更专——它按八表结构化匹配）",
    ]


_CHAT_CALL_RE = re.compile(r"\b(TriggerRegisterPlayerChatEvent(?:BJ)?)\s*\(")


def _chat_registrations(
    script: str, *, lua: bool | None
) -> Iterator[tuple[str, str, str, int]]:
    """Read native/BJ chat registrations with balanced, complete arguments."""
    for site in script_trigger_bindings(script, lua=lua).sites:
        api = site.call.name.removeprefix("_G.")
        if api not in {
            "TriggerRegisterPlayerChatEvent",
            "TriggerRegisterPlayerChatEventBJ",
        }:
            continue
        args = site.arguments
        if len(args) != 4:
            continue
        command_index = 1 if api.endswith("BJ") else 2
        command = literal_string_value(args[command_index])
        if command is not None:
            yield args[0], command, args[command_index + 1], site.call.start


_SCOPE_ADD_COND_RE = re.compile(
    r"TriggerAddCondition\(\s*([A-Za-z_]\w*)\s*,\s*Condition\(\s*function\s+(\w+)"
)
_SCOPE_ADD_ACTION_RE = re.compile(
    r"TriggerAddAction\(\s*([A-Za-z_]\w*)\s*,\s*function\s+(\w+)"
)


_SCOPE_CACHE: dict[str, tuple[list[int], list[str]]] = {}
_REGISTRATION_CACHE: dict[
    str, tuple[dict[str, tuple[str, int]], dict[str, tuple[str, int]]]
] = {}


def _script_function_spans(script: str) -> tuple[list[int], list[str]]:
    """按脚本文本缓存 (函数起点列表, 对应函数名列表), 二分定位 O(log n)。

    where/drop/refs 等命令对同一脚本反复查作用域; 旧实现每次 finditer 从头
    扫到 pos, 1428 次 × 4 万行 = 12.6s。缓存后同一脚本只扫一遍。"""
    cached = _SCOPE_CACHE.get(script)
    if cached is None:
        starts: list[int] = []
        names: list[str] = []
        for hm in _FN_HEAD_RE.finditer(script_views(script).syntax):
            starts.append(hm.start())
            names.append(hm.group(1))
        cached = (starts, names)
        _SCOPE_CACHE[script] = cached
    return cached


def _function_scope_at(script: str, pos: int) -> tuple[str, str, int]:
    """包含 pos 的函数 (函数名, 函数体, 函数体起点); 找不到返回 ("", script, 0)。"""
    starts, names = _script_function_spans(script)
    if not starts:
        return "", script, 0
    i = bisect.bisect_right(starts, pos) - 1
    if i < 0:
        return "", script, 0
    name, start = names[i], starts[i]
    end = script_views(script).syntax.find("endfunction", start)
    if end >= 0 and pos >= end + len("endfunction"):
        return "", script, 0
    return name, script[start : len(script) if end < 0 else end], start


def _registration_maps(
    script: str,
) -> tuple[dict[str, tuple[str, int]], dict[str, tuple[str, int]]]:
    """条件/动作函数 -> (触发器变量, 注册语句绝对偏移)。

    偏移是关键: 初始化函数里同一变量 t 会被反复 CreateTrigger 复用
    (CreateNeutralHostile 41 处 TriggerAddAction 都写 t), 只按
    (作用域, 变量) 配对必然张冠李戴。"""
    cached = _REGISTRATION_CACHE.get(script)
    if cached is not None:
        return cached
    conds: dict[str, tuple[str, int]] = {}
    acts: dict[str, tuple[str, int]] = {}
    for m in _SCOPE_ADD_COND_RE.finditer(script):
        conds.setdefault(m.group(2), (m.group(1), m.start()))
    for m in _SCOPE_ADD_ACTION_RE.finditer(script):
        acts.setdefault(m.group(2), (m.group(1), m.start()))
    _REGISTRATION_CACHE[script] = (conds, acts)
    return conds, acts


@lru_cache(maxsize=8)
def _trigger_assignment_offsets(var: str, scope_body: str) -> tuple[int, ...]:
    """Cache syntax positions, without limiting registrations or source length."""
    syntax = script_views(scope_body).syntax
    pattern = re.compile(r"\bset\s+" + re.escape(var) + r"\s*=")
    return tuple(match.start() for match in pattern.finditer(syntax))


def _registration_window(
    var: str, pos: int, scope_body: str, scope_start: int
) -> tuple[int, int]:
    """A trigger's bindings end at its next assignment or the function end."""
    offsets = _trigger_assignment_offsets(var, scope_body)
    index = bisect.bisect_right(offsets, max(0, pos - scope_start))
    start = offsets[index - 1] if index else 0
    end = offsets[index] if index < len(offsets) else len(scope_body)
    return start, end


def _action_after_registration(
    var: str, pos: int, scope_body: str, scope_start: int
) -> str:
    rel = max(0, pos - scope_start)
    _start, end = _registration_window(var, pos, scope_body, scope_start)
    syntax = script_views(scope_body).syntax
    match = re.search(
        r"TriggerAddAction\s*\(\s*" + re.escape(var) + r"\s*,\s*function\s+(\w+)",
        syntax[rel:end],
    )
    return match.group(1) if match else ""


def _registration_events(
    var: str, pos: int, scope_body: str, scope_start: int
) -> set[str]:
    """Read every actual event call for this variable throughout its lifetime."""
    start, end = _registration_window(var, pos, scope_body, scope_start)
    syntax = script_views(scope_body).syntax
    pattern = re.compile(r"\bTriggerRegister\w*\s*\(\s*" + re.escape(var) + r"\s*,")
    events: set[str] = set()
    for match in pattern.finditer(syntax, start, end):
        call = _balanced_call(syntax, match.start())
        events.update(re.findall(r"\bEVENT_\w+", call))
    return events


def load_script(pack_dir: Path) -> str | None:
    """全部 JASS/Lua 脚本全文；一次查询内共用同一份读取结果。"""
    key = str(pack_dir)
    if _QUERY_SCRIPTS is not None and key in _QUERY_SCRIPTS:
        return _QUERY_SCRIPTS[key]
    sources = load_script_contexts(pack_dir)
    result = "\n".join(text for _source, text, _lua in sources) if sources else None
    if _QUERY_SCRIPTS is not None:
        _QUERY_SCRIPTS[key] = result
    return result


def load_script_sources(pack_dir: Path) -> tuple[tuple[str, str], ...]:
    """Read each source once while retaining its language and source boundary."""
    key = str(pack_dir)
    if _QUERY_SCRIPT_SOURCES is not None and key in _QUERY_SCRIPT_SOURCES:
        return _QUERY_SCRIPT_SOURCES[key]
    d = pack_dir / "脚本可读文本"
    if not d.is_dir():
        return ()
    sources: list[tuple[str, str]] = []
    for p in sorted(
        path for path in d.rglob("*") if path.suffix.lower() in (".j", ".lua", ".txt")
    ):
        file_key = (str(pack_dir), p.relative_to(pack_dir).as_posix())
        if _QUERY_FILES is not None:
            _QUERY_FILES.add(file_key)
        try:
            sources.append(
                (
                    p.relative_to(d).as_posix(),
                    p.read_text(encoding="utf-8", errors="replace").replace("\r", "\n"),
                )
            )
            _LOCKED_FILES.discard(file_key)
        except OSError:
            _LOCKED_FILES.add(file_key)
    result = tuple(sources)
    if _QUERY_SCRIPT_SOURCES is not None:
        _QUERY_SCRIPT_SOURCES[key] = result
    return result


def _pack_script_type(pack_dir: Path) -> str:
    return script_type_from_report(
        "\n".join("\t".join(row) for row in _read_rows(pack_dir, "地图信息.txt"))
    )


def load_script_contexts(pack_dir: Path) -> tuple[AnalysisScriptSource, ...]:
    sources = load_script_sources(pack_dir)
    declared = _pack_script_type(pack_dir)
    entries: list[AnalysisScriptSource] = []
    for source, text in sources:
        lua = script_language(
            source,
            available_sources=(name for name, _text in sources),
            declared_script_type=declared,
        )
        entries.append(
            AnalysisScriptSource(source, analysis_script_text(source, text, lua), lua)
        )
    return tuple(entries)


def _script_encrypted(pack_dir: Path) -> bool:
    """平台加密脚本块存在（未知文件/加密脚本检测.txt）：脚本类触发分析不可用。"""
    return (pack_dir / "未知文件" / "加密脚本检测.txt").is_file()


def _hint_targets(pack_dir: Path, query: str) -> set[str]:
    """查询词 -> 文案层提示的目标名集合（四码先解名, 与原词并入）。"""
    targets = {query}
    if len(query) == 4:
        name = load_items(pack_dir).get(query, ("", ""))[0]
        if name:
            targets.add(name)
        uname = load_units(pack_dir).get(query, "")
        if uname:
            targets.add(uname)
    return {t for t in targets if t}


def _tooltip_source_hints(pack_dir: Path, targets: set[str]) -> list[str]:
    """文案层获取线索兜底：其他对象说明文本提到目标物品名（配方/掉落来源）。

    关系表与脚本奖池都无记录时使用——输出必须带"文案级"标注（未脚本验证）。"""
    if not targets:
        return []
    out: list[str] = []
    wanted = sorted(targets)
    for code, (name, desc) in load_items(pack_dir).items():
        if not desc or name in targets:
            continue
        if next((t for t in wanted if t in desc), None) is None:
            continue
        excerpt = desc  # 说明全文
        out.append(f"{name} [{code}] 说明: {excerpt}")
    return out


def _fn_body(script: str, fn: str, *, preserve_whitespace: bool = False) -> str:
    starts, names = _script_function_spans(script)
    try:
        start = starts[names.index(fn)]
    except ValueError:
        return "(未找到函数体)"
    end = script_views(script).syntax.find("endfunction", start)
    body = script[start : end + len("endfunction") if end >= 0 else len(script)]
    return body.strip() if preserve_whitespace else " ".join(body.split())


def _source_drop_map(pack: Path) -> dict[str, str]:
    """来源ID -> 掉落物品清单 (关系表 掉落 行 + YDWE 每单位死亡随机模板)。

    脚本独有掉落 (关系表无行) 同样要进 near 的「掉:」注解——第三形态与
    drop/where/guide 同源, 否则脚底单位注解会漏报。"""
    drops: dict[str, list[str]] = {}
    codes_by_src: dict[str, set[str]] = {}
    for r in _read_rows(pack, "掉落与获取关系.tsv"):
        if len(r) < 8 or "掉落" not in r[2]:
            continue
        src = r[6]
        if not src:
            continue
        entry = _clean(r[4]) + "[" + r[3] + "]"
        lst = drops.setdefault(src, [])
        if entry not in lst:
            lst.append(entry)
        codes_by_src.setdefault(src, set()).add(r[3])
    script = load_script(pack)
    if script is not None:
        item_names = load_items(pack)
        for code, _fn, regs in _unit_death_random_drops(script):
            known = codes_by_src.setdefault(code, set())
            lst = drops.setdefault(code, [])
            for icode, _w in regs:
                if icode in known:
                    continue
                known.add(icode)
                iname = item_names.get(icode, (icode, ""))[0]
                lst.append(
                    (iname if iname and iname != icode else "") + "[" + icode + "]"
                )
    return {code: "、".join(entries) for code, entries in drops.items()}


def _source_shop_map(pack: Path) -> dict[str, str]:
    """商店四码 -> 货架清单 (near 的 卖: 注解 。"""
    shops: dict[str, str] = {}
    for code, _name, stocks in load_shop_stocks(pack):
        if stocks:
            shops[code] = "、".join(stocks)
    return shops


def _query_near_result(pack: Path, query: str, limit: int) -> SpatialQueryResult:
    """Return exact spatial data through the same sources as every pack query."""
    from .pack_query_spatial import SpatialSources, query_near

    return query_near(
        pack, query, limit, cast(SpatialSources, cast(object, sys.modules[__name__]))
    )


def _query_near(pack: Path, query: str, limit: int) -> list[str]:
    """Compatibility text view of the complete spatial query."""
    return list(_query_near_result(pack, query, limit).lines)


_FN_HEAD_RE = re.compile(
    r"(?m)^[ \t]*(?:(?:private|public|static)\s+)*function\s+(\w+)\s+takes"
)


@dataclass
class _CommandMatch:
    variable: str
    command: str
    exact: str
    actions: tuple[CallbackReference, ...]
    conditions: tuple[CallbackReference, ...]
    function: str
    source: str
    script: str
    diagnostic: str = ""
    count: int = 0
    lua: bool | None = None


def _query_cmd(pack: Path, query: str, limit: int) -> list[str]:
    sources = load_script_contexts(pack)
    if not sources:
        return [
            "未找到脚本 (脚本可读文本/*.j / *.lua / 自定义代码)——该包可能未导出可读脚本"
        ]
    exact_hits: dict[tuple[object, ...], _CommandMatch] = {}
    loose_hits: dict[tuple[object, ...], _CommandMatch] = {}
    empty = 0
    for source, script, lua in sources:
        bindings = script_trigger_bindings(script, lua=lua)
        for var, cmd, exact, position in _chat_registrations(script, lua=lua):
            empty += not bool(cmd)
            if cmd == query:
                bucket = exact_hits
            elif len(cmd) > 1 and (query in cmd or cmd in query):
                bucket = loose_hits
            else:
                continue
            registration = bindings.by_start[position]
            owner = bindings.structure.scopes.at(position)
            fn = owner.name if owner is not None else ""
            related = bindings.instances[registration.instance]
            actions = tuple(
                site.callback
                for site in related
                if site.call.name.removeprefix("_G.")
                in {"TriggerAddAction", "TriggerAddActionBJ"}
                and site.callback is not None
            )
            conditions = tuple(
                site.callback
                for site in related
                if site.call.name.removeprefix("_G.")
                in {"TriggerAddCondition", "TriggerAddConditionBJ"}
                and site.callback is not None
            )
            key = (source, registration.instance, cmd, exact, actions, conditions)
            found = bucket.setdefault(
                key,
                _CommandMatch(
                    var,
                    cmd,
                    exact,
                    actions,
                    conditions,
                    fn,
                    source,
                    script,
                    registration.diagnostic,
                    lua=lua,
                ),
            )
            found.count += 1
    hits = exact_hits or loose_hits
    if not hits:
        if empty:
            return [
                f"⚠ 未找到具名聊天指令: {query}",
                f"  （本图另有 {empty} 处空串聊天事件——任意聊天都会触发, 具体参数写在条件/动作里; 见 脚本触发注册索引「聊天事件」行）",
            ]
        return [
            "未找到聊天指令: " + query,
            "  （本图指令注册见 脚本触发注册索引.tsv 的「聊天事件」行; 空串监听=任意聊天触发）",
        ]
    blocks: list[list[str]] = []
    for found in sorted(hits.values(), key=lambda value: -value.count):
        match_kind = (
            "精确"
            if found.exact == "true"
            else "前缀"
            if found.exact == "false"
            else "动态匹配: " + found.exact
        )
        block = [
            f'指令 "{found.command}" ({match_kind}, 注册{found.count}个玩家位) -> {found.variable}',
            "  来源: " + found.source,
        ]
        if found.function:
            block.append("  注册函数: " + found.function)
        if found.diagnostic:
            block.append("  关联诊断: " + found.diagnostic)
        functions = script_functions(found.script, lua=found.lua)
        for label, callbacks in (("条件", found.conditions), ("动作", found.actions)):
            for callback, count in Counter(callbacks).items():
                if count > 1:
                    block.append(f"  {label}注册: 同一回调 {count} 次")
                if callback.diagnostic:
                    block.append(
                        f"  {label}诊断: {callback.diagnostic}; 表达式: {callback.expression}"
                    )
                if not callback.functions:
                    block.append(f"  {label}: {callback.expression}")
                for function in callback.functions:
                    block.append(
                        f"  {label}: "
                        + found.script[function.start : function.end].strip()
                    )
                    block.extend(
                        format_function_graph(
                            functions.graph(function), functions, definitions=True
                        )
                    )
        if not found.actions:
            block.append("  动作: (未找到 TriggerAddAction)")
        block.append("")
        blocks.append(block)
    return _limit_result_blocks(blocks, limit)


_GIVE_MECHS = ("UnitAddItem", "CreateItem")
_GIVE_DIGEST_MARKS = (
    "call UnitAddItem",
    "call CreateItem",
    "=CreateUnit",
    "call CreateNUnitsAtLoc",
)
_CONSUME_MARKS = ("GetItemTypeId", "UnitHasItemOfType", "GetItemOfType", "RemoveItem")


def _ref_kind(mech: str, digest: str, *, context: str = "") -> str:
    """单条对象码引用的形态: give=给予/创建, consume=作为材料或触发媒介, other。

    机制列常为笼统的 ObjectCode，native 名在摘要里，两处都嗅。"""
    if context.startswith(_CONSUME_MARKS):
        return "consume"
    if context.startswith((*_GIVE_MECHS, "CreateUnit", "CreateNUnits", "BlzCreate")):
        return "give"
    if (
        mech.startswith(_GIVE_MECHS)
        or "CreateItem" in mech
        or any(m in digest for m in _GIVE_DIGEST_MARKS)
    ):
        return "give"
    if any(m in digest for m in _CONSUME_MARKS):
        return "consume"
    return "other"


def _query_refs(pack: Path, query: str, limit: int) -> list[str]:
    rows = _read_rows(pack, "脚本对象码出现索引.tsv")
    if not rows:
        return [
            "未找到 脚本对象码出现索引.tsv（资料包未导出脚本索引——用 cli <地图> --pack 重导一次即有）"
        ]
    groups: dict[tuple[str, str], tuple[str, dict[str, list[str]]]] = {}
    for row in rows:
        if len(row) < 11:
            continue
        code, kind, name = row[3], row[5], _clean(row[6])
        if not _is_record_code(code) or not _match(query, code, name):
            continue
        _name, buckets = groups.setdefault(
            (kind, code), (name, {"give": [], "consume": [], "other": []})
        )
        mech, digest = row[9], row[10]
        source = row[0] + ":" if row[0] else ""
        buckets[_ref_kind(mech, digest, context=row[8])].append(
            f"    {source}行{row[1]} {row[2]}  {mech} {digest}"
        )
    if not groups:
        return [
            "未找到引用: " + query,
            "  （引用来自 对象字段.tsv 的单位/物品/技能列表与脚本 native 提码——对象若从未被引用, 此处即「孤立对象」信号）",
        ]
    blocks: list[list[str]] = []
    encrypted = _script_encrypted(pack)
    for (kind, code), (name, buckets) in groups.items():
        give, consume, other = buckets["give"], buckets["consume"], buckets["other"]
        block = [
            f"[{code}] {name}  ({kind})  共{len(give) + len(consume) + len(other)}处引用",
            f"  给予/创建: {len(give)} 处",
            *give,
            f"  作为材料/触发媒介(被检测或移除): {len(consume)} 处",
            *consume,
        ]
        if other:
            block.extend([f"  其他引用: {len(other)} 处", *other])
        if kind == "物品" and give and not consume:
            if encrypted:
                block.append(
                    "  ⚠ 脚本加密: 消耗引用不可读, '终止'结论不成立——先用 pack-query drop <物品名> 查文案级配方线索"
                )
            else:
                block.append(
                    "  ⚠ 零消耗引用: 当前可读索引未发现该物品作为材料被检测/移除的记录，未确认后续升级。"
                )
                block.append(
                    f"    获取/配方复核: recipe {code} / drop {code}；名字带[N/M]不证明存在下一级。"
                )
        blocks.append(block)
    return _limit_result_blocks(blocks, limit)


def _load_affixes(pack_dir: Path) -> list[tuple[str, str, str]]:
    """Retain distinct definitions even when several affixes share one name."""
    return list(
        dict.fromkeys(
            (row[0], row[1], row[2])
            for row in _read_rows(pack_dir, "词缀表.tsv")
            if len(row) >= 3 and row[:3] != ["词缀名", "倍率", "属性"]
        )
    )


def _registered_data_rows(pack_dir: Path) -> list[list[str]]:
    """Accept exported headers and headerless legacy tables without losing row 1."""
    return [
        row
        for row in _read_rows(pack_dir, "注册数据.tsv")
        if len(row) >= 3
        and not (
            row[0] == "消息名" and row[1] in {"记录数", "序号"} and row[2] == "记录JSON"
        )
    ]


def _load_registered_names(pack_dir: Path) -> dict[str, int]:
    """注册数据.tsv: 消息名 → 记录数。内存导出包可选文件。"""
    counts: dict[str, int] = {}
    for row in _registered_data_rows(pack_dir):
        counts[row[0]] = counts.get(row[0], 0) + 1
    return counts


def _query_affix(pack: Path, query: str, limit: int) -> list[str]:
    """词缀公式查询: affixes <词缀名或空>。

    读内存导出包的 词缀表.tsv (live --dump-objects 产出, 模式驱动无词表)。
    空查询 = 全量列出; 命中失败时给总量提示 (否定断言纪律)。
    """
    affixes = _load_affixes(pack)
    if not affixes:
        return [
            "本包无 词缀表.tsv (非内存导出包, 或该图未捕获到词缀定义)。",
            "重新导出: uv run python -X utf8 main.py live --dump-objects <目录>",
            "  （GUI 用户: 数据工具菜单 →「导出运行时对象包 (词缀/注册)」）",
        ]
    blocks: list[list[str]] = []
    for name, mult, stat in sorted(affixes):
        if query and not _match(query, name, stat):
            continue
        unit = "点" if not stat.startswith("的") else ""
        block = [f"[{name}] {stat or '(特效型)'}"]
        if stat:
            block.append(f"  公式: 词条等级 × {mult} {unit}{stat}")
        blocks.append(block)
    return (
        _limit_result_blocks(blocks, limit)
        if blocks
        else [f"未找到词缀: {query}（本包词缀表共 {len(affixes)} 条）"]
    )


def _query_registered(pack: Path, query: str, limit: int) -> list[str]:
    """注册数据查询: registered <消息名>。

    列出消息名与记录数; 带查询词时对记录 JSON 全文子串匹配并全文输出。
    """
    rows = _registered_data_rows(pack)
    if not rows:
        return [
            "本包无可读的注册数据记录 (注册数据.tsv 缺失、为空，或该图未捕获到云消息)。",
            "重新导出: uv run python -X utf8 main.py live --dump-objects <目录>",
            "  （GUI 用户: 数据工具菜单 →「导出运行时对象包 (词缀/注册)」）",
        ]
    counts: dict[str, int] = {}
    matched: list[list[str]] = []
    wanted = query.casefold()
    for row in rows:
        name, payload = row[0], row[2]
        counts[name] = counts.get(name, 0) + 1
        if wanted and (wanted in name.casefold() or wanted in payload.casefold()):
            matched.append([f"== {name} ==", "  " + payload])
    if query:
        if not matched:
            return [
                f"未找到消息: {query}（本包注册数据共 {len(counts)} 种消息名: "
                + "、".join(sorted(counts))
                + "）"
            ]
        return _limit_result_blocks(matched, limit)
    blocks = [[f"  {name}: {counts[name]} 条"] for name in sorted(counts)]
    coverage = "全量" if not limit or limit >= len(blocks) else f"显示 {limit} 种"
    return [
        f"注册消息名 ({len(counts)} 种, {coverage}):",
        *_limit_result_blocks(blocks, limit),
    ]


def _query_search(pack: Path, query: str, limit: int) -> list[str]:
    """Search all object text with optional category scope and Boolean expressions."""
    from .pack_query_search import SearchSources, query_search

    return query_search(
        pack, query, limit, cast(SearchSources, cast(object, sys.modules[__name__]))
    )


def _diff_field_changes(
    old_pack: Path, new_pack: Path, table: str, ids: list[str]
) -> dict[str, list[str]]:
    """对变更对象算字段级差异 (基于两包 对象字段.tsv 的 字段键/值 对比。"""
    result: dict[str, list[str]] = {}
    if not ids:
        return result
    wanted = set(ids)

    def collect(pack: Path) -> dict[str, dict[str, str]]:
        rows = _read_rows(pack, "对象字段.tsv")
        if len(rows) <= 1:
            return {}
        header = rows[0]
        try:
            cat_i = header.index("分类")
            id_i = header.index("ID")
            key_i = header.index("字段键")
            val_i = header.index("值")
        except ValueError:
            return {}
        fields: dict[str, dict[str, str]] = {}
        for r in rows[1:]:
            if len(r) <= max(val_i, key_i, id_i, cat_i):
                continue
            if r[cat_i] != table or r[id_i] not in wanted:
                continue
            fields.setdefault(r[id_i], {})[r[key_i]] = r[val_i]
        return fields

    old_fields = collect(old_pack)
    new_fields = collect(new_pack)
    for obj_id in ids:
        o = old_fields.get(obj_id, {})
        n = new_fields.get(obj_id, {})
        if not o and not n:
            continue
        lines: list[str] = []
        for key in sorted(set(o) | set(n)):
            ov = o.get(key)
            nv = n.get(key)
            if ov == nv:
                continue
            if ov is None:
                lines.append(f"{key}: (无) -> {nv}")
            elif nv is None:
                lines.append(f"{key}: {ov} -> (删)")
            else:
                lines.append(f"{key}: {ov} -> {nv}")
        if lines:
            result[obj_id] = lines
    return result


def _query_diff(pack: Path, query: str, limit: int, pack_b: str = "") -> list[str]:
    """diff 双包对比: 地图更新后新包 vs 旧包, 列出对象表新增/删除的物品与单位。
    比较维度: 对象ID/物品.tsv 与 对象ID/单位.tsv 的 ID 集合 (行内容以 ID 为主键)。
    query 可传子表名过滤 (物品/单位), 空 = 全部。"""
    if not pack_b:
        return ["diff 需要第二个包: pack-query <新包> diff <旧包目录>"]
    old_pack = Path(pack_b)
    if not old_pack.is_dir():
        return ["第二个包目录不存在: " + pack_b]
    tables = (
        "物品",
        "单位",
        "技能",
        "英雄",
    )
    filter_table = query.strip() if query.strip() in tables else ""
    out: list[str] = []
    for table in tables:
        if filter_table and table != filter_table:
            continue
        old_rows = _read_rows(old_pack, f"对象ID/{table}.tsv")
        new_rows = _read_rows(pack, f"对象ID/{table}.tsv")
        if not old_rows and not new_rows:
            continue
        old_by_id = {r[1]: r for r in old_rows[1:] if len(r) > 4}
        new_by_id = {r[1]: r for r in new_rows[1:] if len(r) > 4}
        added = [i for i in new_by_id if i not in old_by_id]
        removed = [i for i in old_by_id if i not in new_by_id]
        changed = [
            i for i in new_by_id if i in old_by_id and new_by_id[i] != old_by_id[i]
        ]
        # 字段级变化也算变更 (物品.tsv 行相同但对象字段.tsv 值不同)
        field_changes = _diff_field_changes(
            old_pack,
            pack,
            table,
            [i for i in new_by_id if i in old_by_id and i not in changed],
        )
        for i, lines in field_changes.items():
            if lines and i not in changed:
                changed.append(i)
        changed.sort()
        if not added and not removed and not changed:
            continue
        out.append(
            f"== {table}: 新增 {len(added)} / 删除 {len(removed)} / 变更 {len(changed)} =="
        )
        for i in added:
            name = _clean(new_by_id[i][4]) if len(new_by_id[i]) > 4 else i
            out.append(f"  + [{i}] {name}")
        for i in removed:
            name = _clean(old_by_id[i][4]) if len(old_by_id[i]) > 4 else i
            out.append(f"  - [{i}] {name}")
        shown = 0
        cap = (
            limit  # 0 = 不限量满量列出 (旧隐性默认 20 已删, 373 轮); 显式 --limit 才截
        )
        if cap <= 0:
            cap = len(changed) + 1  # 不限量: 循环条件恒假等价写法 (cap>len(changed))
        field_changes.update(
            _diff_field_changes(
                old_pack, pack, table, [i for i in changed if i not in field_changes]
            )
        )
        for i in changed:
            if shown >= cap:
                out.append(f"  …… 其余 {len(changed) - shown} 条变更加大 limit 查看")
                break
            name = _clean(new_by_id[i][4]) if len(new_by_id[i]) > 4 else i
            out.append(f"  ~ [{i}] {name}")
            for line in field_changes.get(i, ()):
                out.append("      " + line)
            if i not in field_changes:
                out.append("      (名称/行内容有变化, 字段明细请翻两包 对象字段.tsv)")
            shown += 1

    # 合成配方对比 (改材料/增删配方是 RPG 更新高频项)
    def synth_map(p: Path) -> dict[str, str]:
        result: dict[str, str] = {}
        for r in _read_rows(p, "掉落与获取关系.tsv"):
            if len(r) < 19 or r[2] != "合成":
                continue
            if _clean(r[18]):
                result.setdefault(r[3], _clean(r[18]))
        return result

    old_synths = synth_map(old_pack)
    new_synths = synth_map(pack)
    synth_added = [k for k in new_synths if k not in old_synths]
    synth_removed = [k for k in old_synths if k not in new_synths]
    synth_changed = [
        k for k in new_synths if k in old_synths and new_synths[k] != old_synths[k]
    ]
    if synth_added or synth_removed or synth_changed:
        out.append(
            f"== 合成: 新增 {len(synth_added)} / 删除 {len(synth_removed)} / 变更 {len(synth_changed)} =="
        )
        names = load_items(pack)
        for k in synth_added:
            nm = names.get(k, (k, ""))[0]
            out.append(f"  + [{k}] {nm}  <-  {new_synths[k]}")
        for k in synth_removed:
            nm = names.get(k, (k, ""))[0]
            out.append(f"  - [{k}] {nm}  <-  {old_synths[k]}")
        for k in synth_changed:
            nm = names.get(k, (k, ""))[0]
            out.append(f"  ~ [{k}] {nm}")
            out.append(f"      旧: {old_synths[k]}")
            out.append(f"      新: {new_synths[k]}")
    if not out:
        return ["两包对象表无差异"]
    # 头部插入统计摘要: 一眼看更新规模 (X 段 / Y 处变化)
    sections = sum(1 for line in out if line.startswith("== "))
    total_changes = sum(
        int(part)
        for line in out
        if line.startswith("== ")
        for part in line.replace("=", " ").split()
        if part.isdigit()
    )
    out.insert(0, f"共 {sections} 个差异段, 合计 {total_changes} 项变化")
    return out


def _query_list(pack: Path, query: str, limit: int) -> list[str]:
    """list 按表列出全部对象 ID+名称 (供脚本/AI 消费的纯清单)。
    query 可传表名过滤 (物品/单位/技能/英雄/增益/科技), 空 = 全部表。"""
    del limit  # 满量清单不截断
    tables = (
        "物品",
        "单位",
        "技能",
        "英雄",
        "增益",
        "科技",
        "装饰物",
        "可破坏物",
    )
    want = query.strip()
    out: list[str] = []
    for table in tables:
        if want and table != want:
            continue
        rows = _read_rows(pack, f"对象ID/{table}.tsv")
        if len(rows) <= 1:
            continue
        out.append(f"== {table} ({len(rows) - 1}) ==")
        for r in rows[1:]:
            if len(r) < 5:
                continue
            out.append(f"[{r[1]}] {_clean(r[4])}")
    if not out:
        return [
            "未找到对象表: " + (want or "全表"),
            "  （可用表名: 物品/单位/技能/英雄/增益/科技/装饰物/可破坏物）",
        ]
    return out


def _query_doc(pack: Path, query: str, limit: int) -> list[str]:
    """doc 单对象全景报告: 一个对象一次看全 item/price/where/drop/refs。
    query 是对象四码或名称 (与 item 同语义)。"""
    sections = (
        ("item", "基本信息/效果"),
        ("price", "价格"),
        ("where", "获取途径"),
        ("drop", "掉落"),
        ("refs", "引用分析"),
    )
    out: list[str] = []
    for cmd, title in sections:
        query_fn = _QUERIES[cmd]
        lines = query_fn(pack, query, limit)
        if not lines or lines[0].startswith("未找到"):
            continue
        out.append(f"==== {title} ({cmd}) ====")
        out.extend(lines)
        out.append("")
    if not out:
        return [
            "未找到: "
            + query
            + " (doc 聚合 item/price/where/drop/refs 五个维度, 全部未命中)"
        ]
    return out


def _query_object_list(
    pack: Path, query: str, table: str, missing: str, limit: int = 0
) -> list[str]:
    """List every valid legacy/current record and its complete description."""
    rows = _read_rows(pack, f"对象ID/{table}.tsv")
    if len(rows) <= 1:
        return [missing]
    needle = _clean(query).casefold()
    out: list[str] = []
    total = 0
    for row in rows[1:]:
        if len(row) < 5:
            continue
        total += 1
        code, name = row[1], _clean(row[4])
        custom = row[5].strip() if len(row) > 5 else ""
        note = _clean(row[6]) if len(row) > 6 else ""
        if needle and not any(needle in text.casefold() for text in (code, name, note)):
            continue
        origin = (
            "自定义"
            if custom == "是"
            else "继承基础"
            if custom == "否"
            else "来源未记录"
        )
        out.append(f"[{code}] {name} ({origin})" + (f" — {note}" if note else ""))
    if out:
        note = _truncated_note(out, limit)
        return [*_bounded(out, limit), *([note] if note else [])]
    return [
        "未找到: " + query + " (名称/ID/效果三路过滤)",
        f"  本图{table}表共 {total} 项；可换名称或四码，或用 search <词> 跨八表查说明。",
    ]


def _query_buffs(pack: Path, query: str, limit: int) -> list[str]:
    """Complete 增益 listing, including legacy rows without optional columns."""
    return _query_object_list(
        pack, query, "增益", "本包无 增益.tsv (地图未自定义增益)", limit
    )


def _query_heroes(pack: Path, query: str, limit: int) -> list[str]:
    """Complete 英雄 listing, including legacy rows without optional columns."""
    return _query_object_list(
        pack,
        query,
        "英雄",
        "本包无 英雄.tsv (英雄类单位通常并入 单位 表 — 用 search 查)",
        limit,
    )


def _code_home_hint(pack: Path, query: str) -> str:
    """码在技能/增益表中时给出专属命令提示, 否则返回空串。"""
    code = query.strip()
    for table, cmd in (("技能", "skills"), ("增益", "buffs"), ("英雄", "heroes")):
        for r in _read_rows(pack, "对象ID/" + table + ".tsv")[1:]:
            if len(r) > 4 and (r[1] == code or _clean(r[4]) == code):
                return f"(该码属 {table} — 用 {cmd} {code} 查)"
    return ""


def _query_units(pack: Path, query: str, limit: int) -> list[str]:
    """Complete 单位 listing, including legacy rows without optional columns."""
    return _query_object_list(pack, query, "单位", "本包无 单位.tsv", limit)


def _query_skills(pack: Path, query: str, limit: int) -> list[str]:
    """Complete 技能 listing, including legacy rows without optional columns."""
    return _query_object_list(pack, query, "技能", "本包无 技能.tsv", limit)


def _query_stats(pack: Path, query: str, limit: int) -> list[str]:
    """stats 包总览: 地图信息摘要 + 每张对象表的行数与自定义行数。"""
    del query, limit  # 总览无过滤/截断
    out: list[str] = []
    info = pack / "地图信息.txt"
    if info.exists():
        for line in _iter_tsv_lines(info):
            if line.strip():
                out.append(line)  # 满量: 玩家/队伍/小地图标记段不再 12 行截断
    obj_dir = pack / "对象ID"
    # 导出时间 = 对象表目录 mtime (包重导时刷新), 用户可判断包新旧
    if obj_dir.is_dir():
        import datetime

        exported = datetime.datetime.fromtimestamp(obj_dir.stat().st_mtime)
        out.append(f"导出时间: {exported:%Y-%m-%d %H:%M}")
        out.append("")
    if not info.exists() and not obj_dir.is_dir():
        # 无地图信息也无对象表 = 战役容器级空壳, 返回未找到让分段逻辑跳过
        # (战役场景由分段协议消费; 普通目录则由外层 fallback 给指引)
        if not (pack / "子地图").is_dir():
            return [
                "未找到地图信息 (空包或非资料包目录)。",
                "  （stats 需要 cli <地图> --pack 导出的资料包——先导出再查）",
            ]
        return ["未找到"]
    if out:
        out.append("")
    out.append("==== 对象表总览 ====")
    if not obj_dir.is_dir():
        out.append("本包无对象表")
        return out
    for tsv in sorted(obj_dir.glob("*.tsv")):
        rows = _read_rows(pack, "对象ID/" + tsv.name)
        if len(rows) <= 1:
            continue
        custom_idx = rows[0].index("自定义") if "自定义" in rows[0] else -1
        total = len(rows) - 1
        if custom_idx >= 0:
            custom = sum(
                1
                for r in rows[1:]
                if len(r) > custom_idx and r[custom_idx].strip() == "是"
            )
            out.append(f"{tsv.stem}: {total} 行 (自定义 {custom})")
        else:
            out.append(f"{tsv.stem}: {total} 行")
    # 记忆资产段: again/near 链的用户侧状态一屏可见
    memo = _memo_dir()
    last = _load_last_query()
    history = _memo_dir() / "history.json"
    out.append("")
    out.append("== 查询记忆 ==")
    if last:
        out.append(f"最近查询: {last['command']} {last['query']} (来自 {last['pack']})")
    else:
        out.append("最近查询: (无——成功查询会记入 again 记忆)")
    if history.exists():
        try:
            import json as _json

            entries = _json.loads(history.read_text(encoding="utf-8"))
            out.append(
                f"历史条数: {len(entries)} (历史与 GUI 下拉均全量保留, again 走独立记忆)"
            )
        except OSError, ValueError:
            pass  # 记忆损坏不可读 — 总览其余段落照常, 条数行省略 (非关键披露)
    out.append(f"记忆目录: {memo}")
    return out


def _query_export(pack: Path, query: str, limit: int) -> list[str]:
    """export 单对象全景落盘: doc 报告写临时目录并打印文件路径。
    给 AI/文档喂上下文时复制文件比复制终端输出方便。query 是四码或名称。"""
    lines = _query_doc(pack, query, limit)
    if lines[0].startswith("未找到"):
        return lines
    from .archive_export import tmp_extract_dir

    safe = (
        "".join(char if char not in '\\/:*?"<>|' else "_" for char in query).strip()
        or "object"
    )
    out_dir = tmp_extract_dir("pack-query-export")
    out_path = os.path.join(out_dir, safe + ".md")
    with open(out_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    return [f"已导出: {out_path}", *lines]


_LAST_QUERY_FILE = "pack-query-last.json"


def _memo_dir() -> Path:
    from .cache_root import gamexray_cache_root

    return gamexray_cache_root() / "gui-query-memo"


def _load_last_query() -> dict[str, str] | None:
    """GUI/CLI 共享的最近一次成功查询; 缺失/损坏返回 None (fail-open)。"""
    path = _memo_dir() / _LAST_QUERY_FILE
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        pack, command, query = payload["pack"], payload["command"], payload["query"]
        if (
            not (
                isinstance(pack, str)
                and isinstance(command, str)
                and isinstance(query, str)
            )
            or command == "again"
        ):
            # 拒绝旧 GUI 写下的自引用记忆, placeholder/stats/CLI 统一不消费。
            return None
        return {"pack": pack, "command": command, "query": query}
    except OSError, ValueError, KeyError:
        return None


def _store_last_query(pack: Path, command: str, query: str) -> None:
    if command == "again":
        return  # 重跑不是新查询; 不能覆盖被重跑的原始 pack/command/query。
    try:
        d = _memo_dir()
        d.mkdir(parents=True, exist_ok=True)
        (d / _LAST_QUERY_FILE).write_text(
            json.dumps(
                {"pack": str(pack), "command": command, "query": query},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except OSError:
        pass  # fail-open: 记忆失败不影响查询本身


def _query_again(pack: Path, query: str, limit: int) -> list[str]:
    """again: 重跑最近一次成功查询 (pack/command/query 均从 memo 取)。"""
    del pack, query  # again 全从 memo 取, 入参仅作 dispatcher 签名统一
    last = _load_last_query()
    if last is None or last["command"] == "again":
        return [
            "无最近查询记录 (again 记住上一次成功查询; 先跑任意一次普通查询)",
        ]
    memo_pack = Path(last["pack"])
    if not memo_pack.is_dir():
        return ["最近查询的资料包目录已不存在: " + last["pack"]]
    run_fn = _QUERIES.get(last["command"])
    if run_fn is None:
        return ["最近查询的命令已失效: " + last["command"]]
    return [
        f"[重跑] {last['command']} {last['query']} (来自 {last['pack']})",
        *run_fn(memo_pack, last["query"], limit),
    ]


_QUERIES = {
    "item": _query_item,
    "recipe": _query_recipe,
    "where": _query_where,
    "drop": _query_drop,
    "quest": _query_quest,
    "text": _query_text,
    "price": _query_price,
    "shop": _query_shop,
    "tech": _query_tech,
    "cmd": _query_cmd,
    "refs": _query_refs,
    "near": _query_near,
    "locate": _query_locate,
    "affixes": _query_affix,
    "registered": _query_registered,
    "diff": _query_diff,
    "search": _query_search,
    "list": _query_list,
    "doc": _query_doc,
    "buffs": _query_buffs,
    "again": _query_again,
    "export": _query_export,
    "stats": _query_stats,
    "synth": _query_synth,
    "skills": _query_skills,
    "units": _query_units,
    "heroes": _query_heroes,
}


def _campaign_subpacks(pack: Path) -> list[Path]:
    """战役容器包: 子地图/*/ 各自是独立知识包 (根目录本身无对象表)。

    只有战役导出会生成 子地图/*/ 带表的子包 (容器根自己也有 对象ID),
    因此以子包存在为准, 不看根目录表 (根目录表是容器级, 逐关数据在子包)。"""
    sub = pack / "子地图"
    if not sub.is_dir():
        return []
    return sorted(
        p
        for p in sub.iterdir()
        if p.is_dir()
        and (
            (p / "掉落与获取关系.tsv").is_file()
            or (p / "对象ID").is_dir()
            or (p / "内容清单.json").is_file()
            or (p / "脚本可读文本").is_dir()
        )
    )


def execute_pack_query(options: PackQueryCliOptions) -> PackQueryResult:
    """Run a query and return its result without changing process streams."""
    from .pack_query_execution import QueryBackend, execute_query

    return execute_query(
        options, cast(QueryBackend, cast(object, sys.modules[__name__]))
    )


def run_pack_query_cli(options: PackQueryCliOptions) -> int:
    """Render the shared result; GUI callers use execute_pack_query directly."""

    configure_cli_output()
    result = execute_pack_query(options)
    print(result.render(as_json=options.as_json))
    for diagnostic in result.diagnostics:
        print(diagnostic, file=sys.stderr)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(run_pack_query_cli(parse_pack_query_cli_options(sys.argv[1:])))
