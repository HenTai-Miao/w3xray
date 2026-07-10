"""Script string-literal index for static map investigation."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Final

from .api import MapData
from .resources import RESOURCE_EXTS
from .save_api_catalog import save_api_info
from .script_function_index import ScriptFunction, build_script_function_index
from .script_sources import analysis_script_texts
from .wts import parse_wts

_CALL_RE: Final = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_TRIGSTR_RE: Final = re.compile(r"^TRIGSTR_(\d+)$", re.IGNORECASE)
_FOURCC_RE: Final = re.compile(r"[A-Za-z0-9]{4}")
_CHAT_CALLS: Final = {"TriggerRegisterPlayerChatEvent", "TriggerRegisterPlayerChatEventBJ"}
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


@dataclass(frozen=True, slots=True)
class ScriptStringIndex:
    entries: tuple[ScriptStringEntry, ...]


@dataclass(frozen=True, slots=True)
class _StringToken:
    line: int
    column: int
    value: str
    summary: str


def build_script_string_index(md: MapData) -> ScriptStringIndex:
    """Return script string literals with source, function and purpose clues."""
    trigstr_table = _trigstr_table(md)
    functions = build_script_function_index(md).functions
    entries: list[ScriptStringEntry] = []
    for source, text in analysis_script_texts(md):
        entries.extend(_entries_for_script(source, text, trigstr_table, functions))
    return ScriptStringIndex(tuple(entries))


def format_script_string_index_tsv(index: ScriptStringIndex) -> str:
    """Format script string literals as TSV."""
    rows = ["来源\t行号\t函数\t调用\t用途\t字符串\t解析文本\t摘要"]
    for entry in index.entries:
        rows.append("\t".join((
            _tsv(entry.source),
            str(entry.line),
            _tsv(entry.function),
            _tsv(entry.call),
            _tsv(entry.purpose),
            _tsv(entry.value),
            _tsv(entry.resolved),
            _tsv(entry.summary),
        )))
    return "\n".join(rows) + "\n"


def _entries_for_script(
    source: str,
    text: str,
    trigstr_table: dict[str, str],
    functions: tuple[ScriptFunction, ...],
) -> list[ScriptStringEntry]:
    rows: list[ScriptStringEntry] = []
    for token in _iter_string_tokens(text):
        call = _line_call(token.summary, token.column)
        rows.append(ScriptStringEntry(
            source=source,
            line=token.line,
            function=_function_for(source, token.line, functions),
            call=call,
            purpose=_purpose(call, token.value),
            value=token.value,
            resolved=_resolve_string(token.value, trigstr_table),
            summary=token.summary[:160],
        ))
    return rows


def _iter_string_tokens(text: str) -> tuple[_StringToken, ...]:
    tokens: list[_StringToken] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        index = 0
        while index < len(line):
            if _starts_comment(line, index):
                break
            char = line[index]
            if char not in {"'", '"'}:
                index += 1
                continue
            value, end = _read_quoted(line, index)
            if not (char == "'" and _FOURCC_RE.fullmatch(value)):
                tokens.append(_StringToken(
                    line=line_no,
                    column=index,
                    value=_unescape(value),
                    summary=line.strip(),
                ))
            index = end
    return tuple(tokens)


def _starts_comment(line: str, index: int) -> bool:
    return (
        line.startswith("//", index)
        or line.startswith("--", index)
    )


def _read_quoted(line: str, start: int) -> tuple[str, int]:
    quote = line[start]
    chars: list[str] = []
    index = start + 1
    escaped = False
    while index < len(line):
        char = line[index]
        if escaped:
            chars.append("\\" + char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == quote:
            return "".join(chars), index + 1
        else:
            chars.append(char)
        index += 1
    return "".join(chars), len(line)


def _line_call(line: str, column: int) -> str:
    prefix = line[:column]
    match = _CALL_RE.search(prefix)
    return match.group(1) if match is not None else ""


def _function_for(source: str, line: int, functions: tuple[ScriptFunction, ...]) -> str:
    for item in functions:
        if item.source == source and item.start_line <= line <= item.end_line:
            return item.name
    return ""


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
    if api is not None and api.mechanism in {"GameCache", "Hashtable", "PlatformSave", "HashKey"}:
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
    raw = md.scripts.get("war3map.wts") or md.scripts.get("war3campaign.wts")
    if not raw:
        return {}
    table = parse_wts(raw.encode("utf-8", "replace"))
    return {f"TRIGSTR_{sid:03d}": text for sid, text in table.items()}


def _unescape(value: str) -> str:
    return value.replace("\\\\", "\\").replace('\\"', '"').replace("\\'", "'")


def _tsv(value: str) -> str:
    return value.replace("\t", " ").replace("\r", " ").replace("\n", " ")
