"""Return-value index for static script investigation."""

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
from .script_scan import _codes_in
from .script_lexing import script_string_values, script_views
from .script_tokens import script_code_text
from .script_returns import script_returns
from .script_scopes import script_structure

_VAR_RE: Final = re.compile(
    r"\b(?:udg|bj|gg_trg|gg_unit|gg_item|gg_dest|gg_rct|gg_cam|gg_snd)_[A-Za-z0-9_]+\b",
)


@dataclass(frozen=True, slots=True)
class ScriptReturn:
    source: str
    line: int
    function: str
    expression: str
    calls: tuple[str, ...]
    variables: tuple[str, ...]
    strings: tuple[str, ...]
    object_codes: tuple[str, ...]
    purpose: str
    summary: str
    offset: int = 0
    end_line: int = 0
    end_offset: int = 0
    diagnostic: str = ""


@dataclass(frozen=True, slots=True)
class ScriptReturnIndex:
    returns: tuple[ScriptReturn, ...]


def build_script_return_index(md: MapData) -> ScriptReturnIndex:
    """Return script return expressions with save, variable and object-ID clues."""
    functions = build_function_lookup(build_script_function_index(md).functions)
    rows: list[ScriptReturn] = []
    for source, text, lua in analysis_script_sources(md):
        rows.extend(_returns_for_script(source, text, functions, lua=lua))
    return ScriptReturnIndex(tuple(rows))


def format_script_return_index_tsv(index: ScriptReturnIndex) -> str:
    """Format script return rows as TSV."""
    rows = [
        "来源\t行号\t函数\t表达式\t调用\t变量\t字符串\t对象码\t用途\t摘要\t偏移\t结束行\t结束偏移\t诊断"
    ]
    for item in index.returns:
        rows.append(
            "\t".join(
                (
                    _tsv(item.source),
                    str(item.line),
                    _tsv(item.function),
                    _tsv(item.expression),
                    _tsv("; ".join(item.calls)),
                    _tsv("; ".join(item.variables)),
                    _tsv("; ".join(item.strings)),
                    _tsv("; ".join(item.object_codes)),
                    _tsv(item.purpose),
                    _tsv(item.summary),
                    str(item.offset),
                    str(item.end_line),
                    str(item.end_offset),
                    _tsv(item.diagnostic),
                )
            )
        )
    return "\n".join(rows) + "\n"


def _returns_for_script(
    source: str, text: str, functions: ScriptFunctionLookup, *, lua: bool | None = None
) -> list[ScriptReturn]:
    lua = script_language(source) if lua is None else lua
    rows: list[ScriptReturn] = []
    for span in script_returns(text, lua=lua):
        expression = span.expression
        code_expression = script_code_text(expression, lua=lua)
        calls = _unique_ordered(
            call.name for call in script_structure(expression, lua=lua).calls
        )
        variables = _unique_ordered(
            item.group(0) for item in _VAR_RE.finditer(code_expression)
        )
        strings = _strings_in(expression, lua=lua)
        object_codes = tuple(sorted(set(_codes_in(code_expression))))
        rows.append(
            ScriptReturn(
                source=source,
                line=span.line,
                function=functions.name_for(source, span.line, offset=span.start),
                expression=expression,
                calls=calls,
                variables=variables,
                strings=strings,
                object_codes=object_codes,
                purpose=_purpose(expression, calls, variables, strings, object_codes),
                summary=script_views(text, lua=lua)
                .arguments[span.start : span.end]
                .strip(),
                offset=span.start,
                end_line=span.end_line,
                end_offset=span.end,
                diagnostic=span.diagnostic,
            )
        )
    return rows


def _purpose(
    expression: str,
    calls: tuple[str, ...],
    variables: tuple[str, ...],
    strings: tuple[str, ...],
    object_codes: tuple[str, ...],
) -> str:
    if not expression:
        return "空返回"
    if any(_is_save_call(call) for call in calls):
        return "存档返回值"
    if object_codes:
        return "对象ID返回值"
    if any(_looks_like_resource_path(value) for value in strings):
        return "资源返回值"
    if variables:
        return "状态变量返回值"
    if calls:
        return "调用返回值"
    return "普通返回值"


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
