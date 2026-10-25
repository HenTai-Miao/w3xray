"""Loop index for static script investigation."""

from __future__ import annotations

from .script_sources import analysis_script_sources, script_language

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from .api import MapData
from .presentation_safety import tsv_cell as _tsv
from .resources import RESOURCE_EXTS
from .save_api_catalog import save_api_info
from .script_function_index import (
    ScriptFunctionLookup,
    build_function_lookup,
    build_script_function_index,
)
from .script_scopes import source_line_starts
from .script_scan import _codes_in
from .script_lexing import script_string_values, script_views
from .script_tokens import script_code_text

_LOOP_RE: Final = re.compile(r"^\s*loop\b", re.IGNORECASE)
_EXITWHEN_RE: Final = re.compile(r"^\s*exitwhen\s+(?P<expr>.+?)\s*$", re.IGNORECASE)
_WHILE_RE: Final = re.compile(r"^\s*while\s+(?P<expr>.+?)\s+do\b", re.IGNORECASE)
_FOR_RE: Final = re.compile(r"^\s*for\s+(?P<expr>.+?)\s+do\b", re.IGNORECASE)
_REPEAT_RE: Final = re.compile(r"^\s*repeat\b", re.IGNORECASE)
_UNTIL_RE: Final = re.compile(r"^\s*until\s+(?P<expr>.+?)\s*$", re.IGNORECASE)
_CALL_RE: Final = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_VAR_RE: Final = re.compile(
    r"\b(?:udg|bj|gg_trg|gg_unit|gg_item|gg_dest|gg_rct|gg_cam|gg_snd)_[A-Za-z0-9_]+\b",
)


@dataclass(frozen=True, slots=True)
class ScriptLoop:
    source: str
    line: int
    function: str
    loop_type: str
    expression: str
    calls: tuple[str, ...]
    variables: tuple[str, ...]
    strings: tuple[str, ...]
    object_codes: tuple[str, ...]
    purpose: str
    summary: str


@dataclass(frozen=True, slots=True)
class ScriptLoopIndex:
    loops: tuple[ScriptLoop, ...]


def build_script_loop_index(md: MapData) -> ScriptLoopIndex:
    """Return loop constructs and exit conditions with static clues."""
    functions = build_function_lookup(build_script_function_index(md).functions)
    rows: list[ScriptLoop] = []
    for source, text, lua in analysis_script_sources(md):
        rows.extend(_loops_for_script(source, text, functions, lua=lua))
    return ScriptLoopIndex(tuple(rows))


def format_script_loop_index_tsv(index: ScriptLoopIndex) -> str:
    """Format loop rows as TSV."""
    rows = ["来源\t行号\t函数\t类型\t表达式\t调用\t变量\t字符串\t对象码\t用途\t摘要"]
    for item in index.loops:
        rows.append(
            "\t".join(
                (
                    _tsv(item.source),
                    str(item.line),
                    _tsv(item.function),
                    _tsv(item.loop_type),
                    _tsv(item.expression),
                    _tsv("; ".join(item.calls)),
                    _tsv("; ".join(item.variables)),
                    _tsv("; ".join(item.strings)),
                    _tsv("; ".join(item.object_codes)),
                    _tsv(item.purpose),
                    _tsv(item.summary),
                )
            )
        )
    return "\n".join(rows) + "\n"


def _loops_for_script(
    source: str,
    text: str,
    functions: ScriptFunctionLookup,
    *,
    lua: bool | None = None,
) -> list[ScriptLoop]:
    lua = script_language(source) if lua is None else lua
    rows: list[ScriptLoop] = []
    code_lines = script_code_text(text, lua=lua).splitlines()
    raw_lines = script_views(text, lua=lua).arguments.splitlines()
    line_offsets = source_line_starts(text)
    for line_no, code_line in enumerate(code_lines, start=1):
        item = _loop_match(code_line)
        if item is None:
            continue
        loop_type, start, end = item
        raw_line = raw_lines[line_no - 1]
        expression = raw_line[start:end].strip() if start != end else ""
        code_expression = code_line[start:end]
        calls = _unique_ordered(
            match.group(1) for match in _CALL_RE.finditer(code_expression)
        )
        variables = _unique_ordered(
            match.group(0) for match in _VAR_RE.finditer(code_expression)
        )
        strings = _strings_in(expression, lua=lua)
        object_codes = tuple(sorted(set(_codes_in(code_expression))))
        rows.append(
            ScriptLoop(
                source=source,
                line=line_no,
                function=functions.name_for(
                    source,
                    line_no,
                    offset=line_offsets[line_no - 1]
                    + len(code_line)
                    - len(code_line.lstrip()),
                ),
                loop_type=loop_type,
                expression=expression,
                calls=calls,
                variables=variables,
                strings=strings,
                object_codes=object_codes,
                purpose=_purpose(loop_type, calls, variables, strings, object_codes),
                summary=raw_line.strip(),
            )
        )
    return rows


def _loop_match(line: str) -> tuple[str, int, int] | None:
    for kind, pattern in (
        ("exitwhen", _EXITWHEN_RE),
        ("while", _WHILE_RE),
        ("for", _FOR_RE),
        ("until", _UNTIL_RE),
    ):
        match = pattern.match(line)
        if match is not None:
            end = match.end() - 2 if kind in {"while", "for"} else len(line)
            return kind, match.start("expr"), end
    if _LOOP_RE.match(line) is not None:
        return "loop", 0, 0
    if _REPEAT_RE.match(line) is not None:
        return "repeat", 0, 0
    return None


def _purpose(
    loop_type: str,
    calls: tuple[str, ...],
    variables: tuple[str, ...],
    strings: tuple[str, ...],
    object_codes: tuple[str, ...],
) -> str:
    if loop_type in {"loop", "repeat"}:
        return "普通循环"
    if any(_is_save_call(call) for call in calls):
        return "存档循环条件"
    if object_codes:
        return "对象ID循环条件"
    if any(_looks_like_resource_path(value) for value in strings):
        return "资源循环条件"
    if variables:
        return "状态变量循环条件"
    if calls:
        return "调用循环条件"
    return "普通循环条件"


def _is_save_call(name: str) -> bool:
    return save_api_info(name) is not None or name == "StringHash"


def _looks_like_resource_path(value: str) -> bool:
    if "." not in value:
        return False
    return value.rsplit(".", 1)[-1].lower() in RESOURCE_EXTS


def _strings_in(text: str, *, lua: bool | None = None) -> tuple[str, ...]:
    return _unique_ordered(
        script_string_values(text, lua=lua, include_object_codes=False)
    )


def _unique_ordered(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)
