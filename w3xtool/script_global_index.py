"""JASS globals index for static map investigation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from .api import MapData
from .presentation_safety import tsv_cell as _tsv
from .resources import RESOURCE_EXTS
from .script_scan import _codes_in
from .script_sources import analysis_script_texts
from .script_tokens import strip_line_comment as _strip_comment

_GLOBAL_DECL_RE: Final = re.compile(
    r"^\s*(?:(?:private|public)\s+)?"
    r"(?P<constant>constant\s+)?"
    r"(?P<type>[A-Za-z_][A-Za-z0-9_]*)\s+"
    r"(?P<array>array\s+)?"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?:\s*=\s*(?P<value>.*))?\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ScriptGlobal:
    source: str
    line: int
    name: str
    value_type: str
    is_array: bool
    is_constant: bool
    initial: str
    string_value: str
    object_codes: tuple[str, ...]
    purpose: str
    summary: str


@dataclass(frozen=True, slots=True)
class ScriptGlobalIndex:
    globals: tuple[ScriptGlobal, ...]


def build_script_global_index(md: MapData) -> ScriptGlobalIndex:
    """Return globals declared in JASS scripts with static value clues."""
    rows: list[ScriptGlobal] = []
    for source, text in analysis_script_texts(md):
        rows.extend(_globals_for_script(source, text))
    return ScriptGlobalIndex(tuple(rows))


def format_script_global_index_tsv(index: ScriptGlobalIndex) -> str:
    """Format JASS global variables as TSV."""
    rows = ["来源\t行号\t名称\t类型\t数组\t常量\t初值\t字符串\t对象码\t用途\t摘要"]
    for item in index.globals:
        rows.append("\t".join((
            _tsv(item.source),
            str(item.line),
            _tsv(item.name),
            _tsv(item.value_type),
            _yes_no(item.is_array),
            _yes_no(item.is_constant),
            _tsv(item.initial),
            _tsv(item.string_value),
            _tsv("; ".join(item.object_codes)),
            _tsv(item.purpose),
            _tsv(item.summary),
        )))
    return "\n".join(rows) + "\n"


def _globals_for_script(source: str, text: str) -> list[ScriptGlobal]:
    rows: list[ScriptGlobal] = []
    inside = False
    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = _strip_comment(raw_line).strip()
        if not line:
            continue
        marker = line.lower()
        if not inside:
            inside = marker == "globals"
            continue
        if marker == "endglobals":
            inside = False
            continue
        row = _parse_global(source, line_no, line)
        if row is not None:
            rows.append(row)
    return rows


def _parse_global(source: str, line_no: int, line: str) -> ScriptGlobal | None:
    match = _GLOBAL_DECL_RE.match(line)
    if match is None:
        return None
    initial = (match.group("value") or "").strip()
    name = match.group("name")
    value_type = match.group("type")
    is_array = match.group("array") is not None
    is_constant = match.group("constant") is not None
    string_value = _first_string(initial)
    object_codes = tuple(sorted(set(_codes_in(initial))))
    return ScriptGlobal(
        source=source,
        line=line_no,
        name=name,
        value_type=value_type,
        is_array=is_array,
        is_constant=is_constant,
        initial=initial,
        string_value=string_value,
        object_codes=object_codes,
        purpose=_purpose(name, value_type, is_array, string_value, object_codes),
        summary=line[:160],
    )




def _first_string(value: str) -> str:
    index = 0
    while index < len(value):
        if value[index] != '"':
            index += 1
            continue
        raw, _end = _read_quoted(value, index)
        return _unescape(raw)
    return ""


def _read_quoted(text: str, start: int) -> tuple[str, int]:
    chars: list[str] = []
    index = start + 1
    escaped = False
    while index < len(text):
        char = text[index]
        if escaped:
            chars.append("\\" + char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            return "".join(chars), index + 1
        else:
            chars.append(char)
        index += 1
    return "".join(chars), len(text)


def _purpose(
    name: str,
    value_type: str,
    is_array: bool,
    string_value: str,
    object_codes: tuple[str, ...],
) -> str:
    if object_codes:
        return "对象码"
    if _looks_like_resource_path(string_value):
        return "资源路径"
    if _looks_like_save_key(name, string_value):
        return "存档/键"
    if value_type.lower() == "boolean":
        return "开关"
    if is_array:
        return "数组状态"
    return "全局变量"


def _looks_like_resource_path(value: str) -> bool:
    if "." not in value:
        return False
    return value.rsplit(".", 1)[-1].lower() in RESOURCE_EXTS


def _looks_like_save_key(name: str, value: str) -> bool:
    lowered = f"{name} {value}".lower()
    if any(word in lowered for word in ("save", "cache", "key", "load", "slot", "password")):
        return True
    return "." in value and not _looks_like_resource_path(value)


def _unescape(value: str) -> str:
    return value.replace("\\\\", "\\").replace('\\"', '"').replace("\\'", "'")


def _yes_no(value: bool) -> str:
    return "是" if value else "否"
