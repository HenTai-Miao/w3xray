"""Grouped script call catalog for static map investigation."""

from __future__ import annotations

from .script_sources import analysis_script_sources, script_language

import re
from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final, cast

from .map_data import MapData
from .presentation_safety import tsv_cell as _tsv
from .save_api_catalog import object_api_category, save_api_info
from .script_lexing import script_string_values, script_views
from .script_scan import object_code_occurrences
from .script_scopes import script_structure, source_line_starts

_CALL_RE: Final = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")


@dataclass(frozen=True, slots=True)
class ScriptCall:
    function: str
    source: str
    line: int
    mechanism: str
    object_codes: tuple[str, ...]
    string_args: tuple[str, ...]
    example: str
    offset: int | None = None
    end_offset: int | None = None
    scope_offset: int | None = None
    primary: bool = True


@dataclass(frozen=True, slots=True)
class ScriptCallRow:
    function: str
    count: int
    sources: tuple[str, ...]
    lines: tuple[str, ...]
    mechanisms: tuple[str, ...]
    object_codes: tuple[str, ...]
    string_args: tuple[str, ...]
    examples: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ScriptCallCatalog:
    calls: tuple[ScriptCall, ...]
    rows: tuple[ScriptCallRow, ...]


def build_script_call_catalog(md: MapData) -> ScriptCallCatalog:
    """Return script calls grouped by function/native name.

    目录是加载后不变的派生数据；函数索引、对象码出现索引等会
    重复构建，挂在 MapData 上共用一次扫描结果。
    """
    cached = getattr(md, "_script_call_catalog_cache", None)
    if cached is not None:
        return cast("ScriptCallCatalog", cached)
    calls: list[ScriptCall] = []
    for source, text, lua in analysis_script_sources(md):
        calls.extend(_scan_script_calls(source, text, lua=lua))
    catalog = ScriptCallCatalog(calls=tuple(calls), rows=_group_calls(calls))
    try:
        md._script_call_catalog_cache = catalog
    except AttributeError:  # 测试替身可能不是带槽的 MapData
        pass
    return catalog


def format_script_call_catalog_tsv(catalog: ScriptCallCatalog) -> str:
    """Format a grouped call catalog as TSV."""
    rows = ["函数\t次数\t来源\t行号\t机制\t对象码\t字符串参数\t示例"]
    for row in catalog.rows:
        rows.append(
            "\t".join(
                (
                    _tsv(row.function),
                    str(row.count),
                    _tsv("; ".join(row.sources)),
                    _tsv("; ".join(row.lines)),
                    _tsv("; ".join(row.mechanisms)),
                    _tsv("; ".join(row.object_codes)),
                    _tsv("; ".join(row.string_args)),
                    _tsv(" | ".join(row.examples)),
                )
            )
        )
    return "\n".join(rows) + "\n"


def _scan_script_calls(
    source: str, text: str, *, lua: bool | None = None
) -> list[ScriptCall]:
    lua = script_language(source) if lua is None else lua
    rows: list[ScriptCall] = []
    line_starts = source_line_starts(text)
    views = script_views(text, lua=lua)
    structure = script_structure(text, lua=lua)
    codes = object_code_occurrences(text, lua=lua)
    positions = tuple(offset for offset, _code in codes)
    for call in structure.calls:
        name = call.name
        arguments = structure.own_text(
            views.arguments, call.open + 1, call.end - int(call.complete), call.owner
        )
        found: set[str] = set()
        for offset, code in codes[
            bisect_left(positions, call.start) : bisect_left(positions, call.end)
        ]:
            owner = structure.scopes.at(offset)
            if (owner.start if owner is not None else None) == call.owner:
                found.add(code)
        object_codes = tuple(sorted(found))
        string_args = _string_args((arguments,), object_codes)
        rows.append(
            ScriptCall(
                function=name,
                source=source,
                line=bisect_right(line_starts, call.start),
                mechanism=_mechanism(name, object_codes),
                object_codes=object_codes,
                string_args=string_args,
                example=text[call.start : call.end],
                offset=call.start,
                end_offset=call.end,
                scope_offset=call.owner,
                primary=call.primary,
            )
        )
    return rows


def _group_calls(calls: Iterable[ScriptCall]) -> tuple[ScriptCallRow, ...]:
    grouped: dict[str, list[ScriptCall]] = defaultdict(list)
    for call in calls:
        grouped[call.function].append(call)
    rows: list[ScriptCallRow] = []
    for function in sorted(grouped):
        items = grouped[function]
        rows.append(
            ScriptCallRow(
                function=function,
                count=len(items),
                sources=tuple(sorted({item.source for item in items})),
                lines=_line_summary(items),
                mechanisms=_unique_ordered(item.mechanism for item in items),
                object_codes=tuple(
                    sorted({code for item in items for code in item.object_codes})
                ),
                string_args=_unique_ordered(
                    arg for item in items for arg in item.string_args
                ),
                examples=_unique_ordered(
                    item.example for item in items if item.example
                ),  # 全部示例
            )
        )
    return tuple(rows)


def _line_summary(items: list[ScriptCall]) -> tuple[str, ...]:
    if len({item.source for item in items}) == 1:
        return tuple(str(line) for line in sorted({item.line for item in items}))
    return tuple(sorted({f"{item.source}:{item.line}" for item in items}))


def _mechanism(name: str, object_codes: tuple[str, ...]) -> str:
    name = name.removeprefix("_G.")
    api = save_api_info(name)
    if api is not None:
        return f"{api.mechanism}:{api.operation}"
    category = object_api_category(name)
    if category is not None:
        return f"ObjectID:{category}"
    if object_codes:
        return "ObjectCode"
    return "普通调用"


def _string_args(
    args: tuple[str, ...], object_codes: tuple[str, ...]
) -> tuple[str, ...]:
    code_set = set(object_codes)
    return _unique_ordered(
        value
        for value in _quoted_values(" ".join(args))
        if value and value not in code_set
    )


def _quoted_values(text: str) -> tuple[str, ...]:
    return tuple(script_string_values(text))


def _line_starts(text: str) -> list[int]:
    starts = [0]
    starts.extend(match.end() for match in re.finditer("\n", text))
    return starts


def _line_fragment(text: str, start: int) -> str:
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", start)
    if line_end < 0:
        line_end = len(text)
    return text[line_start:line_end].strip()


def _unique_ordered(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)
