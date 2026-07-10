"""Condition branch index for static script investigation."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import re
from typing import Final

from .api import MapData
from .resources import RESOURCE_EXTS
from .save_api_catalog import save_api_info
from .save_call_context import unescape_arg
from .script_function_index import ScriptFunction, build_script_function_index
from .script_scan import _codes_in
from .script_sources import analysis_script_texts
from .script_tokens import script_code_text

_BRANCH_RE: Final = re.compile(
    r"^\s*(?P<branch>if|elseif)\s+(?P<condition>.+?)\s+then\b",
    re.IGNORECASE,
)
_CALL_RE: Final = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_VAR_RE: Final = re.compile(
    r"\b(?:udg|bj|gg_trg|gg_unit|gg_item|gg_dest|gg_rct|gg_cam|gg_snd)_[A-Za-z0-9_]+\b",
)
_FOURCC_RE: Final = re.compile(r"[A-Za-z0-9]{4}")


@dataclass(frozen=True, slots=True)
class ScriptConditionBranch:
    source: str
    line: int
    function: str
    branch: str
    condition: str
    calls: tuple[str, ...]
    variables: tuple[str, ...]
    strings: tuple[str, ...]
    object_codes: tuple[str, ...]
    purpose: str
    summary: str


@dataclass(frozen=True, slots=True)
class ScriptConditionBranchIndex:
    branches: tuple[ScriptConditionBranch, ...]


def build_script_condition_branch_index(md: MapData) -> ScriptConditionBranchIndex:
    """Return if/elseif conditions with save, variable and object-ID clues."""
    functions = build_script_function_index(md).functions
    rows: list[ScriptConditionBranch] = []
    for source, text in analysis_script_texts(md):
        rows.extend(_branches_for_script(source, text, functions))
    return ScriptConditionBranchIndex(tuple(rows))


def format_script_condition_branch_index_tsv(index: ScriptConditionBranchIndex) -> str:
    """Format branch conditions as TSV."""
    rows = ["来源\t行号\t函数\t分支\t条件\t调用\t变量\t字符串\t对象码\t用途\t摘要"]
    for item in index.branches:
        rows.append("\t".join((
            _tsv(item.source),
            str(item.line),
            _tsv(item.function),
            _tsv(item.branch),
            _tsv(item.condition),
            _tsv("; ".join(item.calls)),
            _tsv("; ".join(item.variables)),
            _tsv("; ".join(item.strings)),
            _tsv("; ".join(item.object_codes)),
            _tsv(item.purpose),
            _tsv(item.summary),
        )))
    return "\n".join(rows) + "\n"


def _branches_for_script(
    source: str,
    text: str,
    functions: tuple[ScriptFunction, ...],
) -> list[ScriptConditionBranch]:
    rows: list[ScriptConditionBranch] = []
    code_lines = script_code_text(text).splitlines()
    raw_lines = text.splitlines()
    for line_no, code_line in enumerate(code_lines, start=1):
        match = _BRANCH_RE.match(code_line)
        if match is None:
            continue
        raw_line = _strip_comment(raw_lines[line_no - 1])
        start, end = match.span("condition")
        condition = raw_line[start:end].strip()
        code_condition = code_line[start:end]
        calls = _unique_ordered(item.group(1) for item in _CALL_RE.finditer(code_condition))
        variables = _unique_ordered(item.group(0) for item in _VAR_RE.finditer(code_condition))
        strings = _strings_in(condition)
        object_codes = tuple(sorted(set(_codes_in(code_condition))))
        rows.append(ScriptConditionBranch(
            source=source,
            line=line_no,
            function=_function_for(source, line_no, functions),
            branch=match.group("branch").lower(),
            condition=condition,
            calls=calls,
            variables=variables,
            strings=strings,
            object_codes=object_codes,
            purpose=_purpose(calls, variables, strings, object_codes),
            summary=raw_line.strip()[:160],
        ))
    return rows


def _purpose(
    calls: tuple[str, ...],
    variables: tuple[str, ...],
    strings: tuple[str, ...],
    object_codes: tuple[str, ...],
) -> str:
    if any(_is_save_call(call) for call in calls):
        return "存档条件"
    if object_codes:
        return "对象ID条件"
    if any(_looks_like_resource_path(value) for value in strings):
        return "资源条件"
    if variables:
        return "状态变量条件"
    if calls:
        return "调用条件"
    return "普通条件"


def _is_save_call(name: str) -> bool:
    return save_api_info(name) is not None or name == "StringHash"


def _looks_like_resource_path(value: str) -> bool:
    if "." not in value:
        return False
    return value.rsplit(".", 1)[-1].lower() in RESOURCE_EXTS


def _strings_in(text: str) -> tuple[str, ...]:
    values: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char not in {"'", '"'}:
            index += 1
            continue
        value, end = _read_quoted(text, index)
        if not (char == "'" and _FOURCC_RE.fullmatch(value)):
            values.append(unescape_arg(value))
        index = end
    return _unique_ordered(values)


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


def _unique_ordered(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)


def _tsv(value: str) -> str:
    return value.replace("\t", " ").replace("\r", " ").replace("\n", " ")
