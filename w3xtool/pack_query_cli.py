# -*- coding: utf-8 -*-
"""pack-query 子命令：一次进程内查询地图知识包（物品/配方/坐标/掉落/任务/全文）。

用法：
    uv run main.py pack-query <资料包目录> <子命令> <查询词> [--limit N] (默认全量输出; --limit N 为显式缩减)

子命令：
    item   <名字|四码>   物品属性（金币价; 装备效果取自携带技能属性字段; 真实提示文本优先于继承模板描述）
    recipe <名字|四码>   相关合成配方（作为产物或材料，自动去重）
    where  <名字|四码>   单位/地面物品的放置坐标
    drop   <名字|四码>   获取途径（掉落/商店/触发奖励; 无记录时回落文案级配方/来源线索）
    quest  <关键词>     任务注册文本与剧情对话
    text   <关键词>     全包 TSV 有界搜索
    price  <名字|四码>   金币价（igol 地图价优先, 基础ID继承）
    tech   <名字|四码>   科技卡（最大等级/每级金木费用/效果/前置, 自定义字段优先基础继承）
    cmd    <指令文字>    聊天指令效果链（注册->触发器->条件+动作函数体节选, 免手搓脚本）
    refs   <四码|名>     对象码脚本引用分类（给予/作为材料/生成），零消耗引用=升级链终止（脚本加密图不下终止结论）

设计动机：避免为每次查询写一次性脚本/起多个进程（文件变更通知会拖垮资源
管理器外壳）；全部查询在单次进程内完成，输出有界。
"""

from __future__ import annotations

import csv
import math
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .cli_output import configure_cli_output
from .presentation_safety import single_line_text

__all__ = (
    "PackQueryCliOptionError",
    "PackQueryCliOptions",
    "parse_pack_query_cli_options",
    "run_pack_query_cli",
)

_COMMANDS = (
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
)
_COLOR_RE = re.compile(r"\|c[0-9A-Fa-f]{8}|\|r")


def _clean(text: str) -> str:
    return _COLOR_RE.sub("", text).replace("|n", " ")


def _read_rows(pack_dir: Path, rel: str) -> list[list[str]]:
    path = pack_dir / rel
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.reader(f, delimiter="\t"))


def load_items(pack_dir: Path) -> dict[str, tuple[str, str]]:
    """物品四码 -> (去色名称, 描述)。"""
    out: dict[str, tuple[str, str]] = {}
    for r in _read_rows(pack_dir, "对象ID/物品.tsv"):
        if len(r) > 6 and len(r[1]) == 4:
            out[r[1]] = (_clean(r[4]), _clean(r[6]))
    return out


def load_units(pack_dir: Path) -> dict[str, str]:
    """单位四码 -> 名称。"""
    out: dict[str, str] = {}
    for r in _read_rows(pack_dir, "对象ID/单位.tsv"):
        if len(r) > 4 and len(r[1]) == 4:
            out[r[1]] = _clean(r[4])
    return out


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
        if len(r) > 5 and r[3].removeprefix("base:") not in ("usei", "Sellitems"):
            continue
        codes = []
        for token in r[5].split(","):
            token = token.strip()
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
            out[code.lower()] = {k: v for k, v in entry[1]}
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


def _query_tech(pack: Path, query: str, limit: int) -> list[str]:
    techs = load_techs(pack)
    fields = load_tech_fields(pack)
    bases = _tech_base_fields()
    lines: list[str] = []
    for code, (name, base_id) in techs.items():
        if not _match(query, code, name):
            continue
        f = fields.get(code, {})
        base_f = bases.get(base_id, {})

        def _num(custom_key: str, base_label: str) -> int | None:
            for v in (f.get(custom_key), base_f.get(base_label)):
                if v and v.lstrip("'") not in ("-", "_", "'"):
                    try:
                        return int(float(v))
                    except ValueError:
                        pass
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

            marks = sorted({1, min(5, levels), levels})
            lines.append(
                "  级费用: " + " | ".join(str(n) + "级 " + _cost(n) for n in marks)
            )
            gsum = (
                sum(gold_b + (gold_i or 0) * (n - 1) for n in range(1, levels + 1))
                if gold_b is not None
                else None
            )
            wsum = (
                sum(lum_b + (lum_i or 0) * (n - 1) for n in range(1, levels + 1))
                if lum_b is not None
                else None
            )
            if gsum is not None or wsum is not None:
                lines.append(
                    "  满级累计: "
                    + (("金" + str(gsum) + " ") if gsum is not None else "")
                    + (("木" + str(wsum)) if wsum is not None else "")
                )
        if levels:
            for lv in (1, levels):
                t = f.get("gub1:" + str(lv))
                if t:
                    lines.append("  效果(" + str(lv) + "级): " + t)  # 全文, 不截断
        reqs = sorted((k, v) for k, v in f.items() if k.startswith("greq:"))
        if reqs:
            lines.append(
                "  前置: " + ", ".join(k.split(":", 1)[1] + "级←" + v for k, v in reqs)
            )
        lines.append("")
        if limit and len(lines) >= limit * 8:
            break
    return lines or ["未找到科技: " + query]


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


