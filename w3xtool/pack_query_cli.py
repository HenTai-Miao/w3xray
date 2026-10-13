# -*- coding: utf-8 -*-
"""pack-query 子命令：一次进程内查询地图知识包（物品/配方/坐标/掉落/任务/全文）。

用法：
    uv run main.py pack-query <资料包目录> <子命令> <查询词> [--limit N]

子命令：
    item   <名字|四码>   物品属性（金币价; 装备效果取自携带技能属性字段; 真实提示文本优先于继承模板描述）
    recipe <名字|四码>   相关合成配方（作为产物或材料，自动去重）
    where  <名字|四码>   单位/地面物品的放置坐标
    drop   <名字|四码>   获取途径（掉落/商店/触发奖励）
    quest  <关键词>     任务注册文本与剧情对话
    text   <关键词>     全包 TSV 有界搜索
    price  <名字|四码>   金币价（igol 地图价优先, 基础ID继承）
    tech   <名字|四码>   科技卡（最大等级/每级金木费用/效果/前置, 自定义字段优先基础继承）
    cmd    <指令文字>    聊天指令效果链（注册->触发器->条件+动作函数体节选, 免手搓脚本）

设计动机：避免为每次查询写一次性脚本/起多个进程（文件变更通知会拖垮资源
管理器外壳）；全部查询在单次进程内完成，输出有界。
"""

from __future__ import annotations

