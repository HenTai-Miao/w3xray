"""Exact function ownership and source-local call indexes for JASS and Lua."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import re
from typing import cast, final

from .map_data import MapData
from .presentation_safety import tsv_cell as _tsv
from .script_call_catalog import ScriptCall, build_script_call_catalog
from .script_scopes import ScopeLookup, script_structure
from .script_sources import analysis_script_sources, script_language

_PRIMARY_CALL_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")


@dataclass(frozen=True, slots=True)
class ScriptFunction:
    name: str
    source: str
    start_line: int
    end_line: int
    inbound_calls: int
    internal_calls: int
    mechanisms: tuple[str, ...]
    object_codes: tuple[str, ...]
    called_functions: tuple[str, ...]
    summary: str
    start_offset: int | None = None
    end_offset: int | None = None
    parent_offset: int | None = None
    complete: bool = True
    ambiguous_calls: int = 0

    @property
    def line_count(self) -> int:
        return self.end_line - self.start_line + 1


@dataclass(frozen=True, slots=True)
class ScriptFunctionIndex:
    functions: tuple[ScriptFunction, ...]


@dataclass(frozen=True, slots=True)
class _FunctionRange:
    name: str
    source: str
    start_line: int
    end_line: int
    summary: str
    start_offset: int
    end_offset: int
    parent_offset: int | None
    complete: bool


@final
class ScriptFunctionLookup:
    """Binary lookups of exact character scopes, with legacy line-only fallback."""

    def __init__(self, functions: Iterable[ScriptFunction]) -> None:
        grouped: dict[str, list[ScriptFunction]] = {}
        for item in functions:
            grouped.setdefault(item.source, []).append(item)
        self._characters = {
            source: ScopeLookup(
                (item.start_offset, item.end_offset, item)
                for item in values
                if item.start_offset is not None and item.end_offset is not None
            )
            for source, values in grouped.items()
        }
        self._lines = {
            source: ScopeLookup(
                (item.start_line, item.end_line + 1, item) for item in values
            )
            for source, values in grouped.items()
        }

    def name_for(self, source: str, line: int, *, offset: int | None = None) -> str:
        entry = (self._characters if offset is not None else self._lines).get(source)
        item = (
            entry.at(offset if offset is not None else line)
            if entry is not None
            else None
        )
        return item.name if item is not None else ""


def build_function_lookup(functions: Iterable[ScriptFunction]) -> ScriptFunctionLookup:
    return ScriptFunctionLookup(functions)


def _function_ranges(
    source: str, text: str, *, lua: bool | None = None
) -> Iterable[_FunctionRange]:
    lua = script_language(source) if lua is None else lua
    for item in script_structure(text, lua=lua).functions:
        yield _FunctionRange(
            item.name,
            source,
            item.start_line,
            item.end_line,
            text[item.start : item.body_start].strip(),
            item.start,
            item.end,
            item.parent,
            item.complete,
        )


def _is_primary_call(call: ScriptCall) -> bool:
    if call.offset is not None:
        return call.primary
    match = _PRIMARY_CALL_RE.search(call.example)
    return match is not None and match.group(1) == call.function


def _inside(item: _FunctionRange, call: ScriptCall) -> bool:
    if call.source != item.source:
        return False
    return (
        item.start_offset <= call.offset < item.end_offset
        if call.offset is not None
        else item.start_line <= call.line <= item.end_line
    )


def build_script_function_index(md: MapData) -> ScriptFunctionIndex:
    cached = getattr(md, "_script_function_index_cache", None)
    if cached is not None:
        return cast("ScriptFunctionIndex", cached)
    ranges = tuple(
        item
        for source, text, lua in analysis_script_sources(md)
        for item in _function_ranges(source, text, lua=lua)
    )
    grouped: dict[str, list[_FunctionRange]] = {}
    by_position: dict[tuple[str, int], _FunctionRange] = {}
    names: dict[tuple[str, str], dict[int | None, list[_FunctionRange]]] = {}
    for item in ranges:
        grouped.setdefault(item.source, []).append(item)
        by_position[item.source, item.start_offset] = item
        names.setdefault(
            (item.source, item.name.replace(":", ".").removeprefix("_G.")), {}
        ).setdefault(item.parent_offset, []).append(item)
    exact = {
        source: ScopeLookup(
            (item.start_offset, item.end_offset, item) for item in values
        )
        for source, values in grouped.items()
    }
    lines = {
        source: ScopeLookup(
            (item.start_line, item.end_line + 1, item) for item in values
        )
        for source, values in grouped.items()
    }
    internal: dict[tuple[str, int], list[ScriptCall]] = {}
    inbound: dict[tuple[str, int], int] = {}
    ambiguous: dict[tuple[str, str, int | None], int] = {}
    unresolved: dict[tuple[str, str], int] = {}
    for call in build_script_call_catalog(md).calls:
        lookup = (exact if call.offset is not None else lines).get(call.source)
        owner = (
            lookup.at(call.offset if call.offset is not None else call.line)
            if lookup is not None
            else None
        )
        if owner is not None and _is_primary_call(call):
            internal.setdefault((owner.source, owner.start_offset), []).append(call)
        name = call.function.replace(":", ".").removeprefix("_G.")
        candidates = names.get((call.source, name))
        if candidates is None:
            continue
        visible = (
            owner.start_offset
            if owner is not None and not call.function.startswith("_G.")
            else None
        )
        while True:
            targets = candidates.get(visible, ())
            if targets:
                if len(targets) == 1:
                    target = targets[0]
                    key = (target.source, target.start_offset)
                    if owner is None or owner.start_offset != target.start_offset:
                        inbound[key] = inbound.get(key, 0) + 1
                else:
                    key = (call.source, name, visible)
                    ambiguous[key] = ambiguous.get(key, 0) + 1
                break
            if visible is None:
                unresolved[call.source, name] = (
                    unresolved.get((call.source, name), 0) + 1
                )
                break
            visible = by_position[call.source, visible].parent_offset
    result: list[ScriptFunction] = []
    for item in ranges:
        key = (item.source, item.start_offset)
        calls = internal.get(key, ())
        mechanisms = _unique_ordered(call.mechanism for call in calls)
        explicit = tuple(value for value in mechanisms if value != "普通调用")
        result.append(
            ScriptFunction(
                item.name,
                item.source,
                item.start_line,
                item.end_line,
                inbound.get(key, 0),
                len(calls),
                explicit or mechanisms,
                tuple(sorted({code for call in calls for code in call.object_codes})),
                _unique_ordered(call.function for call in calls),
                item.summary,
                item.start_offset,
                item.end_offset,
                item.parent_offset,
                item.complete,
                ambiguous.get(
                    (
                        item.source,
                        item.name.replace(":", ".").removeprefix("_G."),
                        item.parent_offset,
                    ),
                    0,
                )
                + unresolved.get(
                    (item.source, item.name.replace(":", ".").removeprefix("_G.")), 0
                ),
            )
        )
    index = ScriptFunctionIndex(tuple(sorted(result, key=_function_sort_key)))
    try:
        md._script_function_index_cache = index
    except AttributeError:
        pass
    return index


def format_script_function_index_tsv(index: ScriptFunctionIndex) -> str:
    """Append exact offsets, parent and ambiguity diagnostics to legacy columns."""
    rows = [
        "函数\t来源\t起始行\t结束行\t行数\t被调用次数\t内部调用数\t机制\t对象码\t调用函数\t摘要\t起始偏移\t结束偏移\t父函数偏移\t范围完整性\t歧义调用数"
    ]
    for item in index.functions:
        rows.append(
            "\t".join(
                (
                    _tsv(item.name),
                    _tsv(item.source),
                    str(item.start_line),
                    str(item.end_line),
                    str(item.line_count),
                    str(item.inbound_calls),
                    str(item.internal_calls),
                    _tsv("; ".join(item.mechanisms)),
                    _tsv("; ".join(item.object_codes)),
                    _tsv("; ".join(item.called_functions)),
                    _tsv(item.summary),
                    str(item.start_offset) if item.start_offset is not None else "",
                    str(item.end_offset) if item.end_offset is not None else "",
                    str(item.parent_offset) if item.parent_offset is not None else "",
                    "完整" if item.complete else "未闭合",
                    str(item.ambiguous_calls),
                )
            )
        )
    return "\n".join(rows) + "\n"


def _unique_ordered(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _function_sort_key(item: ScriptFunction) -> tuple[str, int, int, str]:
    return item.source, item.start_line, item.start_offset or 0, item.name
