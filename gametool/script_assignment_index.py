"""Script assignment index for static map investigation."""

from __future__ import annotations

from .script_sources import analysis_script_sources, script_language

import re
from dataclasses import dataclass
from typing import Final

from .api import MapData
from .presentation_safety import tsv_cell as _tsv
from .resources import RESOURCE_EXTS
from .script_function_index import (
    ScriptFunctionLookup,
    build_function_lookup,
    build_script_function_index,
)
from .script_scan import _codes_in
from .script_lexing import script_string_values, script_views
from .script_tokens import script_code_text
from .script_scopes import source_line_starts

_JASS_SET_RE: Final = re.compile(
    r"^\s*set\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?:\[(?P<index>[^\]]+)\])?\s*=\s*",
)
_LUA_ASSIGN_RE: Final = re.compile(
    r"^\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?:\[(?P<index>[^\]]+)\])?\s*=\s*",
)


@dataclass(frozen=True, slots=True)
class ScriptAssignment:
    source: str
    line: int
    function: str
    variable: str
    index: str
    value: str
    string_value: str
    object_codes: tuple[str, ...]
    purpose: str
    summary: str


@dataclass(frozen=True, slots=True)
class ScriptAssignmentIndex:
    assignments: tuple[ScriptAssignment, ...]


def build_script_assignment_index(md: MapData) -> ScriptAssignmentIndex:
    """Return script variable assignments with value and purpose clues."""
    functions = build_function_lookup(build_script_function_index(md).functions)
    rows: list[ScriptAssignment] = []
    for source, text, lua in analysis_script_sources(md):
        rows.extend(_assignments_for_script(source, text, functions, lua=lua))
    return ScriptAssignmentIndex(tuple(rows))


def format_script_assignment_index_tsv(index: ScriptAssignmentIndex) -> str:
    """Format script assignments as TSV."""
    rows = ["来源\t行号\t函数\t变量\t索引\t右值\t字符串\t对象码\t用途\t摘要"]
    for item in index.assignments:
        rows.append(
            "\t".join(
                (
                    _tsv(item.source),
                    str(item.line),
                    _tsv(item.function),
                    _tsv(item.variable),
                    _tsv(item.index),
                    _tsv(item.value),
                    _tsv(item.string_value),
                    _tsv("; ".join(item.object_codes)),
                    _tsv(item.purpose),
                    _tsv(item.summary),
                )
            )
        )
    return "\n".join(rows) + "\n"


def _assignments_for_script(
    source: str, text: str, functions: ScriptFunctionLookup, *, lua: bool | None = None
) -> list[ScriptAssignment]:
    lua = script_language(source) if lua is None else lua
    rows: list[ScriptAssignment] = []
    code_lines = script_code_text(text, lua=lua).splitlines()
    raw_lines = script_views(text, lua=lua).arguments.splitlines()
    is_lua = lua is True
    line_offsets = source_line_starts(text)
    for line_no, code_line in enumerate(code_lines, start=1):
        match = _assignment_match(code_line, is_lua)
        if match is None:
            continue
        raw_line = raw_lines[line_no - 1]
        value_start = code_line.find("=", match.start()) + 1
        value = raw_line[value_start:].strip()
        rows.append(
            _assignment_row(
                source,
                line_no,
                match,
                value,
                functions,
                lua=lua,
                offset=line_offsets[line_no - 1] + match.start("name"),
            )
        )
    return rows


def _assignment_match(line: str, is_lua: bool) -> re.Match[str] | None:
    match = _JASS_SET_RE.match(line)
    if match is not None:
        return match
    if not is_lua:
        return None
    stripped = line.lstrip().lower()
    if stripped.startswith(("local ", "function ", "if ", "for ", "while ", "return ")):
        return None
    return _LUA_ASSIGN_RE.match(line)


def _assignment_row(
    source: str,
    line_no: int,
    match: re.Match[str],
    value: str,
    functions: ScriptFunctionLookup,
    *,
    lua: bool | None = None,
    offset: int | None = None,
) -> ScriptAssignment:
    lua = script_language(source) if lua is None else lua
    variable = match.group("name")
    index = (match.group("index") or "").strip()
    string_value = _first_string(value, lua=lua)
    object_codes = tuple(sorted(set(_codes_in(script_views(value, lua=lua).code))))
    return ScriptAssignment(
        source=source,
        line=line_no,
        function=functions.name_for(source, line_no, offset=offset),
        variable=variable,
        index=index,
        value=value,
        string_value=string_value,
        object_codes=object_codes,
        purpose=_purpose(variable, index, value, string_value, object_codes),
        summary=match.string.strip(),
    )


def _first_string(value: str, *, lua: bool | None = None) -> str:
    return next(script_string_values(value, lua=lua, include_object_codes=False), "")


def _purpose(
    variable: str,
    index: str,
    value: str,
    string_value: str,
    object_codes: tuple[str, ...],
) -> str:
    if object_codes:
        return "对象码"
    if _looks_like_resource_path(string_value):
        return "资源路径"
    if _looks_like_save_key(variable, string_value):
        return "存档/键"
    if index:
        return "数组状态"
    if value.lower() in {"true", "false"}:
        return "开关"
    return "变量赋值"


def _looks_like_resource_path(value: str) -> bool:
    if "." not in value:
        return False
    return value.rsplit(".", 1)[-1].lower() in RESOURCE_EXTS


def _looks_like_save_key(variable: str, value: str) -> bool:
    lowered = f"{variable} {value}".lower()
    if any(
        word in lowered for word in ("save", "cache", "key", "load", "slot", "password")
    ):
        return True
    return "." in value and not _looks_like_resource_path(value)