def load_formulas(pack_dir: Path) -> list[tuple[str, list[tuple[str, int]]]]:
    """解析 YDWENewItemsFormula 调用 -> [(产物四码, [(材料四码, 数量)])]。

    参数形如 ('I06Z', 8, 'I00F', 0, ..., 'I074')：末位是产物，
    其余两两成对 (材料, 数量)，数量<=0 的占位材料会被过滤。
    """
    out: list[tuple[str, list[tuple[str, int]]]] = []
    path = pack_dir / "脚本调用参数索引.tsv"
    if not path.exists():
        return out
    for line in path.open(encoding="utf-8"):
        if "call YDWENewItemsFormula(" not in line:
            continue
        tail = line.split("call YDWENewItemsFormula(", 1)[1].rstrip().rstrip(")")
        toks = [t.strip() for t in tail.split(",")]
        if len(toks) < 3:
            continue
        try:
            pairs = [
                (toks[i].strip("'"), int(float(toks[i + 1].replace(" ", ""))))
                for i in range(0, len(toks) - 1, 2)
            ]
        except ValueError:
            continue
        out.append(
            (toks[-1].strip("'"), [(c, k) for c, k in pairs if k > 0 and c != "ches"])
        )
    return out


def load_placements(pack_dir: Path) -> list[tuple[str, float, float, str]]:
    """脚本创建的单位/地面物品 -> [(四码, x, y, 'unit'|'item')]。"""
    out: list[tuple[str, float, float, str]] = []
    path = pack_dir / "脚本调用参数索引.tsv"
    if not path.exists():
        return out
    for line in path.open(encoding="utf-8"):
        if "=CreateUnit(p, '" in line:
            tail = line.split("=CreateUnit(p, '", 1)[1]
            parts = tail.rstrip().rstrip(")").split(", ")
            if len(parts) < 3:
                continue
            try:
                x = float(parts[1].replace(" ", ""))
                y = float(parts[2].replace(" ", ""))
            except ValueError:
                continue
            out.append((parts[0].strip("'"), x, y, "unit"))
        elif "call CreateItem('" in line:
            tail = line.split("call CreateItem('", 1)[1]
            parts = tail.rstrip().rstrip(")").split(", ")
            if len(parts) < 3:
                continue
            try:
                x = float(parts[1].replace(" ", ""))
                y = float(parts[2].replace(" ", ""))
            except ValueError:
                continue
            out.append((parts[0].strip("'"), x, y, "item"))
    return out


@dataclass(frozen=True, slots=True)
class PackQueryCliOptions:
    """pack-query 子命令的已解析参数。"""

    pack_dir: str
    command: str
    query: str
    limit: int = 0  # 0 = 不限量 (满量输出); --limit N 显式缩减


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
    command = rest[1] if len(rest) > 1 else ""
    if command == "near" and len(rest) in (4, 5):
        rest = rest[:2] + [" ".join(rest[2:])]
    if len(rest) != 3:
        raise PackQueryCliOptionError(
            "用法: pack-query <资料包目录> <item|recipe|where|drop|quest|text|price|shop|tech|cmd|refs|near|locate> <查询词>"
            + ("  (near 用法: near <x> <y> [radius])" if command == "near" else "")
        )
    pack_dir, query = rest[0], rest[2]
    if command not in _COMMANDS:
        raise PackQueryCliOptionError(
            "未知子命令: " + command + " (可选: " + ",".join(_COMMANDS) + ")"
        )
    if not query.strip():
        raise PackQueryCliOptionError("查询词不能为空")
    return PackQueryCliOptions(
        pack_dir=pack_dir, command=command, query=query.strip(), limit=limit
    )


def _match(query: str, code: str, name: str) -> bool:
    q = query.lower()
    return q == code.lower() or q in name.lower() or name.lower() in q


def _query_locate(pack: Path, query: str, limit: int) -> list[str]:
    """特征码交集: 多个对象码同时出现在本图时报告命中 (战役任务关识别)。

    战役工作流第④步的机械化: live 拿英雄/随从/物品四码, 用本命令扫
    脚本对象码出现索引.tsv, 「全部码都出现」的子图即候选任务关——
    容器包由 run_pack_query_cli 自动逐关分段 (== 子地图 名 ==)。"""
    codes = [c.strip() for c in re.split(r"[;,，；\s]+", query) if c.strip()]
    if not codes:
        return ["用法: locate <码1;码2;...> (特征码交集, 全部码都出现才算命中)"]
    rows = _read_rows(pack, "脚本对象码出现索引.tsv")
    if not rows:
        return ["未找到 脚本对象码出现索引.tsv（资料包未导出脚本索引）"]
    counts: dict[str, int] = {c.lower(): 0 for c in codes}
    for r in rows:
        if len(r) < 4:
            continue
        key = r[3].lower()
        if key in counts:
            counts[key] += 1
    missing = [c for c in codes if counts[c.lower()] == 0]
    if missing:
        return ["未找到: 缺少 " + "、".join(missing) + "（特征码未全部出现）"]
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
    for code, (name, desc) in items.items():
        if _match(query, code, name):
            lines.append("[" + code + "] " + name)
            price = _item_price(bases, code, overrides)
            base = bases.get(code, "")
            if price:
                src = (
                    "地图价"
                    if code in overrides
                    else ("继承基础 " + base if base else "")
                )
                lines.append("  金币: " + price + (" (" + src + ")" if src else ""))
            # 装备真实效果（iabi 携带技能的属性字段，自定义行优先）。
            if code in equipped_effects:
                lines.append("  装备效果: " + ", ".join(equipped_effects[code]))
            # 真实提示文本（地图自定义 ides/utub）优先；继承模板描述仅作兜底。
            lines.append("  " + (tooltips.get(code, "") or desc))  # ides/utub 全文
            if limit and len(lines) >= limit * 3:
                break
    return lines or ["未找到物品: " + query]


