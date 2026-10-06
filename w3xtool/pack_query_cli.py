# -*- coding: utf-8 -*-
"""pack-query 子命令：一次进程内查询地图知识包（物品/配方/坐标/掉落/任务/全文）。

用法：
    uv run main.py pack-query <资料包目录> <子命令> <查询词> [--limit N]

子命令：
    item   <名字|四码>   物品属性
    recipe <名字|四码>   相关合成配方（作为产物或材料）
    where  <名字|四码>   单位/地面物品的放置坐标
    drop   <名字|四码>   获取途径（掉落/商店/触发奖励）
    quest  <关键词>     任务注册文本与剧情对话
    text   <关键词>     全包 TSV 有界搜索

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

_COMMANDS = ("item", "recipe", "where", "drop", "quest", "text")
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
        if "set u=CreateUnit(p, '" in line:
            tail = line.split("set u=CreateUnit(p, '", 1)[1]
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
            "用法: pack-query <资料包目录> <item|recipe|where|drop|quest|text> <查询词>"
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
    lines = []
    for code, (name, desc) in items.items():
        if _match(query, code, name):
            lines.append("[" + code + "] " + name)
            lines.append("  " + desc[:240])
            if len(lines) >= limit * 2:
                break
    return lines or ["未找到物品: " + query]


def _query_recipe(pack: Path, query: str, limit: int) -> list[str]:
    items = load_items(pack)
    hits = []
    for prod, pairs in load_formulas(pack):
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
    for r in _read_rows(pack, "掉落与获取关系.tsv"):
        if len(r) < 7:
            continue
        code, name = r[3], _clean(r[4])
        if not (q == code.lower() or q in name.lower() or name.lower() in q):
            continue
        lines.append(name + " [" + code + "]  " + r[2] + " <- " + r[5] + " " + r[6])
        if len(lines) >= limit:
            break
    return lines or ["未找到获取途径: " + query]


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


_QUERIES = {
    "item": _query_item,
    "recipe": _query_recipe,
    "where": _query_where,
    "drop": _query_drop,
    "quest": _query_quest,
    "text": _query_text,
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
