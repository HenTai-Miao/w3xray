"""Per-call script argument index for static map investigation."""

from __future__ import annotations

from .script_sources import analysis_script_sources, script_language

import re
from bisect import bisect_right
from dataclasses import dataclass
from typing import Final

from .map_data import MapData
from .presentation_safety import tsv_cell as _tsv
from .resources import RESOURCE_EXTS
from .save_api_catalog import object_api_category, save_api_info
from .save_call_context import extract_call_args
from .script_function_index import (
    ScriptFunctionLookup,
    build_function_lookup,
    build_script_function_index,
)
from .script_scan import _codes_in
from .script_lexing import script_string_values, script_views
from .script_scopes import script_structure, source_line_starts

_CALL_RE: Final = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")


@dataclass(frozen=True, slots=True)
class ScriptCallArgument:
    source: str
    line: int
    function: str
    call: str
    position: int
    argument: str
    string_value: str
    object_codes: tuple[str, ...]
    mechanism: str
    purpose: str
    summary: str
    call_offset: int | None = None
    primary: bool = True


@dataclass(frozen=True, slots=True)
class ScriptCallArgumentIndex:
    arguments: tuple[ScriptCallArgument, ...]


def build_script_call_argument_index(md: MapData) -> ScriptCallArgumentIndex:
    """Return each script call argument with save, resource and object-code clues."""
    functions = build_function_lookup(build_script_function_index(md).functions)
    rows: list[ScriptCallArgument] = []
    for source, text, lua in analysis_script_sources(md):
        rows.extend(_arguments_for_script(source, text, functions, lua=lua))
    return ScriptCallArgumentIndex(tuple(rows))


def format_script_call_argument_index_tsv(index: ScriptCallArgumentIndex) -> str:
    """Format call arguments as TSV."""
    rows = [
        "来源\t行号\t函数\t调用\t参数序号\t参数\t字符串\t对象码\t机制\t用途\t摘要\t调用偏移"
    ]
    seen: set[tuple[str, int]] = set()
    for item in index.arguments:
        summary = item.summary
        if item.call_offset is not None:
            key = (item.source, item.call_offset)
            if key in seen:
                summary = ""
            seen.add(key)
        rows.append(
            "\t".join(
                (
                    _tsv(item.source),
                    str(item.line),
                    _tsv(item.function),
                    _tsv(item.call),
                    str(item.position),
                    _tsv(item.argument),
                    _tsv(item.string_value),
                    _tsv("; ".join(item.object_codes)),
                    _tsv(item.mechanism),
                    _tsv(item.purpose),
                    _tsv(summary),
                    str(item.call_offset) if item.call_offset is not None else "",
                )
            )
        )
    return "\n".join(rows) + "\n"


def _arguments_for_script(
    source: str, text: str, functions: ScriptFunctionLookup, *, lua: bool | None = None
) -> list[ScriptCallArgument]:
    lua = script_language(source) if lua is None else lua
    rows: list[ScriptCallArgument] = []
    line_starts = source_line_starts(text)
    views = script_views(text, lua=lua)
    structure = script_structure(text, lua=lua)
    for site in structure.calls:
        raw_args = extract_call_args(views, site.open + 1)
        own_code = structure.own_text(views.code, site.start, site.end, site.owner)
        own_arguments = structure.own_text(
            views.arguments, site.start, site.end, site.owner
        )
        code_args = extract_call_args(
            own_code, site.open - site.start + 1, lua=lua, mask_strings=True
        )
        value_args = extract_call_args(
            own_arguments, site.open - site.start + 1, lua=lua
        )
        line_no = bisect_right(line_starts, site.start)
        call = site.name
        mechanism = _mechanism(call)
        rows.extend(
            _argument_rows(
                source,
                line_no,
                functions.name_for(source, line_no, offset=site.start),
                call,
                mechanism,
                raw_args,
                code_args,
                text[site.start : site.end],
                lua=lua,
                value_args=value_args,
                call_offset=site.start,
                primary=site.primary,
            )
        )
    return rows


def _argument_rows(
    source: str,
    line_no: int,
    function: str,
    call: str,
    mechanism: str,
    raw_args: tuple[str, ...],
    code_args: tuple[str, ...],
    summary: str,
    *,
    lua: bool | None = None,
    value_args: tuple[str, ...] | None = None,
    call_offset: int | None = None,
    primary: bool = True,
) -> list[ScriptCallArgument]:
    lua = script_language(source) if lua is None else lua
    rows: list[ScriptCallArgument] = []
    for index, raw_arg in enumerate(raw_args, start=1):
        code_arg = code_args[index - 1] if index <= len(code_args) else raw_arg
        object_codes = tuple(sorted(set(_codes_in(code_arg))))
        value_arg = (
            value_args[index - 1]
            if value_args is not None and index <= len(value_args)
            else raw_arg
        )
        string_value = _first_string(value_arg, lua=lua)
        rows.append(
            ScriptCallArgument(
                source=source,
                line=line_no,
                function=function,
                call=call,
                position=index,
                argument=raw_arg,
                string_value=string_value,
                object_codes=object_codes,
                mechanism=mechanism,
                purpose=_purpose(call, mechanism, string_value, object_codes),
                summary=summary,
                call_offset=call_offset,
                primary=primary,
            )
        )
    return rows


def _mechanism(call: str) -> str:
    call = call.removeprefix("_G.")
    api = save_api_info(call)
    if api is not None:
        return f"{api.mechanism}:{api.operation}"
    category = object_api_category(call)
    if category is not None:
        return f"ObjectID:{category}"
    return "普通调用"


def _purpose(
    call: str,
    mechanism: str,
    string_value: str,
    object_codes: tuple[str, ...],
) -> str:
    if object_codes:
        return "对象码"
    if _looks_like_resource_path(string_value):
        return "资源路径"
    if _looks_like_save_key(call, mechanism, string_value):
        return "存档/键"
    if string_value:
        return "字符串"
    return "普通参数"


def _first_string(value: str, *, lua: bool | None = None) -> str:
    return next(script_string_values(value, lua=lua, include_object_codes=False), "")


def _looks_like_resource_path(value: str) -> bool:
    if "." not in value:
        return False
    return value.rsplit(".", 1)[-1].lower() in RESOURCE_EXTS


def _looks_like_save_key(call: str, mechanism: str, value: str) -> bool:
    if mechanism.split(":", 1)[0] in {
        "GameCache",
        "Hashtable",
        "PlatformSave",
        "HashKey",
        "Sync",
    }:
        return bool(value)
    lowered = f"{call} {value}".lower()
    if any(
        word in lowered for word in ("save", "cache", "key", "load", "slot", "password")
    ):
        return True
    return "." in value and not _looks_like_resource_path(value)


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