def _query_price(pack: Path, query: str, limit: int) -> list[str]:
    items = load_items(pack)
    bases = load_item_bases(pack)
    overrides = load_item_gold_overrides(pack)
    lines = []
    for code, (name, _desc) in items.items():
        if _match(query, code, name):
            price = _item_price(bases, code, overrides)
            base = bases.get(
                code, code.lower() if code.lower() in _base_prices() else "-"
            )
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
            if limit and len(lines) >= limit:
                break
    if not lines:
        price = _base_prices().get(query.lower())
        if price:
            lines.append("基础物品 [" + query.lower() + "]  金币: " + price)
    return lines or ["未找到物品价格: " + query]


def _query_shop(pack: Path, query: str, limit: int) -> list[str]:
    """按商店列出售清单与逐件真实价格（igol 地图价优先，回落基础继承价）。"""
    items = load_items(pack)
    bases = load_item_bases(pack)
    overrides = load_item_gold_overrides(pack)
    lines: list[str] = []
    stocked: set[str] = set()
    for shop_code, shop_name, codes in load_shop_stocks(pack):
        if not _match(query, shop_code, shop_name):
            continue
        stocked.add(shop_code)
        lines.append("== " + shop_name + " [" + shop_code + "]")
        for c in codes:
            name = items.get(c, (c, ""))[0]
            price = _item_price(bases, c, overrides)
            tag = "地图价" if c in overrides else "继承"
            lines.append(
                "  " + name + "  " + (price or "?") + "金  (" + tag + " " + c + ")"
            )
        lines.append("")
        if limit and len(lines) >= limit * 12:
            break
    # 商店制造 (关系表独立通道): 奇迹古树/神秘藏宝室这类制造商店没有
    # usei 货架, 只靠 stock 扫描会答「未找到商店」
    craft: dict[str, tuple[str, list[tuple[str, str]]]] = {}
    for r in _read_rows(pack, "掉落与获取关系.tsv"):
        if len(r) < 8 or r[2] != "商店制造":
            continue
        code = r[6]
        if not code:
            continue
        entry = craft.setdefault(code, (_clean(r[7]) or code, []))
        pair = (r[3], _clean(r[4]))
        if pair not in entry[1]:
            entry[1].append(pair)
    for code, (name, entries) in craft.items():
        if not _match(query, code, name):
            continue
        lines.append("== " + name + " [" + code + "]  (商店制造)")
        for icode, iname in entries:
            lines.append("  制造 " + iname + " [" + icode + "]")
        lines.append("")
    # 关系表「商店出售」行: 货架字段缺失时的另一证据源——战役容器商店
    # (h704 银月配方商) 只有关系行, 对象字段无自定义 usei, 曾答未找到
    sell: dict[str, tuple[str, list[str]]] = {}
    for r in _read_rows(pack, "掉落与获取关系.tsv"):
        if len(r) < 8 or r[2] != "商店出售":
            continue
        code = r[6]
        if not code:
            continue
        entry = sell.setdefault(code, (_clean(r[7]) or code, []))
        item = _clean(r[4]) + " [" + r[3] + "]"
        if item not in entry[1]:
            entry[1].append(item)
    for code, (name, entries) in sell.items():
        if code in stocked or not _match(query, code, name):
            continue
        lines.append("== " + name + " [" + code + "]  (关系表出售)")
        for item in entries:
            lines.append("  " + item)
        lines.append("")
    return lines or ["未找到商店: " + query]


def _query_recipe(pack: Path, query: str, limit: int) -> list[str]:
    items = load_items(pack)
    hits: list[str] = []
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
        if not (
            _match(query, prod, pname)
            or (r[17] and query.lower() in r[17].lower())
            or query in mats
        ):
            continue
        key = (prod, mats)
        if key in seen_rels:
            continue
        seen_rels.add(key)
        hits.append("[" + prod + "] " + pname + "  <-  " + mats)
        if limit and len(hits) >= limit:
            break
    for prod, pairs in load_formulas(pack):
        key = (prod, tuple(pairs))
        if key in seen:
            continue
        seen.add(key)
        prod_name = items.get(prod, (prod, ""))[0]
        mat_names = [items.get(c, (c, ""))[0] for c, _k in pairs]
        if _match(query, prod, prod_name) or any(
            _match(query, c, n) for (c, _k), n in zip(pairs, mat_names, strict=False)
        ):
            need = " + ".join(
                n + "x" + str(k) for (_c, k), n in zip(pairs, mat_names, strict=False)
            )
            hits.append("[" + prod + "] " + prod_name + "  <-  " + need)
            if limit and len(hits) >= limit:
                break
    return hits or ["未找到相关配方: " + query]


