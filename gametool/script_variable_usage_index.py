"""Global variable usage index for static script investigation."""

from __future__ import annotations

from .script_sources import analysis_script_sources, script_language

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from .api import MapData
from .presentation_safety import tsv_cell as _tsv
from .script_function_index import (
    ScriptFunctionLookup,
    build_function_lookup,
    build_script_function_index,
)
from .script_scan import _codes_in
from .script_lexing import script_views
from .script_tokens import script_code_text
from .script_scopes import source_line_starts, script_structure

_VAR_RE: Final = re.compile(
    r"\b(?:udg|bj|gg_trg|gg_unit|gg_item|gg_dest|gg_rct|gg_cam|gg_snd)_[A-Za-z0-9_]+\b",
)
_CALL_RE: Final = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_JASS_SET_RE: Final = re.compile(
    r"^\s*set\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?:\[[^\]]+\])?\s*=",
)
_LUA_ASSIGN_RE: Final = re.compile(
    r"^\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?:\[[^\]]+\])?\s*=",
)


@dataclass(frozen=True, slots=True)
class ScriptVariableUsage:
    source: str
    line: int
    function: str
    variable: str
    access: str
    category: str
    call: str
    object_codes: tuple[str, ...]
    summary: str


@dataclass(frozen=True, slots=True)
class ScriptVariableUsageIndex:
    usages: tuple[ScriptVariableUsage, ...]


def build_script_variable_usage_index(md: MapData) -> ScriptVariableUsageIndex:
    """Return udg_/gg_/bj_ variable reads and writes with script context."""
    functions = build_function_lookup(build_script_function_index(md).functions)
    rows: list[ScriptVariableUsage] = []
    for source, text, lua in analysis_script_sources(md):
        rows.extend(_usages_for_script(source, text, functions, lua=lua))
    return ScriptVariableUsageIndex(tuple(rows))


def format_script_variable_usage_index_tsv(index: ScriptVariableUsageIndex) -> str:
    """Format script variable usage rows as TSV."""
    rows = ["来源\t行号\t函数\t变量\t访问\t类别\t调用\t对象码\t摘要"]
    for item in index.usages:
        rows.append(
            "\t".join(
                (
                    _tsv(item.source),
                    str(item.line),
                    _tsv(item.function),
                    _tsv(item.variable),
                    _tsv(item.access),
                    _tsv(item.category),
                    _tsv(item.call),
                    _tsv("; ".join(item.object_codes)),
                    _tsv(item.summary),
                )
            )
        )
    return "\n".join(rows) + "\n"


def _usages_for_script(
    source: str, text: str, functions: ScriptFunctionLookup, *, lua: bool | None = None
) -> list[ScriptVariableUsage]:
    lua = script_language(source) if lua is None else lua
    rows: list[ScriptVariableUsage] = []
    code_lines = script_code_text(text, lua=lua).splitlines()
    is_lua = lua is True
    starts = source_line_starts(text)
    structure = script_structure(text, lua=lua)
    views = script_views(text, lua=lua)
    for line_no, code_line in enumerate(code_lines, start=1):
        seen: set[tuple[int | None, str]] = set()
        for match in _VAR_RE.finditer(code_line):
            variable = match.group()
            offset = starts[line_no - 1] + match.start()
            owner = structure.scopes.at(offset)
            scope = owner.start if owner is not None else None
            if (scope, variable) in seen:
                continue
            seen.add((scope, variable))
            left, right = starts[line_no - 1], starts[line_no - 1] + len(code_line)
            if owner is not None:
                left = max(
                    left,
                    owner.body_start if offset >= owner.body_start else owner.start,
                )
                right = min(
                    right, owner.body_end if offset < owner.body_end else owner.end
                )
            code = structure.own_text(views.code, left, right, scope)
            raw = structure.own_text(views.arguments, left, right, scope)
            write_target = _write_target(code, is_lua)
            object_codes = tuple(sorted(set(_codes_in(code))))
            call = _line_call(code)
            rows.append(
                ScriptVariableUsage(
                    source,
                    line_no,
                    functions.name_for(source, line_no, offset=offset),
                    variable,
                    _access(variable, write_target, code),
                    _category(variable),
                    call if variable != write_target else "",
                    object_codes,
                    raw.strip(),
                )
            )
    return rows


def _write_target(line: str, is_lua: bool) -> str:
    match = _JASS_SET_RE.match(line)
    if match is not None:
        return match.group("name")
    if not is_lua:
        return ""
    stripped = line.lstrip().lower()
    if stripped.startswith(("local ", "function ", "if ", "for ", "while ", "return ")):
        return ""
    match = _LUA_ASSIGN_RE.match(line)
    return match.group("name") if match is not None else ""


def _access(variable: str, write_target: str, line: str) -> str:
    if variable != write_target:
        return "读取"
    eq_index = line.find("=")
    if eq_index >= 0 and re.search(rf"\b{re.escape(variable)}\b", line[eq_index + 1 :]):
        return "读写"
    return "写入"


def _category(variable: str) -> str:
    if variable.startswith("udg_"):
        return "用户全局"
    if variable.startswith("gg_trg_"):
        return "触发器变量"
    if variable.startswith("gg_unit_"):
        return "预放置单位"
    if variable.startswith("gg_item_"):
        return "预放置物品"
    if variable.startswith("gg_dest_"):
        return "预放置装饰物"
    if variable.startswith("gg_rct_"):
        return "区域变量"
    if variable.startswith("gg_cam_"):
        return "镜头变量"
    if variable.startswith("gg_snd_"):
        return "声音变量"
    if variable.startswith("bj_"):
        return "BJ变量"
    return "脚本变量"


def _line_call(line: str) -> str:
    match = _CALL_RE.search(line)
    return match.group(1) if match is not None else ""


def _unique_ordered(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)
