"""Grouped script call catalog for static map investigation."""

from __future__ import annotations

import re
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from .api import MapData
from .presentation_safety import tsv_cell as _tsv
from .save_api_catalog import object_api_category, save_api_info
from .save_call_context import extract_call_args, unescape_arg
from .script_scan import _codes_in
from .script_sources import analysis_script_texts
from .script_tokens import script_code_text

_CALL_RE: Final = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_FOURCC_LITERAL_RE: Final = re.compile(r"[A-Za-z0-9]{4}")


@dataclass(frozen=True, slots=True)
class ScriptCall:
    function: str
    source: str
    line: int
    mechanism: str
    object_codes: tuple[str, ...]
    string_args: tuple[str, ...]
    example: str


@dataclass(frozen=True, slots=True)
class ScriptCallRow:
    function: str
    count: int
    sources: tuple[str, ...]
    lines: tuple[str, ...]
    mechanisms: tuple[str, ...]
    object_codes: tuple[str, ...]
    string_args: tuple[str, ...]
    examples: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ScriptCallCatalog:
    calls: tuple[ScriptCall, ...]
    rows: tuple[ScriptCallRow, ...]


def build_script_call_catalog(md: MapData) -> ScriptCallCatalog:
    """Return script calls grouped by function/native name."""
    calls: list[ScriptCall] = []
    for source, text in analysis_script_texts(md):
        calls.extend(_scan_script_calls(source, text))
    return ScriptCallCatalog(calls=tuple(calls), rows=_group_calls(calls))


def format_script_call_catalog_tsv(catalog: ScriptCallCatalog) -> str:
    """Format a grouped call catalog as TSV."""
    rows = ["函数\t次数\t来源\t行号\t机制\t对象码\t字符串参数\t示例"]
    for row in catalog.rows:
        rows.append("\t".join((
            _tsv(row.function),
            str(row.count),
            _tsv("; ".join(row.sources)),
            _tsv("; ".join(row.lines)),
            _tsv("; ".join(row.mechanisms)),
            _tsv("; ".join(row.object_codes)),
            _tsv("; ".join(row.string_args)),
            _tsv(" | ".join(row.examples)),
        )))
    return "\n".join(rows) + "\n"


def _scan_script_calls(source: str, text: str) -> list[ScriptCall]:
    rows: list[ScriptCall] = []
    line_starts = _line_starts(text)
    code_text = script_code_text(text)
    for match in _CALL_RE.finditer(code_text):
        if _is_lua_function_definition(code_text, match.start()):
            continue
        name = match.group(1)
        args = extract_call_args(text, match.end())
        code_args = extract_call_args(code_text, match.end())
        object_codes = tuple(sorted(set(_codes_in(" ".join(code_args)))))
        string_args = _string_args(args, object_codes)
        rows.append(ScriptCall(
            function=name,
            source=source,
            line=bisect_right(line_starts, match.start()),
            mechanism=_mechanism(name, object_codes),
            object_codes=object_codes,
            string_args=string_args,
            example=_line_fragment(text, match.start())[:160],
        ))
    return rows


def _group_calls(calls: Iterable[ScriptCall]) -> tuple[ScriptCallRow, ...]:
    grouped: dict[str, list[ScriptCall]] = defaultdict(list)
    for call in calls:
        grouped[call.function].append(call)
    rows: list[ScriptCallRow] = []
    for function in sorted(grouped):
        items = grouped[function]
        rows.append(ScriptCallRow(
            function=function,
            count=len(items),
            sources=tuple(sorted({item.source for item in items})),
            lines=_line_summary(items),
            mechanisms=_unique_ordered(item.mechanism for item in items),
            object_codes=tuple(sorted({code for item in items for code in item.object_codes})),
            string_args=_unique_ordered(arg for item in items for arg in item.string_args),
            examples=_unique_ordered(item.example for item in items if item.example)[:3],
        ))
    return tuple(rows)


def _line_summary(items: list[ScriptCall]) -> tuple[str, ...]:
    if len({item.source for item in items}) == 1:
        return tuple(str(line) for line in sorted({item.line for item in items}))
    return tuple(sorted({f"{item.source}:{item.line}" for item in items}))


def _mechanism(name: str, object_codes: tuple[str, ...]) -> str:
    api = save_api_info(name)
    if api is not None:
        return f"{api.mechanism}:{api.operation}"
    category = object_api_category(name)
    if category is not None:
        return f"ObjectID:{category}"
    if object_codes:
        return "ObjectCode"
    return "普通调用"


def _string_args(args: tuple[str, ...], object_codes: tuple[str, ...]) -> tuple[str, ...]:
    code_set = set(object_codes)
    return _unique_ordered(
        value for value in _quoted_values(" ".join(args))
        if value and value not in code_set
    )


def _quoted_values(text: str) -> tuple[str, ...]:
    values: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char not in {"'", '"'}:
            index += 1
            continue
        value, end = _read_quoted(text, index)
        if char != "'" or not _FOURCC_LITERAL_RE.fullmatch(value):
            values.append(unescape_arg(value))
        index = end
    return tuple(values)


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


def _is_lua_function_definition(script: str, start: int) -> bool:
    line_start = script.rfind("\n", 0, start) + 1
    prefix = script[line_start:start]
    return re.search(r"\bfunction\s+(?:[A-Za-z_][A-Za-z0-9_]*[.:]?)*$", prefix) is not None


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


def _unique_ordered(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)