def _query_where(pack: Path, query: str, limit: int) -> list[str]:
    items = load_items(pack)
    units = load_units(pack)
    names: dict[str, str] = {**units, **{c: n for c, (n, _d) in items.items()}}
    lines = []
    for code, x, y, kind in load_placements(pack):
        name = names.get(code, code)
        if _match(query, code, name):
            tag = "单位" if kind == "unit" else "地面物品"
            lines.append(
                "["
                + code
                + "] "
                + name
                + " ("
                + tag
                + ") -> ("
                + f"{x:.0f}"
                + ", "
                + f"{y:.0f}"
                + ")"
            )
            if limit and len(lines) >= limit:
                break
    # 预放置之外满量附上关系行 (I01F 事故: 任务物品无预放置点,
    # 关系行明明存在却被跳过, 文案兜底还按描述子串错配到别的物品;
    # 有预放置也有关系行的物品两类证据都给, 不静默吞掉)
    for r in _read_rows(pack, "掉落与获取关系.tsv"):
        if len(r) < 7:
            continue
        code, name = r[3], _clean(r[4])
        if not _match(query, code, name):
            continue
        lines.append(
            name + " [" + code + "]  " + r[2] + " <- " + r[5] + " " + r[6]
        )
        if limit and len(lines) >= limit:
            break
    # 来源侧: 查询词本身是来源 (可破坏物/商人/单位) 时, 关系表装备列
    # 不匹配也要给出来源侧行 (路障 B007 掉三件物品, 两个命令曾都答未找到)
    for r in _read_rows(pack, "掉落与获取关系.tsv"):
        if len(r) < 8:
            continue
        src_name = _clean(r[7])
        if not _match(query, r[6], src_name):
            continue
        lines.append(
            "来源 " + src_name + "[" + r[6] + "]: " + r[2]
            + " -> " + _clean(r[4]) + " [" + r[3] + "]"
        )
        if limit and len(lines) >= limit:
            break
    # 使用触发随机产出 (宝箱开箱): 数组池内容静态可解, 满量列出
    script = load_script(pack)
    if script is not None:
        for code, (name, _d) in items.items():
            if not _match(query, code, name):
                continue
            lines.extend(_script_use_item_loot(script, code, names))
            lines.extend(
                _item_trigger_grant_lines(
                    script, [code], lambda c: names.get(c, c)
                )
            )
    if not lines:
        # 单位查询不该吃物品文案兜底 (邪恶陨石人的任务文本曾被端出来
        # 当「炎石守卫」的来源线索)——路由到 drop 的单位反查
        for ucode, uname in load_units(pack).items():
            if _match(query, ucode, uname):
                return [
                    "未找到 [" + ucode + "] " + uname + " 的预放置/关系表记录。",
                    "单位掉落查询用 drop <单位名或码> (按单位反查死亡触发)。",
                ]
        hints = _tooltip_source_hints(pack, _hint_targets(pack, query), limit)
        if hints:
            head = (
                "⚠ 文案级来源线索 (无预放置/关系表记录"
                + ("; 脚本加密" if _script_encrypted(pack) else "")
                + "; 未脚本验证):"
            )
            return [head] + ["  " + h for h in _bounded(hints, limit)]
    return lines or ["未找到放置记录: " + query]


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
        except (ValueError, UnicodeDecodeError):
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


def _script_use_item_loot(
    script: str, code: str, names: dict[str, str]
) -> list[str]:
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
    var_by_cond = {fn: var for var, fn in _ADD_COND_RE.findall(script)}
    act_by_var = dict(_ADD_ACTION_RE.findall(script))
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
        var = var_by_cond.get(stem + "Conditions")
        act = act_by_var.get(var or "")
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


def _trigger_events(script: str, var: str) -> set[str]:
    """触发器变量注册的事件集合 (在变量名之后的窗口里找 EVENT_* 字面量)。"""
    events: set[str] = set()
    for m in re.finditer(re.escape(var) + r"[^)\n]*", script):
        seg = script[m.start() : m.start() + 400]
        events.update(re.findall(r"EVENT_\w+", seg))
    return events


def _item_trigger_blocks(script: str) -> list[tuple[str, list[str], str, set[str]]]:
    """反应 GetManipulatedItem 的触发块 (stem, 条件物品码, 动作体, 事件集)。

    双形态: ①Trig_*Conditions/Trig_*Actions 成对 (wbc 开箱);
    ②动作体自判 (hxsj TBX/JFDH/SJSRWPGM 兑换系统——条件函数不存在,
    物品判定与发放都在 action 里)。事件集区分拾取/使用维度。"""
    var_by_cond = {fn: var for var, fn in _ADD_COND_RE.findall(script)}
    act_by_var = dict(_ADD_ACTION_RE.findall(script))
    var_by_action = {fn: var for var, fn in _ADD_ACTION_RE.findall(script)}
    blocks: list[tuple[str, list[str], str, set[str]]] = []
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
        var = var_by_cond.get(stem + "Conditions")
        act = act_by_var.get(var or "")
        if not act:
            continue
        body = _fn_body(script, act)
        if body == "(未找到函数体)":
            continue
        seen_bodies.add(act)
        events = _trigger_events(script, var) if var else set()
        blocks.append((stem, codes, body, events))
    for m in _FN_ALL_RE.finditer(script):
        name = m.group(1)
        if name in seen_bodies:
            continue
        body = m.group(2)
        if "GetManipulatedItem" not in body:
            continue
        codes = [
            _fourcc(x.group(1), x.group(2))
            for x in _USE_ITEM_COND_RE.finditer(body)
        ]
        codes = [c for c in codes if c]
        if not codes:
            continue
        var = var_by_action.get(name)
        events = _trigger_events(script, var) if var else set()
        stem = name[: -len("Actions")] if name.endswith("Actions") else name
        blocks.append((stem, codes, body, events))
    return blocks


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
        kind = (
            "拾取" if "EVENT_PLAYER_UNIT_PICKUP_ITEM" in events else "使用"
        )
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


