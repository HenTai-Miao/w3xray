"""Script string-literal index for static map investigation."""

from __future__ import annotations

from .script_sources import analysis_script_sources, script_language

import re
from bisect import bisect_right
from dataclasses import dataclass
from typing import Final

from .api import MapData
from .presentation_safety import tsv_cell as _tsv
from .resources import RESOURCE_EXTS
from .save_api_catalog import save_api_info
from .script_lexing import script_literals
from .script_scopes import script_structure, source_line_starts
from .script_function_index import (
    ScriptFunctionLookup,
    build_function_lookup,
    build_script_function_index,
)
from .wts import map_wts_table

_CALL_RE: Final = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_TRIGSTR_RE: Final = re.compile(r"^TRIGSTR_(\d+)$", re.IGNORECASE)
_CHAT_CALLS: Final = {
    "TriggerRegisterPlayerChatEvent",
    "TriggerRegisterPlayerChatEventBJ",
}
_DISPLAY_CALLS: Final = {
    "BJDebugMsg",
    "DisplayTextToPlayer",
    "DisplayTimedTextToPlayer",
    "DisplayTextToForce",
    "DisplayTimedTextToForce",
}
_SYNC_CALLS: Final = {"BlzSendSyncData", "BlzTriggerRegisterPlayerSyncEvent"}


@dataclass(frozen=True, slots=True)
class ScriptStringEntry:
    source: str
    line: int
    function: str
    call: str
    purpose: str
    value: str
    resolved: str
    summary: str
    offset: int = 0


@dataclass(frozen=True, slots=True)
class ScriptStringIndex:
    entries: tuple[ScriptStringEntry, ...]


@dataclass(frozen=True, slots=True)
class _StringToken:
    offset: int
    line: int
    value: str
    summary: str


def build_script_string_index(md: MapData) -> ScriptStringIndex:
    """Return script string literals with source, function and purpose clues."""
    trigstr_table = _trigstr_table(md)
    functions = build_function_lookup(build_script_function_index(md).functions)
    entries: list[ScriptStringEntry] = []
    for source, text, lua in analysis_script_sources(md):
        entries.extend(
            _entries_for_script(source, text, trigstr_table, functions, lua=lua)
        )
    return ScriptStringIndex(tuple(entries))


def format_script_string_index_tsv(index: ScriptStringIndex) -> str:
    """Format script string literals as TSV."""
    rows = ["来源\t行号\t函数\t调用\t用途\t字符串\t解析文本\t摘要\t源码偏移"]
    for entry in index.entries:
        rows.append(
            "\t".join(
                (
                    _tsv(entry.source),
                    str(entry.line),
                    _tsv(entry.function),
                    _tsv(entry.call),
                    _tsv(entry.purpose),
                    _tsv(entry.value),
                    _tsv(entry.resolved),
                    _tsv(entry.summary),
                    str(entry.offset),
                )
            )
        )
    return "\n".join(rows) + "\n"


def _entries_for_script(
    source: str,
    text: str,
    trigstr_table: dict[str, str],
    functions: ScriptFunctionLookup,
    *,
    lua: bool | None = None,
) -> list[ScriptStringEntry]:
    lua = script_language(source) if lua is None else lua
    rows: list[ScriptStringEntry] = []
    structure = script_structure(text, lua=lua)
    for token in _iter_string_tokens(text, lua=lua):
        site = structure.call_scopes.at(token.offset)
        owner = structure.scopes.at(token.offset)
        call = (
            site.name
            if site is not None
            and site.owner == (owner.start if owner is not None else None)
            else ""
        )
        rows.append(
            ScriptStringEntry(
                source=source,
                line=token.line,
                function=functions.name_for(source, token.line, offset=token.offset),
                call=call,
                purpose=_purpose(call, token.value),
                value=token.value,
                resolved=_resolve_string(token.value, trigstr_table),
                summary=token.summary,
                offset=token.offset,
            )
        )
    return rows


def _iter_string_tokens(
    text: str, *, lua: bool | None = None
) -> tuple[_StringToken, ...]:
    """Keep complete literals, including multiline Lua long-bracket strings."""
    tokens: list[_StringToken] = []
    line_starts = source_line_starts(text)
    for literal in script_literals(text, lua=lua):
        if literal.object_code:
            continue
        line = bisect_right(line_starts, literal.start)
        tokens.append(
            _StringToken(
                literal.start,
                line,
                literal.value,
                text[literal.start : literal.end],
            )
        )
    return tuple(tokens)


def _line_call(line: str, column: int) -> str:
    prefix = line[:column]
    match = _CALL_RE.search(prefix)
    return match.group(1) if match is not None else ""


def _purpose(call: str, value: str) -> str:
    if _TRIGSTR_RE.fullmatch(value):
        return "UI文本"
    if call in _CHAT_CALLS:
        return "聊天指令"
    if call in _SYNC_CALLS:
        return "同步前缀"
    if _looks_like_resource_path(value):
        return "资源路径"
    if call in _DISPLAY_CALLS:
        return "显示文本"
    api = save_api_info(call)
    if api is not None and api.mechanism in {
        "GameCache",
        "Hashtable",
        "PlatformSave",
        "HashKey",
    }:
        return "存档/键"
    if value.startswith("-"):
        return "聊天指令"
    return "字符串"


def _looks_like_resource_path(value: str) -> bool:
    if "." not in value:
        return False
    ext = value.rsplit(".", 1)[-1].lower()
    return ext in RESOURCE_EXTS


def _resolve_string(value: str, trigstr_table: dict[str, str]) -> str:
    match = _TRIGSTR_RE.fullmatch(value)
    if match is None:
        return ""
    return trigstr_table.get(f"TRIGSTR_{int(match.group(1)):03d}", "")


def _trigstr_table(md: MapData) -> dict[str, str]:
    table = map_wts_table(md)
    return {f"TRIGSTR_{sid:03d}": text for sid, text in table.items()}
