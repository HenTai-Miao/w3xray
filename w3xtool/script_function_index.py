"""Function-scoped script index for static map investigation."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import re
from typing import Final

from .api import MapData
from .script_call_catalog import ScriptCall, build_script_call_catalog
from .script_sources import analysis_script_texts
from .script_tokens import script_code_text

_JASS_FUNCTION_RE: Final = re.compile(r"^\s*function\s+([A-Za-z_][A-Za-z0-9_]*)\b")
_LUA_FUNCTION_RE: Final = re.compile(
    r"^\s*(?:local\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*(?:[.:][A-Za-z_][A-Za-z0-9_]*)*)\s*\(",
)
_LUA_OPEN_RE: Final = re.compile(r"\b(function|then|do|repeat)\b")
_LUA_CLOSE_RE: Final = re.compile(r"\b(end|until)\b")


@dataclass(frozen=True, slots=True)
class ScriptFunction:
    name: str
    source: str
    start_line: int
    end_line: int
    inbound_calls: int
    internal_calls: int
    mechanisms: tuple[str, ...]
    object_codes: tuple[str, ...]
    called_functions: tuple[str, ...]
    summary: str

    @property
    def line_count(self) -> int:
        return self.end_line - self.start_line + 1


@dataclass(frozen=True, slots=True)
class ScriptFunctionIndex:
    functions: tuple[ScriptFunction, ...]


@dataclass(frozen=True, slots=True)
class _FunctionRange:
    name: str
    source: str
    start_line: int
    end_line: int
    summary: str


def build_script_function_index(md: MapData) -> ScriptFunctionIndex:
    """Return function ranges with function-scoped call and object-code clues."""
    calls = build_script_call_catalog(md).calls
    ranges = tuple(
        item
        for source, text in analysis_script_texts(md)
        for item in _function_ranges(source, text)
    )
    functions = tuple(_function_row(item, calls) for item in ranges)
    return ScriptFunctionIndex(tuple(sorted(functions, key=_function_sort_key)))


def format_script_function_index_tsv(index: ScriptFunctionIndex) -> str:
    """Format function-scoped script clues as TSV."""
    rows = ["函数\t来源\t起始行\t结束行\t行数\t被调用次数\t内部调用数\t机制\t对象码\t调用函数\t摘要"]
    for item in index.functions:
        rows.append("\t".join((
            _tsv(item.name),
            _tsv(item.source),
            str(item.start_line),
            str(item.end_line),
            str(item.line_count),
            str(item.inbound_calls),
            str(item.internal_calls),
            _tsv("; ".join(item.mechanisms)),
            _tsv("; ".join(item.object_codes)),
            _tsv("; ".join(item.called_functions)),
            _tsv(item.summary),
        )))
    return "\n".join(rows) + "\n"


def _function_ranges(source: str, text: str) -> Iterable[_FunctionRange]:
    lines = text.splitlines()
    code_lines = script_code_text(text).splitlines()
    index = 0
    while index < len(code_lines):
        lua_match = _LUA_FUNCTION_RE.match(code_lines[index])
        if lua_match is not None:
            end_index = _lua_end_index(code_lines, index)
            yield _FunctionRange(
                name=lua_match.group(1),
                source=source,
                start_line=index + 1,
                end_line=end_index + 1,
                summary=lines[index].strip()[:160],
            )
            index = end_index + 1
            continue
        jass_match = _JASS_FUNCTION_RE.match(code_lines[index])
        if jass_match is not None:
            end_index = _jass_end_index(code_lines, index)
            yield _FunctionRange(
                name=jass_match.group(1),
                source=source,
                start_line=index + 1,
                end_line=end_index + 1,
                summary=lines[index].strip()[:160],
            )
            index = end_index + 1
            continue
        index += 1


def _function_row(item: _FunctionRange, calls: tuple[ScriptCall, ...]) -> ScriptFunction:
    internal = tuple(call for call in calls if _inside(item, call) and _is_primary_call(call))
    inbound = tuple(
        call for call in calls
        if call.function == item.name and not _inside(item, call) and _is_primary_call(call)
    )
    return ScriptFunction(
        name=item.name,
        source=item.source,
        start_line=item.start_line,
        end_line=item.end_line,
        inbound_calls=len(inbound),
        internal_calls=len(internal),
        mechanisms=_mechanism_summary(internal),
        object_codes=tuple(sorted({code for call in internal for code in call.object_codes})),
        called_functions=_unique_ordered(call.function for call in internal),
        summary=item.summary,
    )


def _inside(item: _FunctionRange, call: ScriptCall) -> bool:
    return call.source == item.source and item.start_line <= call.line <= item.end_line


def _mechanism_summary(calls: tuple[ScriptCall, ...]) -> tuple[str, ...]:
    values = _unique_ordered(call.mechanism for call in calls)
    explicit = tuple(value for value in values if value != "普通调用")
    return explicit or values


def _is_primary_call(call: ScriptCall) -> bool:
    match = re.search(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(", call.example)
    return match is not None and match.group(1) == call.function


def _jass_end_index(lines: list[str], start: int) -> int:
    for index in range(start + 1, len(lines)):
        if re.match(r"^\s*endfunction\b", lines[index]):
            return index
    return len(lines) - 1


def _lua_end_index(lines: list[str], start: int) -> int:
    depth = 1
    for index in range(start + 1, len(lines)):
        line = lines[index]
        depth += len(_LUA_OPEN_RE.findall(line))
        depth -= len(_LUA_CLOSE_RE.findall(line))
        if depth <= 0:
            return index
    return len(lines) - 1


def _unique_ordered(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)


def _function_sort_key(item: ScriptFunction) -> tuple[str, int, str]:
    return item.source, item.start_line, item.name


def _tsv(value: str) -> str:
    return value.replace("\t", " ").replace("\r", " ").replace("\n", " ")