def _script_pool_drops(pack: Path, code: str) -> list[str]:
    """死亡触发兜底: 关系表无该单位掉落行时, 扫 GetDyingUnit 条件的两种形态。

    ①奖池 PlaceRandomItem —— 输出仍是"池子 N 选 1"形态, 不写成固定掉落;
    ②直落 CreateItemLoc/UnitAddItemByIdSwapped —— 奖池扫描看不见的
    "死亡位置直发"写法 (BossFH 直落 I01F 曾被漏报为"无掉落记录")。"""
    script = load_script(pack)
    if script is None or len(code) != 4:
        return []
    want = "'" + code.lower() + "'"
    want_hex = "$" + code.encode("ascii", "replace").hex()
    var_codes = _unit_var_codes(script)
    var_by_cond = {fn: var for var, fn in _ADD_COND_RE.findall(script)}
    act_by_var = dict(_ADD_ACTION_RE.findall(script))
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
        var = var_by_cond.get(m.group(1) + "Conditions")
        act = act_by_var.get(var or "")
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
        out.append(f"{label} [{code}]  ⚠ 脚本死亡奖池 (关系表无此掉落记录):")
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
    return out


_FN_ALL_RE = re.compile(
    r"function\s+(\w+)\s+takes[^\n]*\n(.*?)endfunction",
    re.S,
)


def _death_blocks(script: str) -> list[tuple[str, str, str, str]]:
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
    return blocks


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
            out.append(f"{iname} [{code}]  ⚠ 脚本死亡位置直落 (关系表无此掉落记录):")
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
            rows.append(
                f"  死亡触发 {stem} -> 直落: {dname} [{icode}]: {snippet}"
            )
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
            gate = (
                _balanced_call(action_body, prior[-1].start()) if prior else "无掷骰"
            )
            direct.append(f"{name_of(icode)}({icode}) 掷骰:{gate}")
        pools: list[str] = []
        for pvar, pidx in _PLACE_POOL_RE.findall(action_body):
            regs = pool_items.get((pvar, pidx), [])
            if not regs:
                continue
            total = sum(w for _, w in regs) or 1.0
            inner = "、".join(
                f"{name_of(ic)}({ic}) {w:g}/{total:g}" for ic, w in regs
            )
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
                "上架商店 "
                + "、".join(f"{name_of(sc)}({sc})" for sc in stock_items)
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
        line = (
            f"- {header}  ⚠ 脚本死亡掉落 ({stem}, 关系表外证据): "
            + "；".join(parts)
        )
        if line in seen:
            continue
        seen.add(line)
        out.append(line)
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
    q = query.lower()
    lines = []
    kinds = set()
    first_code = ""
    for r in _read_rows(pack, "掉落与获取关系.tsv"):
        if len(r) < 7:
            continue
        code, name = r[3], _clean(r[4])
        if not (
            q == code.lower() or (name and (q in name.lower() or name.lower() in q))
        ):
            continue
        kinds.add(r[2])
        if not first_code:
            first_code = code
        lines.append(name + " [" + code + "]  " + r[2] + " <- " + r[5] + " " + r[6])
        if limit and len(lines) >= limit:
            break
    if not lines:
        # 来源侧: 查询词是来源 (可破坏物/商人/单位) 时给出来源侧关系行,
        # 曾让「路障掉什么」直接落到「未找到获取途径」
        src_hits: list[str] = []
        for r in _read_rows(pack, "掉落与获取关系.tsv"):
            if len(r) < 8:
                continue
            src_name = _clean(r[7])
            if not _match(query, r[6], src_name):
                continue
            src_hits.append(
                src_name
                + "["
                + r[6]
                + "] "
                + r[2]
                + " -> "
                + _clean(r[4])
                + " ["
                + r[3]
                + "]"
            )
            if limit and len(src_hits) >= limit:
                break
        if src_hits:
            return src_hits
        cands = (
            [query] if len(query) == 4 and query.isascii() and query.isalnum() else []
        )
        if not cands:
            for ucode, uname in load_units(pack).items():
                if q in uname.lower():
                    cands.append(ucode)
                if len(cands) >= 3:
                    break
        if not cands:
            # 按物品名问「打谁掉」也要进死亡扫描 (I01F 按名查询拿不到直落证据的事故)
            for icode, (iname, _idesc) in load_items(pack).items():
                if q in iname.lower():
                    cands.append(icode)
                if len(cands) >= 3:
                    break
        all_units = load_units(pack)
        for cand in cands:
            got = _script_pool_drops(pack, cand)
            if cand in all_units or cand.upper() in all_units:
                # 物品维度直落扫描按物品码匹配 CreateItemLoc 参数,
                # 单位做查询词(按名或直接敲单位码)都反不进去——
                # 按单位表归属判定, 补单位维度反查
                script = load_script(pack)
                if script is not None:
                    got = got + _script_unit_direct_drops(
                        script, cand, load_items(pack), all_units
                    )
            if got:
                return got
        for ucode, uname in load_units(pack).items():
            if _match(query, ucode, uname):
                return [
                    "[" + ucode + "] " + uname + " 无死亡触发直落/奖池证据。",
                    "位置/获取查询用 where <词>。",
                ]
        hints = _tooltip_source_hints(pack, _hint_targets(pack, query), limit)
        if hints:
            head = (
                "⚠ 文案级配方/来源线索 (关系表与脚本奖池无记录"
                + ("; 脚本加密" if _script_encrypted(pack) else "")
                + "; 未脚本验证——合成/掉落触发以实际游戏为准):"
            )
            return [head] + ["  " + h for h in _bounded(hints, limit)]
        return ["未找到获取途径: " + query]
    if not any("掉落" in k for k in kinds):
        scan_code = (
            query
            if len(query) == 4 and query.isascii() and query.isalnum()
            else first_code
        )
        script_evidence = (
            _script_pool_drops(pack, scan_code)
            if scan_code and len(scan_code) == 4
            else []
        )
        if script_evidence:
            lines.append(
                "⚠ 防呆: 关系表无 Boss/单位死亡掉落行, 但脚本死亡触发有直发证据"
                + "(见下); NPC 随身携带仍不构成掉落证据"
            )
            lines.extend(script_evidence)
        else:
            lines.append(
                "⚠ 防呆: 该物品无 Boss/单位死亡掉落记录(仅 "
                + "/".join(sorted(kinds))
                + ")——不得断言打怪掉落; NPC 随身携带不构成掉落证据"
            )
    return lines


