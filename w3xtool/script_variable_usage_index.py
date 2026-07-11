"""Global variable usage index for static script investigation."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from .api import MapData
from .presentation_safety import tsv_cell as _tsv
from .script_function_index import ScriptFunction, build_script_function_index
from .script_scan import _codes_in
from .script_sources import analysis_script_texts
from .script_tokens import script_code_text

_VAR_RE: Final = re.compile(
    r"\b(?:udg|bj|gg_trg|gg_unit|gg_item|gg_dest|gg_rct|gg_cam|gg_snd)_[A-Za-z0-9_]+\b",
)
_CALL_RE: Final = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_JASS_SET_RE: Final = re.compile(
    r"^\s*set\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?:\[[^\]]+\])?\s*=",
)
_LUA_ASSIGN_RE: Final = re.compile(
    r"^\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?:\[[^\]]+\])?\s*=",
)


@dataclass(frozen=True, slots=True)
class ScriptVariableUsage:
    source: str
    line: int
    function: str
    variable: str
    access: str
    category: str
    call: str
    object_codes: tuple[str, ...]
    summary: str


@dataclass(frozen=True, slots=True)
class ScriptVariableUsageIndex:
    usages: tuple[ScriptVariableUsage, ...]


def build_script_variable_usage_index(md: MapData) -> ScriptVariableUsageIndex:
    """Return udg_/gg_/bj_ variable reads and writes with script context."""
    functions = build_script_function_index(md).functions
    rows: list[ScriptVariableUsage] = []
    for source, text in analysis_script_texts(md):
        rows.extend(_usages_for_script(source, text, functions))
    return ScriptVariableUsageIndex(tuple(rows))


def format_script_variable_usage_index_tsv(index: ScriptVariableUsageIndex) -> str:
    """Format script variable usage rows as TSV."""
    rows = ["来源\t行号\t函数\t变量\t访问\t类别\t调用\t对象码\t摘要"]
    for item in index.usages:
        rows.append("\t".join((
            _tsv(item.source),
            str(item.line),
            _tsv(item.function),
            _tsv(item.variable),
            _tsv(item.access),
            _tsv(item.category),
            _tsv(item.call),
            _tsv("; ".join(item.object_codes)),
            _tsv(item.summary),
        )))
    return "\n".join(rows) + "\n"


def _usages_for_script(
    source: str,
    text: str,
    functions: tuple[ScriptFunction, ...],
) -> list[ScriptVariableUsage]:
    rows: list[ScriptVariableUsage] = []
    code_lines = script_code_text(text).splitlines()
    raw_lines = text.splitlines()
    is_lua = source.lower().endswith(".lua")
    for line_no, code_line in enumerate(code_lines, start=1):
        variables = _unique_ordered(match.group(0) for match in _VAR_RE.finditer(code_line))
        if not variables:
            continue
        write_target = _write_target(code_line, is_lua)
        object_codes = tuple(sorted(set(_codes_in(code_line))))
        call = _line_call(code_line)
        summary = _strip_comment(raw_lines[line_no - 1]).strip()[:160]
        for variable in variables:
            rows.append(ScriptVariableUsage(
                source=source,
                line=line_no,
                function=_function_for(source, line_no, functions),
                variable=variable,
                access=_access(variable, write_target, code_line),
                category=_category(variable),
                call=call if variable != write_target else "",
                object_codes=object_codes,
                summary=summary,
            ))
    return rows


def _write_target(line: str, is_lua: bool) -> str:
    match = _JASS_SET_RE.match(line)
    if match is not None:
        return match.group("name")
    if not is_lua:
        return ""
    stripped = line.lstrip().lower()
    if stripped.startswith(("local ", "function ", "if ", "for ", "while ", "return ")):
        return ""
    match = _LUA_ASSIGN_RE.match(line)
    return match.group("name") if match is not None else ""


def _access(variable: str, write_target: str, line: str) -> str:
    if variable != write_target:
        return "读取"
    eq_index = line.find("=")
    if eq_index >= 0 and re.search(rf"\b{re.escape(variable)}\b", line[eq_index + 1:]):
        return "读写"
    return "写入"


def _category(variable: str) -> str:
    if variable.startswith("udg_"):
        return "用户全局"
    if variable.startswith("gg_trg_"):
        return "触发器变量"
    if variable.startswith("gg_unit_"):
        return "预放置单位"
    if variable.startswith("gg_item_"):
        return "预放置物品"
    if variable.startswith("gg_dest_"):
        return "预放置装饰物"
    if variable.startswith("gg_rct_"):
        return "区域变量"
    if variable.startswith("gg_cam_"):
        return "镜头变量"
    if variable.startswith("gg_snd_"):
        return "声音变量"
    if variable.startswith("bj_"):
        return "BJ变量"
    return "脚本变量"


def _line_call(line: str) -> str:
    match = _CALL_RE.search(line)
    return match.group(1) if match is not None else ""


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
