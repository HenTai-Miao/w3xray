"""Complete object and recipe differences with explicit whole-record limits."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import chain
from pathlib import Path
from typing import Protocol

from .pack_query_objects import OBJECT_TABLES, ObjectTable, valid_object_code


class DiffSources(Protocol):
    def _named_table(
        self, pack: Path, relative: str, table: str = ""
    ) -> ObjectTable: ...
    def _table_is_readable(self, pack: Path, relative: str) -> bool: ...
    def _read_rows(self, pack: Path, relative: str) -> list[list[str]]: ...
    def _clean(self, text: str) -> str: ...
    def load_items(self, pack: Path) -> dict[str, tuple[str, str]]: ...
    def _diff_field_changes(
        self,
        old: Path,
        new: Path,
        table: str,
        ids: list[str],
        *,
        old_complete: bool = True,
        new_complete: bool = True,
    ) -> dict[str, list[str]]: ...


@dataclass(frozen=True, slots=True)
class ComparisonDiagnostic:
    pack: str
    table: str
    message: str

    def render(self) -> str:
        return f"[⚠ 对比未完成: {self.table} — {self.message} 来源: {self.pack}]"


@dataclass(frozen=True, slots=True)
class DiffQueryResult:
    lines: tuple[str, ...]
    has_changes: bool = False
    complete: bool = False
    input_error: bool = False
    diagnostics: tuple[ComparisonDiagnostic, ...] = ()
    checked_packs: tuple[str, ...] = ()


Issues = dict[tuple[str, str], ComparisonDiagnostic]


def _incomplete(
    issues: Issues, pack: Path, relative: str, complete: bool, message: str
) -> None:
    if not complete:
        issues.setdefault(
            (str(pack), relative), ComparisonDiagnostic(str(pack), relative, message)
        )


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
    out: list[str],
    old: Path,
    new: Path,
    table: str,
    limit: int,
    sources: DiffSources,
    issues: Issues,
) -> int:
    relative = f"对象ID/{table}.tsv"
    old_view = sources._named_table(old, relative, table)
    new_view = sources._named_table(new, relative, table)
    old_rows, new_rows = old_view.rows, new_view.rows
    for pack, view in ((old, old_view), (new, new_view)):
        _incomplete(
            issues,
            pack,
            relative,
            view.complete,
            "对象表不完整；未用此来源的缺失记录推断新增或删除。",
        )
    old_by_id = {row[1]: row for row in old_rows[1:] if len(row) > 4}
    new_by_id = {row[1]: row for row in new_rows[1:] if len(row) > 4}
    added = (
        [code for code in new_by_id if code not in old_by_id]
        if old_view.complete
        else []
    )
    removed = (
        [code for code in old_by_id if code not in new_by_id]
        if new_view.complete
        else []
    )
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
    field_changes: dict[str, list[str]] = {}
    if common:
        old_fields = sources._named_table(old, "对象字段.tsv")
        new_fields = sources._named_table(new, "对象字段.tsv")
        for pack, view in ((old, old_fields), (new, new_fields)):
            _incomplete(
                issues,
                pack,
                "对象字段.tsv",
                view.complete,
                "字段表不完整；保留已确认值变化，未确定的缺失不作为字段增删。",
            )
        field_changes = sources._diff_field_changes(
            old,
            new,
            table,
            common,
            old_complete=old_fields.complete,
            new_complete=new_fields.complete,
        )
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


@dataclass(frozen=True, slots=True)
class _RecipeView:
    formulas: dict[str, tuple[Recipe, ...]]
    names: dict[str, str]
    complete: bool
    diagnostic: str = ""


def _recipes(pack: Path, sources: DiffSources) -> _RecipeView:
    formulas: dict[str, dict[Recipe, None]] = {}
    names: dict[str, str] = {}
    raw = sources._read_rows(pack, "掉落与获取关系.tsv")
    readable = sources._table_is_readable(pack, "掉落与获取关系.tsv")
    records = [
        (index, row)
        for index, row in enumerate(raw, 1)
        if any(value.strip().lstrip("\ufeff").strip() for value in row)
    ]
    slots: tuple[int | None, ...] = (2, 3, 4, 17, 18)
    if records:
        first = records[0][1]
        aliases = (
            {"关系类型", "relation_type", "kind"},
            {"装备id", "成品id", "item_id", "product_id"},
            {"装备名称", "成品名称", "item_name", "product_name"},
            {"合成材料id", "材料id", "material_ids"},
            {"合成材料名称与数量", "材料名称与数量", "materials", "material_text"},
        )
        normalized = tuple(
            value.strip().lstrip("\ufeff").strip().casefold() for value in first
        )
        columns = [
            tuple(i for i, name in enumerate(normalized) if name in choices)
            for choices in aliases
        ]
        legacy = len(first) >= 19 and bool(first[2]) and valid_object_code(first[3])
        if not legacy and any(columns):
            if (
                not columns[0]
                or not columns[1]
                or not (columns[3] or columns[4])
                or any(len(indices) > 1 for indices in columns)
            ):
                return _RecipeView(
                    {},
                    {},
                    False,
                    "配方关系表缺少或重复语义列；未猜测成品与材料身份，请核对表头或重新导出。",
                )
            slots = tuple(indices[0] if indices else None for indices in columns)
            records = records[1:]
    bad: list[int] = []
    for index, row in records:

        def cell(slot: int | None) -> str | None:
            return row[slot] if slot is not None and slot < len(row) else None

        kind, code, name, materials, text = (cell(slot) for slot in slots)
        if not kind:
            bad.append(index)
            continue
        if kind != "合成":
            continue
        if (
            code is None
            or not valid_object_code(code)
            or materials is None
            and text is None
        ):
            bad.append(index)
            continue
        materials, text = (materials or "").strip(), sources._clean(text or "")
        if not materials and not text:
            bad.append(index)
            continue
        formulas.setdefault(code, {}).setdefault((materials, text), None)
        if name := sources._clean(name or ""):
            names.setdefault(code, name)
    diagnostic = (
        (
            f"配方关系表有 {len(bad)} 条记录不完整；记录序号: "
            + ", ".join(map(str, bad))
            + "；未用缺失配方推断增删，请核对知识包。"
        )
        if bad
        else "配方关系表读取失败，未用空结果推断配方变化。"
        if not readable
        else ""
    )
    return _RecipeView(
        {code: tuple(rows) for code, rows in formulas.items()},
        names,
        readable and not bad,
        diagnostic,
    )


def _recipe_section(
    out: list[str],
    old: Path,
    new: Path,
    limit: int,
    sources: DiffSources,
    issues: Issues,
) -> int:
    old_view, new_view = _recipes(old, sources), _recipes(new, sources)
    old_recipes, old_names = old_view.formulas, old_view.names
    new_recipes, new_names = new_view.formulas, new_view.names
    for pack, view in ((old, old_view), (new, new_view)):
        _incomplete(issues, pack, "掉落与获取关系.tsv", view.complete, view.diagnostic)
    added = (
        [code for code in new_recipes if code not in old_recipes]
        if old_view.complete
        else []
    )
    removed = (
        [code for code in old_recipes if code not in new_recipes]
        if new_view.complete
        else []
    )
    changed = [
        code
        for code in new_recipes
        if code in old_recipes
        and (
            old_view.complete
            and frozenset(new_recipes[code]).difference(old_recipes[code])
            or new_view.complete
            and frozenset(old_recipes[code]).difference(new_recipes[code])
        )
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
) -> DiffQueryResult:
    if not old_path:
        return DiffQueryResult(
            ("diff 需要第二个包: pack-query <新包> diff <旧包目录>",), input_error=True
        )
    old = Path(old_path)
    if not old.is_dir():
        return DiffQueryResult(("第二个包目录不存在: " + old_path,), input_error=True)
    selected = query.strip()
    if (
        selected
        and Path(selected).is_dir()
        and Path(selected).resolve() == old.resolve()
    ):
        selected = ""
    if selected not in (*OBJECT_TABLES, "合成", "", "all", "全部"):
        return DiffQueryResult(
            (
                "未找到可用的对比表: " + selected,
                "可用: "
                + "/".join((*OBJECT_TABLES, "合成"))
                + "；省略筛选词比较全部。",
            ),
            input_error=True,
        )
    if selected in ("all", "全部"):
        selected = ""
    out: list[str] = []
    issues: Issues = {}
    sections, total = 0, 0
    for table in OBJECT_TABLES:
        if selected and selected != table:
            continue
        changes = _object_section(out, old, new, table, limit, sources, issues)
        sections += bool(changes)
        total += changes
    if selected in ("", "物品", "合成"):
        changes = _recipe_section(out, old, new, limit, sources, issues)
        sections += bool(changes)
        total += changes
    lines = (
        [
            f"共 {sections} 个差异段, 合计 {total} 项变化"
            + ("（已确认；对比未完成）" if issues else ""),
            *out,
        ]
        if total
        else ["未找到可确认的完整对比结果；数据不完整，不能判定两包相同。"]
        if issues
        else ["两包对象表无差异"]
    )
    lines.extend(note.render() for note in issues.values())
    return DiffQueryResult(
        tuple(lines),
        bool(total),
        not issues,
        diagnostics=tuple(issues.values()),
        checked_packs=(str(new), str(old)),
    )