def _query_quest(pack: Path, query: str, limit: int) -> list[str]:
    lines = []
    path = pack / "脚本字符串索引.tsv"
    if path.exists():
        for line in path.open(encoding="utf-8"):
            if query in line and (
                "CreateQuestBJ" in line or "DisplayTimedTextToForce" in line
            ):
                lines.append(_clean(line.rstrip("\n")))  # 整行, 不开窗
                if limit and len(lines) >= limit:
                    break
    return lines or ["未找到任务文本: " + query]


def _query_text(pack: Path, query: str, limit: int) -> list[str]:
    lines = []
    for path in sorted(pack.glob("*.tsv")):
        try:
            for line in path.open(encoding="utf-8"):
                if query in line:
                    lines.append(path.name + ": " + _clean(line.rstrip("\n")))  # 整行
                    break
        except OSError:
            continue
        if limit and len(lines) >= limit:
            break
    return lines or ["未找到文本: " + query]


_CHAT_REG_RE = re.compile(
    r"TriggerRegisterPlayerChatEvent\(\s*(gg_trg_\w+)\s*,\s*"
    r"([A-Za-z_]\w*(?:\((?:[^()]|\([^()]*\))*\))?)\s*,\s*"
    r'"([^"]*)"\s*,\s*(true|false)\s*\)'
)
_ADD_ACTION_RE = re.compile(r"TriggerAddAction\(\s*(gg_trg_\w+)\s*,\s*function\s+(\w+)")
_ADD_COND_RE = re.compile(
    r"TriggerAddCondition\(\s*(gg_trg_\w+)\s*,\s*Condition\(function\s+(\w+)\)"
)


def load_script(pack_dir: Path) -> str | None:
    """脚本可读文本/*.j 全文（\r 归一为 \n），无则 None。"""
    d = pack_dir / "脚本可读文本"
    if not d.is_dir():
        return None
    for p in sorted(d.glob("*.j")):
        try:
            return p.read_text(encoding="utf-8", errors="replace").replace("\r", "\n")
        except OSError:
            continue
    return None


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


def _tooltip_source_hints(pack_dir: Path, targets: set[str], limit: int) -> list[str]:
    """文案层获取线索兜底：其他对象说明文本提到目标物品名（配方/掉落来源）。

    关系表与脚本奖池都无记录时使用——输出必须带"文案级"标注（未脚本验证）。"""
    if not targets:
        return []
    out: list[str] = []
    for code, (name, desc) in load_items(pack_dir).items():
        if not desc or name in targets:
            continue
        if next((t for t in sorted(targets) if t in desc), None) is None:
            continue
        excerpt = desc  # 说明全文
        out.append(f"{name} [{code}] 说明: {excerpt}")
        if limit and len(out) >= limit:
            break
    return out


def _fn_body(script: str, fn: str) -> str:
    i = script.find("function " + fn + " takes")
    if i < 0:
        return "(未找到函数体)"
    j = script.find("endfunction", i)
    body = script[i : (j + len("endfunction")) if j >= 0 else len(script)]
    return " ".join(body.split())  # 满量: 函数体全文, 不设字符上限


_RECT_DEF_RE = re.compile(
    r"set\s+(gg_rct_\w+)\s*=\s*Rect\(\s*(-?\s?[\d.]+)\s*,\s*(-?\s?[\d.]+)\s*,"
    r"\s*(-?\s?[\d.]+)\s*,\s*(-?\s?[\d.]+)\s*\)"
)
_CREATE_UNIT_RE = re.compile(
    r"CreateUnit\s*\(\s*\w+\s*,\s*'(\w{4})'\s*,\s*(-?\s?[\d.]+)\s*,\s*(-?\s?[\d.]+)"
)


def _coord_columns(header: list[str]) -> tuple[int, int]:
    """按表头名取 X/Y 列（防列位漂移）；无表头时退回 3/4。"""
    try:
        return header.index("X"), header.index("Y")
    except ValueError:
        return 3, 4


def _num(s: str) -> float:
    return float(s.replace(" ", ""))


def _source_drop_map(pack: Path) -> dict[str, str]:
    """来源ID -> 掉落物品清单 (关系表 掉落 行, 供 near 就近注解)。"""
    drops: dict[str, list[str]] = {}
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
    return {code: "、".join(items) for code, items in drops.items()}