import csv
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
    "cmd",
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
    如《西方世界的劫难》系列地图），两者同为物品金币成本字段。
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
                g = str(gold_b + gold_i * (n - 1)) if gold_b is not None else "-"
                w = str(lum_b + lum_i * (n - 1)) if lum_b is not None else "-"
                return "金" + g + " 木" + w

            marks = sorted({1, min(5, levels), levels})
            lines.append(
                "  级费用: " + " | ".join(str(n) + "级 " + _cost(n) for n in marks)
            )
            gsum = (
                sum(gold_b + gold_i * (n - 1) for n in range(1, levels + 1))
                if gold_b is not None
                else None
            )
            wsum = (
                sum(lum_b + lum_i * (n - 1) for n in range(1, levels + 1))
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
                    lines.append("  效果(" + str(lv) + "级): " + t[:120])
        reqs = sorted((k, v) for k, v in f.items() if k.startswith("greq:"))
        if reqs:
            lines.append(
                "  前置: " + ", ".join(k.split(":", 1)[1] + "级←" + v for k, v in reqs)
            )
        lines.append("")
        if len(lines) >= limit * 8:
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
    limit: int = 20


@dataclass(frozen=True, slots=True)
class PackQueryCliOptionError(ValueError):
    """pack-query 参数错误，message 面向命令行用户。"""

    detail: str

    def __str__(self) -> str:
        return single_line_text(self.detail)


def parse_pack_query_cli_options(argv: Sequence[str]) -> PackQueryCliOptions:
    """解析 pack-query 后的参数：<资料包目录> <子命令> <查询词> [--limit N]。"""
    rest = list(argv)
    limit = 20
    if "--limit" in rest:
        i = rest.index("--limit")
        if i + 1 >= len(rest):
            raise PackQueryCliOptionError("--limit 需要一个数字参数")
        try:
            limit = int(rest[i + 1])
        except ValueError as exc:
            raise PackQueryCliOptionError("--limit 需要一个数字参数") from exc
        if limit < 1:
            raise PackQueryCliOptionError("--limit 必须为正整数")
        rest = rest[:i] + rest[i + 2 :]
    if len(rest) != 3:
        raise PackQueryCliOptionError(
            "用法: pack-query <资料包目录> <item|recipe|where|drop|quest|text|price|shop|tech|cmd> <查询词>"
        )
    pack_dir, command, query = rest
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
            lines.append("  " + (tooltips.get(code, "") or desc)[:240])
            if len(lines) >= limit * 3:
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
            if len(lines) >= limit:
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
    for shop_code, shop_name, codes in load_shop_stocks(pack):
        if not _match(query, shop_code, shop_name):
            continue
        lines.append("== " + shop_name + " [" + shop_code + "]")
        for c in codes:
            name = items.get(c, (c, ""))[0]
            price = _item_price(bases, c, overrides)
            tag = "地图价" if c in overrides else "继承"
            lines.append(
                "  " + name + "  " + (price or "?") + "金  (" + tag + " " + c + ")"
            )
        lines.append("")
        if len(lines) >= limit * 12:
            break
    return lines or ["未找到商店: " + query]


def _query_recipe(pack: Path, query: str, limit: int) -> list[str]:
    items = load_items(pack)
    hits: list[str] = []
    seen: set[tuple[str, tuple[tuple[str, int], ...]]] = set()
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
            if len(hits) >= limit:
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
            if len(lines) >= limit:
                break
    return lines or ["未找到放置记录: " + query]


def _query_drop(pack: Path, query: str, limit: int) -> list[str]:
    q = query.lower()
    lines = []
    kinds = set()
    for r in _read_rows(pack, "掉落与获取关系.tsv"):
        if len(r) < 7:
            continue
        code, name = r[3], _clean(r[4])
        if not (q == code.lower() or q in name.lower() or name.lower() in q):
            continue
        kinds.add(r[2])
        lines.append(name + " [" + code + "]  " + r[2] + " <- " + r[5] + " " + r[6])
        if len(lines) >= limit:
            break
    if not lines:
        return ["未找到获取途径: " + query]
    if not any("掉落" in k for k in kinds):
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
                tail = line.rstrip("\n")
                s = tail.find("\t", tail.find(query))
                lines.append(
                    _clean(tail[s + 1 : s + 260]) if s > 0 else _clean(tail[:260])
                )
                if len(lines) >= limit:
                    break
    return lines or ["未找到任务文本: " + query]


def _query_text(pack: Path, query: str, limit: int) -> list[str]:
    lines = []
    for path in sorted(pack.glob("*.tsv")):
        try:
            for line in path.open(encoding="utf-8"):
                if query in line:
                    lines.append(path.name + ": " + _clean(line.rstrip("\n"))[:220])
                    break
        except OSError:
            continue
        if len(lines) >= limit:
            break
    return lines or ["未找到文本: " + query]


_CHAT_REG_RE = re.compile(
    r"TriggerRegisterPlayerChatEvent\(\s*(gg_trg_\w+)\s*,\s*Player\(\d+\)\s*,\s*"
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


def _fn_body(script: str, fn: str, cap: int = 900) -> str:
    i = script.find("function " + fn + " takes")
    if i < 0:
        return "(未找到函数体)"
    j = script.find("endfunction", i)
    body = script[i : (j + len("endfunction")) if j >= 0 else i + cap]
    return " ".join(body.split())[:cap]


def _query_cmd(pack: Path, query: str, limit: int) -> list[str]:
    script = load_script(pack)
    if script is None:
        return ["未找到脚本 (脚本可读文本/*.j)——该包可能未导出可读脚本"]
    regs: dict[str, tuple[str, str, int]] = {}
    for m in _CHAT_REG_RE.finditer(script):
        var, cmd, exact = m.group(1), m.group(2), m.group(3)
        if query in cmd or cmd in query:
            v = regs.setdefault(var, (cmd, exact, 0))
            regs[var] = (v[0], v[1], v[2] + 1)
    if not regs:
        return ["未找到聊天指令: " + query]
    actions = dict(_ADD_ACTION_RE.findall(script))
    conds = dict(_ADD_COND_RE.findall(script))
    lines: list[str] = []
    for var, (cmd, exact, count) in sorted(regs.items(), key=lambda kv: -kv[1][2]):
        if len(lines) >= limit * 6:
            break
        lines.append(
            f'指令 "{cmd}" ({"精确" if exact == "true" else "前缀"}, 注册{count}个玩家位) -> {var}'
        )
        cond = conds.get(var)
        if cond:
            lines.append("  条件: " + _fn_body(script, cond, 320))
        act = actions.get(var)
        lines.append(
            "  动作: " + _fn_body(script, act)
            if act
            else "  动作: (未找到 TriggerAddAction)"
        )
        lines.append("")
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
}


def run_pack_query_cli(options: PackQueryCliOptions) -> int:
    """执行查询并打印结果；返回 0（有结果）或 2（无结果）。"""
    configure_cli_output()
    pack = Path(options.pack_dir)
    if not pack.is_dir():
        print("资料包目录不存在: " + options.pack_dir, file=sys.stderr)
        return 2
    lines = _QUERIES[options.command](pack, options.query, options.limit)
    for line in lines:
        print(line)
    return 0 if not lines[0].startswith("未找到") else 2


if __name__ == "__main__":
    raise SystemExit(run_pack_query_cli(parse_pack_query_cli_options(sys.argv[1:])))
