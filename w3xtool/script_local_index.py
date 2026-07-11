"""Function-local variable index for static script investigation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from .api import MapData
from .presentation_safety import tsv_cell as _tsv
from .resources import RESOURCE_EXTS
from .script_function_index import ScriptFunction, build_script_function_index
from .script_scan import _codes_in
from .script_sources import analysis_script_texts
from .script_tokens import script_code_text

_JASS_LOCAL_RE: Final = re.compile(
    r"^\s*local\s+(?P<type>[A-Za-z_][A-Za-z0-9_]*)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?:\s*=\s*(?P<value>.*))?\s*$",
    re.IGNORECASE,
)
_LUA_LOCAL_RE: Final = re.compile(
    r"^\s*local\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?:\s*=\s*(?P<value>.*))?\s*$",
    re.IGNORECASE,
)
_FOURCC_RE: Final = re.compile(r"[A-Za-z0-9]{4}")
_FOURCC_PREFIX_RE: Final = re.compile(r"\bFourCC\s*\(\s*$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ScriptLocal:
    source: str
    line: int
    function: str
    name: str
    value_type: str
    initial: str
    string_value: str
    object_codes: tuple[str, ...]
    purpose: str
    summary: str


@dataclass(frozen=True, slots=True)
class ScriptLocalIndex:
    locals: tuple[ScriptLocal, ...]


def build_script_local_index(md: MapData) -> ScriptLocalIndex:
    """Return local variable declarations with value and object-code clues."""
    functions = build_script_function_index(md).functions
    rows: list[ScriptLocal] = []
    for source, text in analysis_script_texts(md):
        rows.extend(_locals_for_script(source, text, functions))
    return ScriptLocalIndex(tuple(rows))


def format_script_local_index_tsv(index: ScriptLocalIndex) -> str:
    """Format local variable declarations as TSV."""
    rows = ["来源\t行号\t函数\t名称\t类型\t初值\t字符串\t对象码\t用途\t摘要"]
    for item in index.locals:
        rows.append("\t".join((
            _tsv(item.source),
            str(item.line),
            _tsv(item.function),
            _tsv(item.name),
            _tsv(item.value_type),
            _tsv(item.initial),
            _tsv(item.string_value),
            _tsv("; ".join(item.object_codes)),
            _tsv(item.purpose),
            _tsv(item.summary),
        )))
    return "\n".join(rows) + "\n"


def _locals_for_script(
    source: str,
    text: str,
    functions: tuple[ScriptFunction, ...],
) -> list[ScriptLocal]:
    rows: list[ScriptLocal] = []
    code_lines = script_code_text(text).splitlines()
    raw_lines = text.splitlines()
    is_lua = source.lower().endswith(".lua")
    for line_no, code_line in enumerate(code_lines, start=1):
        match = _local_match(code_line, is_lua)
        if match is None:
            continue
        raw_line = _strip_comment(raw_lines[line_no - 1])
        value_start = code_line.find("=", match.start())
        initial = "" if value_start < 0 else raw_line[value_start + 1:].strip()
        code_initial = "" if value_start < 0 else code_line[value_start + 1:].strip()
        rows.append(_local_row(source, line_no, match, initial, code_initial, functions))
    return rows


def _local_match(line: str, is_lua: bool) -> re.Match[str] | None:
    if is_lua:
        if line.lstrip().lower().startswith("local function "):
            return None
        return _LUA_LOCAL_RE.match(line)
    return _JASS_LOCAL_RE.match(line)


def _local_row(
    source: str,
    line_no: int,
    match: re.Match[str],
    initial: str,
    code_initial: str,
    functions: tuple[ScriptFunction, ...],
) -> ScriptLocal:
    name = match.group("name")
    value_type = match.groupdict().get("type") or ""
    string_value = _first_string(initial)
    object_codes = tuple(sorted(set(_codes_in(code_initial))))
    return ScriptLocal(
        source=source,
        line=line_no,
        function=_function_for(source, line_no, functions),
        name=name,
        value_type=value_type,
        initial=initial,
        string_value=string_value,
        object_codes=object_codes,
        purpose=_purpose(name, value_type, initial, string_value, object_codes),
        summary=_strip_comment(match.string).strip()[:160],
    )


def _function_for(source: str, line: int, functions: tuple[ScriptFunction, ...]) -> str:
    for item in functions:
        if item.source == source and item.start_line <= line <= item.end_line:
            return item.name
    return ""


def _strip_comment(line: str) -> str:
    index = 0
    quote = ""
    escaped = False
    while index < len(line):
        char = line[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
        elif char in {"'", '"'}:
            quote = char
        elif line.startswith("//", index) or line.startswith("--", index):
            return line[:index]
        index += 1
    return line


def _first_string(value: str) -> str:
    index = 0
    while index < len(value):
        if value[index] not in {"'", '"'}:
            index += 1
            continue
        quote = value[index]
        raw, end = _read_quoted(value, index)
        if not _is_object_code_quote(value, index, quote, raw):
            return _unescape(raw)
        index = end
    return ""


def _is_object_code_quote(text: str, start: int, quote: str, value: str) -> bool:
    if not _FOURCC_RE.fullmatch(value):
        return False
    return quote == "'" or _FOURCC_PREFIX_RE.search(text[:start]) is not None


def _read_quoted(text: str, start: int) -> tuple[str, int]:
    quote = text[start]
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
        elif char == quote:
            return "".join(chars), index + 1
        else:
            chars.append(char)
        index += 1
    return "".join(chars), len(text)


def _purpose(
    name: str,
    value_type: str,
    initial: str,
    string_value: str,
    object_codes: tuple[str, ...],
) -> str:
    if object_codes:
        return "对象码"
    if _looks_like_resource_path(string_value):
        return "资源路径"
    if _looks_like_save_key(name, string_value):
        return "存档/键"
    if value_type.lower() == "boolean" or initial.lower() in {"true", "false"}:
        return "开关"
    return "局部变量"


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