def _query_near(pack: Path, query: str, limit: int) -> list[str]:
    """坐标反查: near <x> <y> [radius=3000] —— 脚底/附近内容物。

    表头驱动解析预放置表列位；Rect 负号带空格(- 5184.0)统一归一；装饰物聚类报告。"""
    parts = query.split()
    if len(parts) not in (2, 3):
        return ["用法: near <x> <y> [radius=3000]"]
    try:
        px, py = float(parts[0]), float(parts[1])
        radius = float(parts[2]) if len(parts) == 3 else 3000.0
    except ValueError:
        return ["坐标与半径必须是数字: near <x> <y> [radius]"]
    radius = max(50.0, min(radius, 20000.0))
    lines = [f"== 坐标 ({px:g}, {py:g}) 半径 {radius:g} =="]
    drop_map = _source_drop_map(pack)

    def dist(x: float, y: float) -> float:
        return math.hypot(x - px, y - py)

    for rel, kind in (("预放置单位.tsv", "单位"), ("预放置装饰物.tsv", "装饰")):
        rows = _read_rows(pack, rel)
        if not rows:
            continue
        cx_i, cy_i = _coord_columns(rows[0])
        entries: dict[tuple[str, str], list[tuple[float, float]]] = {}
        nearest: list[tuple[float, str]] = []
        for r in rows[1:]:
            if len(r) <= max(cx_i, cy_i):
                continue
            try:
                x, y = float(r[cx_i]), float(r[cy_i])
            except ValueError:
                continue
            d = dist(x, y)
            nearest.append((d, f"{r[2] if len(r) > 2 else r[1]} [{r[1]}]"))
            if d <= radius:
                key = (r[1], r[2] if len(r) > 2 else r[1])
                entries.setdefault(key, []).append((x, y))
        if kind == "单位":
            hits = sorted(
                ((k[0], k[1], xs) for k, xs in entries.items()),
                key=lambda t: dist(
                    sum(p[0] for p in t[2]) / len(t[2]),
                    sum(p[1] for p in t[2]) / len(t[2]),
                ),
            )
            for code, name, xs in _bounded(hits, limit):
                cx = sum(p[0] for p in xs) / len(xs)
                cy = sum(p[1] for p in xs) / len(xs)
                drop = f"  掉: {drop_map[code]}" if code in drop_map else ""
                lines.append(
                    f"  {kind}: {name} [{code}] ×{len(xs)} @({cx:g},{cy:g}) 距{dist(cx, cy):.0f}{drop}"
                )
        else:
            clusters: list[tuple[float, str, int, float, float]] = []
            for (code, name), pts in entries.items():
                remaining = list(pts)
                while remaining:
                    seed = remaining[0]
                    group = [
                        p
                        for p in remaining
                        if math.hypot(p[0] - seed[0], p[1] - seed[1]) < 1200
                    ]
                    remaining = [p for p in remaining if p not in group]
                    gcx = sum(p[0] for p in group) / len(group)
                    gcy = sum(p[1] for p in group) / len(group)
                    clusters.append(
                        (dist(gcx, gcy), f"{name} [{code}]", len(group), gcx, gcy)
                    )
            clusters.sort()
            for d, label, n, gcx, gcy in _bounded(clusters, limit):
                code = label.rsplit("[", 1)[-1].rstrip("]") if "[" in label else ""
                drop = f"  掉: {drop_map[code]}" if code in drop_map else ""
                lines.append(
                    f"  {kind}群: {label} ×{n} @({gcx:g},{gcy:g}) 距{d:.0f}{drop}"
                )
        if not entries and nearest:
            nearest.sort()
            for d, label in nearest:  # 半径外最近全部列出
                lines.append(f"  (半径外最近{kind}: {label} 距{d:.0f})")

    script = load_script(pack)
    if script:
        in_rect: list[str] = []
        for m in _RECT_DEF_RE.finditer(script):
            x1, y1, x2, y2 = (_num(m.group(i)) for i in range(2, 6))
            if min(x1, x2) <= px <= max(x1, x2) and min(y1, y2) <= py <= max(y1, y2):
                in_rect.append(m.group(1))
        if in_rect:
            lines.append("  所在矩形: " + ", ".join(in_rect))  # 全部
        spawned = []
        for m in _CREATE_UNIT_RE.finditer(script):
            x, y = _num(m.group(2)), _num(m.group(3))
            d = dist(x, y)
            if d <= radius:
                spawned.append((d, m.group(1), x, y))
        spawned.sort()
        for d, code, x, y in _bounded(spawned, limit):
            name = load_units(pack).get(code, code)
            drop = f"  掉: {drop_map[code]}" if code in drop_map else ""
            lines.append(
                f"  脚本单位: {name} [{code}] @({x:g},{y:g}) 距{d:.0f}{drop}"
            )
    return lines


def _query_cmd(pack: Path, query: str, limit: int) -> list[str]:
    script = load_script(pack)
    if script is None:
        return ["未找到脚本 (脚本可读文本/*.j)——该包可能未导出可读脚本"]
    exact_hits: dict[str, tuple[str, str, int]] = {}
    loose_hits: dict[str, tuple[str, str, int]] = {}
    for m in _CHAT_REG_RE.finditer(script):
        var, cmd, exact = m.group(1), m.group(3), m.group(4)
        if cmd == query:
            bucket = exact_hits
        elif query in cmd or (cmd in query and len(cmd) > 1):
            bucket = loose_hits
        else:
            continue
        v = bucket.setdefault(var, (cmd, exact, 0))
        bucket[var] = (v[0], v[1], v[2] + 1)
    regs = exact_hits or loose_hits
    if not regs:
        return ["未找到聊天指令: " + query]
    actions = dict(_ADD_ACTION_RE.findall(script))
    conds = dict(_ADD_COND_RE.findall(script))
    lines: list[str] = []
    for var, (cmd, exact, count) in sorted(regs.items(), key=lambda kv: -kv[1][2]):
        if limit and len(lines) >= limit * 6:
            break
        lines.append(
            f'指令 "{cmd}" ({"精确" if exact == "true" else "前缀"}, 注册{count}个玩家位) -> {var}'
        )
        cond = conds.get(var)
        if cond:
            lines.append("  条件: " + _fn_body(script, cond))
        act = actions.get(var)
        lines.append(
            "  动作: " + _fn_body(script, act)
            if act
            else "  动作: (未找到 TriggerAddAction)"
        )
        lines.append("")
    return lines


