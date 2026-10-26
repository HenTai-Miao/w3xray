"""Complete object and recipe differences with explicit whole-record limits."""

from collections.abc import Callable, Sequence
from itertools import chain
from pathlib import Path
from typing import Protocol

from .pack_query_objects import OBJECT_TABLES, valid_object_code


class DiffSources(Protocol):
    def _object_rows(self, pack: Path, table: str) -> tuple[tuple[str, ...], ...]: ...
    def _read_rows(self, pack: Path, relative: str) -> list[list[str]]: ...
    def _clean(self, text: str) -> str: ...
    def load_items(self, pack: Path) -> dict[str, tuple[str, str]]: ...
    def _diff_field_changes(
        self, old: Path, new: Path, table: str, ids: list[str]
    ) -> dict[str, list[str]]: ...


def _append_changes(
    out: list[str],
    title: str,
    groups: tuple[Sequence[str], Sequence[str], Sequence[str]],
    limit: int,
    render: Callable[[str, str], list[str]],
) -> int:
    total = sum(map(len, groups))
    if not total:
        return 0
    added, removed, changed = groups
    out.append(
        f"== {title}: 新增 {len(added)} / 删除 {len(removed)} / 变更 {len(changed)} =="
    )
    if title == "合成":
        out.append("  （按成品统计；每个成品保留全部旧/新配方）")
    records = chain.from_iterable(
        ((kind, code) for code in codes) for kind, codes in zip(("+", "-", "~"), groups)
    )
    shown = 0
    for kind, code in records:
        if limit and shown >= limit:
            break
        out.extend(render(kind, code))
        shown += 1
    if limit and total > shown:
        out.append(
            f"  (已达 --limit {limit}, 其余 {total - shown} 条未显示——去掉 --limit 看全量)"
        )
    return total


def _object_section(
    out: list[str], old: Path, new: Path, table: str, limit: int, sources: DiffSources
) -> int:
    old_rows, new_rows = (
        sources._object_rows(old, table),
        sources._object_rows(new, table),
    )
    old_by_id = {row[1]: row for row in old_rows[1:] if len(row) > 4}
    new_by_id = {row[1]: row for row in new_rows[1:] if len(row) > 4}
    added = [code for code in new_by_id if code not in old_by_id]
    removed = [code for code in old_by_id if code not in new_by_id]
    common = [code for code in new_by_id if code in old_by_id]
    old_columns = sorted(enumerate(old_rows[0]), key=lambda entry: entry[1])
    new_columns = sorted(enumerate(new_rows[0]), key=lambda entry: entry[1])

    def values(row: tuple[str, ...], columns: list[tuple[int, str]]):
        return tuple(
            (name, row[index] if index < len(row) else None) for index, name in columns
        )

    same_header = old_rows[0] == new_rows[0]
    changed = {
        code
        for code in common
        if (
            new_by_id[code] != old_by_id[code]
            if same_header
            else values(new_by_id[code], new_columns)
            != values(old_by_id[code], old_columns)
        )
    }
    field_changes = sources._diff_field_changes(old, new, table, common)
    changed.update(field_changes)

    def render(kind: str, code: str) -> list[str]:
        row = old_by_id[code] if kind == "-" else new_by_id[code]
        lines = [f"  {kind} [{code}] {sources._clean(row[4])}"]
        if kind == "~":
            details = field_changes.get(code)
            lines.extend(
                "      " + detail
                for detail in details
                or ("(名称/行内容有变化, 字段明细请翻两包 对象字段.tsv)",)
            )
        return lines

    return _append_changes(out, table, (added, removed, sorted(changed)), limit, render)


Recipe = tuple[str, str]


def _recipes(
    pack: Path, sources: DiffSources
) -> tuple[dict[str, tuple[Recipe, ...]], dict[str, str]]:
    formulas: dict[str, dict[Recipe, None]] = {}
    names: dict[str, str] = {}
    for row in sources._read_rows(pack, "掉落与获取关系.tsv"):
        if len(row) < 19 or row[2] != "合成" or not valid_object_code(row[3]):
            continue
        materials, text = row[17].strip(), sources._clean(row[18])
        if not materials and not text:
            continue
        formulas.setdefault(row[3], {}).setdefault((materials, text), None)
        if name := sources._clean(row[4]):
            names.setdefault(row[3], name)
    return {code: tuple(rows) for code, rows in formulas.items()}, names


def _recipe_section(
    out: list[str], old: Path, new: Path, limit: int, sources: DiffSources
) -> int:
    old_recipes, old_names = _recipes(old, sources)
    new_recipes, new_names = _recipes(new, sources)
    added = [code for code in new_recipes if code not in old_recipes]
    removed = [code for code in old_recipes if code not in new_recipes]
    changed = [
        code
        for code in new_recipes
        if code in old_recipes
        and frozenset(new_recipes[code]) != frozenset(old_recipes[code])
    ]
    if not added and not removed and not changed:
        return 0
    old_items, new_items = sources.load_items(old), sources.load_items(new)

    def describe(recipe: Recipe) -> str:
        materials, text = recipe
        return text + (f" [材料ID: {materials}]" if materials else "")

    def render(kind: str, code: str) -> list[str]:
        names, items = (old_names, old_items) if kind == "-" else (new_names, new_items)
        name = items.get(code, (names.get(code, code), ""))[0]
        lines = [f"  {kind} [{code}] {name}"]
        if kind != "+":
            lines.extend(
                "      旧: " + describe(recipe) for recipe in old_recipes[code]
            )
        if kind != "-":
            lines.extend(
                "      新: " + describe(recipe) for recipe in new_recipes[code]
            )
        return lines

    return _append_changes(out, "合成", (added, removed, changed), limit, render)


def query_diff(
    new: Path, query: str, limit: int, old_path: str, sources: DiffSources
) -> list[str]:
    if not old_path:
        return ["diff 需要第二个包: pack-query <新包> diff <旧包目录>"]
    old = Path(old_path)
    if not old.is_dir():
        return ["第二个包目录不存在: " + old_path]
    selected = query.strip()
    if (
        selected
        and Path(selected).is_dir()
        and Path(selected).resolve() == old.resolve()
    ):
        selected = ""
    if selected not in (*OBJECT_TABLES, "合成", "", "all", "全部"):
        return [
            "未找到可用的对比表: " + selected,
            "可用: " + "/".join((*OBJECT_TABLES, "合成")) + "；省略筛选词比较全部。",
        ]
    if selected in ("all", "全部"):
        selected = ""
    out: list[str] = []
    sections, total = 0, 0
    for table in OBJECT_TABLES:
        if selected and selected != table:
            continue
        changes = _object_section(out, old, new, table, limit, sources)
        sections += bool(changes)
        total += changes
    if selected in ("", "物品", "合成"):
        changes = _recipe_section(out, old, new, limit, sources)
        sections += bool(changes)
        total += changes
    return (
        [f"共 {sections} 个差异段, 合计 {total} 项变化", *out]
        if total
        else ["两包对象表无差异"]
    )
