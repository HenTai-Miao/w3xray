"""Script assignment index for static map investigation."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Final

from .api import MapData
from .resources import RESOURCE_EXTS
from .script_function_index import ScriptFunction, build_script_function_index
from .script_scan import _codes_in
from .script_sources import analysis_script_texts
from .script_tokens import script_code_text

_JASS_SET_RE: Final = re.compile(
    r"^\s*set\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?:\[(?P<index>[^\]]+)\])?\s*=\s*",
)
_LUA_ASSIGN_RE: Final = re.compile(
    r"^\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?:\[(?P<index>[^\]]+)\])?\s*=\s*",
)
_FOURCC_RE: Final = re.compile(r"[A-Za-z0-9]{4}")


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
    functions = build_script_function_index(md).functions
    rows: list[ScriptAssignment] = []
    for source, text in analysis_script_texts(md):
        rows.extend(_assignments_for_script(source, text, functions))
    return ScriptAssignmentIndex(tuple(rows))


def format_script_assignment_index_tsv(index: ScriptAssignmentIndex) -> str:
    """Format script assignments as TSV."""
    rows = ["来源\t行号\t函数\t变量\t索引\t右值\t字符串\t对象码\t用途\t摘要"]
    for item in index.assignments:
        rows.append("\t".join((
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
        )))
    return "\n".join(rows) + "\n"


def _assignments_for_script(
    source: str,
    text: str,
    functions: tuple[ScriptFunction, ...],
) -> list[ScriptAssignment]:
    rows: list[ScriptAssignment] = []
    code_lines = script_code_text(text).splitlines()
    raw_lines = text.splitlines()
    is_lua = source.lower().endswith(".lua")
    for line_no, code_line in enumerate(code_lines, start=1):
        match = _assignment_match(code_line, is_lua)
        if match is None:
            continue
        raw_line = raw_lines[line_no - 1]
        value_start = code_line.find("=", match.start()) + 1
        value = _strip_comment(raw_line)[value_start:].strip()
        rows.append(_assignment_row(source, line_no, match, value, functions))
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
    functions: tuple[ScriptFunction, ...],
) -> ScriptAssignment:
    variable = match.group("name")
    index = (match.group("index") or "").strip()
    string_value = _first_string(value)
    object_codes = tuple(sorted(set(_codes_in(value))))
    return ScriptAssignment(
        source=source,
        line=line_no,
        function=_function_for(source, line_no, functions),
        variable=variable,
        index=index,
        value=value,
        string_value=string_value,
        object_codes=object_codes,
        purpose=_purpose(variable, index, value, string_value, object_codes),
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
        if not (quote == "'" and _FOURCC_RE.fullmatch(raw)):
            return _unescape(raw)
        index = end
    return ""


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
    if any(word in lowered for word in ("save", "cache", "key", "load", "slot", "password")):
        return True
    return "." in value and not _looks_like_resource_path(value)


def _unescape(value: str) -> str:
    return value.replace("\\\\", "\\").replace('\\"', '"').replace("\\'", "'")


def _tsv(value: str) -> str:
    return value.replace("\t", " ").replace("\r", " ").replace("\n", " ")