_GIVE_MECHS = ("UnitAddItem", "CreateItem")
_GIVE_DIGEST_MARKS = (
    "call UnitAddItem",
    "call CreateItem",
    "=CreateUnit",
    "call CreateNUnitsAtLoc",
)
_CONSUME_MARKS = ("GetItemTypeId", "UnitHasItemOfType", "GetItemOfType", "RemoveItem")


def _ref_kind(mech: str, digest: str) -> str:
    """单条对象码引用的形态: give=给予/创建, consume=作为材料或触发媒介, other。

    机制列常为笼统的 ObjectCode，native 名在摘要里，两处都嗅。"""
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
        return ["未找到 脚本对象码出现索引.tsv（资料包未导出脚本索引）"]
    q = query.lower()
    give: list[tuple[str, str, str]] = []
    consume: list[tuple[str, str, str]] = []
    other: list[tuple[str, str, str]] = []
    label = query
    obj_kind = ""
    for r in rows:
        if len(r) < 11:
            continue
        code, kind, name, fn, mech, digest = r[3], r[5], _clean(r[6]), r[2], r[9], r[10]
        if len(code) != 4 or not (
            q == code.lower() or (name and (q in name.lower() or name.lower() in q))
        ):
            continue
        if not (give or consume or other):
            label = f"[{code}] {name}"
            obj_kind = kind
        entry = (r[1], fn, mech + " " + digest)  # 引用摘录全文
        bucket = _ref_kind(mech, digest)
        (
            give if bucket == "give" else consume if bucket == "consume" else other
        ).append(entry)
    if not (give or consume or other):
        return ["未找到引用: " + query]
    lines = [f"{label}  ({obj_kind})  共{len(give) + len(consume) + len(other)}处引用"]
    lines.append(f"  给予/创建: {len(give)} 处")
    lines.extend(f"    行{e[0]} {e[1]}  {e[2]}" for e in _bounded(give, limit))
    lines.append(f"  作为材料/触发媒介(被检测或移除): {len(consume)} 处")
    lines.extend(f"    行{e[0]} {e[1]}  {e[2]}" for e in _bounded(consume, limit))
    if other:
        lines.append(f"  其他引用: {len(other)} 处")
        lines.extend(f"    行{e[0]} {e[1]}  {e[2]}" for e in _bounded(other, limit))
    if obj_kind == "物品" and give and not consume:
        if _script_encrypted(pack):
            lines.append(
                "  ⚠ 脚本加密: 消耗引用不可读, '终止'结论不成立——"
                "先用 pack-query drop <物品名> 查文案级配方线索"
            )
        else:
            lines.append(
                "  ⚠ 零消耗引用: 该物品没有任何'作为材料被检测/移除'的记录 -> 升级链在此终止"
            )
            lines.append(
                "    (名字带[N/M]不证明存在下一级; 报'可升级'前必须有消耗它的配方证据)"
            )
    return lines


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
}


def _campaign_subpacks(pack: Path) -> list[Path]:
    """战役容器包: 子地图/*/ 各自是独立知识包 (根目录本身无对象表)。

    只有战役导出会生成 子地图/*/ 带表的子包 (容器根自己也有 对象ID),
    因此以子包存在为准, 不看根目录表 (根目录表是容器级, 逐关数据在子包)。"""
    sub = pack / "子地图"
    if not sub.is_dir():
        return []
    return sorted(
        p for p in sub.iterdir() if p.is_dir() and (p / "掉落与获取关系.tsv").exists()
    )


def run_pack_query_cli(options: PackQueryCliOptions) -> int:
    """执行查询并打印结果；返回 0（有结果）或 2（无结果）。

    战役容器包 (子地图/*/) 自动逐关查询并以「== 子地图 名 ==」分段——
    容器 guide 只有容器级信息, 逐关数据都在子地图包里 (旧版直接答未找到)。"""
    configure_cli_output()
    pack = Path(options.pack_dir)
    if not pack.is_dir():
        print("资料包目录不存在: " + options.pack_dir, file=sys.stderr)
        return 2
    subs = _campaign_subpacks(pack)
    if subs:
        printed = False
        # 容器自身也有对象表 (商店/物品定义在容器级) —— 先跑容器再把逐关
        # 结果附后; 只聚合子地图会把 shop 商人 这类容器级查询吞成「无结果」
        base_lines = _QUERIES[options.command](pack, options.query, options.limit)
        if base_lines and not base_lines[0].startswith("未找到"):
            print("== 容器级 ==")
            for line in base_lines:
                print(line)
            printed = True
        for sub in subs:
            lines = _QUERIES[options.command](sub, options.query, options.limit)
            if not lines or lines[0].startswith("未找到"):
                continue
            print("== 子地图 " + sub.name + " ==")
            for line in lines:
                print(line)
            printed = True
        if not printed:
            print("子地图均无结果: " + options.query)
            return 2
        return 0
    lines = _QUERIES[options.command](pack, options.query, options.limit)
    for line in lines:
        print(line)
    return 0 if not lines[0].startswith("未找到") else 2


if __name__ == "__main__":
    raise SystemExit(run_pack_query_cli(parse_pack_query_cli_options(sys.argv[1:])))
