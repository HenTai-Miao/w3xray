"""Trigger/event registration index for static script investigation."""

from __future__ import annotations

from .script_sources import analysis_script_sources, script_language

import re
from bisect import bisect_right
from dataclasses import dataclass
from typing import Final

from .map_data import MapData
from .presentation_safety import tsv_cell as _tsv
from .save_call_context import extract_call_args
from .script_function_index import (
    ScriptFunctionLookup,
    build_function_lookup,
    build_script_function_index,
)
from .script_scopes import source_line_starts
from .script_lexing import literal_string_value, script_views
from .script_trigger_bindings import script_trigger_bindings

_CALL_RE: Final = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_EVENT_RE: Final = re.compile(r"\b[A-Z][A-Z0-9_]*EVENT[A-Z0-9_]*\b")
_FUNCTION_REF_RE: Final = re.compile(r"\bfunction\s+([A-Za-z_][A-Za-z0-9_.:]*)\b")


@dataclass(frozen=True, slots=True)
class ScriptTriggerRegistration:
    source: str
    line: int
    function: str
    registration_type: str
    handle: str
    api: str
    target: str
    string_args: tuple[str, ...]
    summary: str
    offset: int = 0
    scope_offset: int | None = None
    binding_offset: int = -1
    callback_offsets: tuple[int, ...] = ()
    callback_diagnostic: str = ""
    callback_expression: str = ""
    binding_diagnostic: str = ""


@dataclass(frozen=True, slots=True)
class ScriptTriggerRegistrationIndex:
    registrations: tuple[ScriptTriggerRegistration, ...]


def build_script_trigger_registration_index(
    md: MapData,
) -> ScriptTriggerRegistrationIndex:
    """Return trigger, action, condition and timer registrations from script code."""
    functions = build_function_lookup(build_script_function_index(md).functions)
    rows: list[ScriptTriggerRegistration] = []
    for source, text, lua in analysis_script_sources(md):
        rows.extend(_registrations_for_script(source, text, functions, lua=lua))
    return ScriptTriggerRegistrationIndex(tuple(rows))


def format_script_trigger_registration_index_tsv(
    index: ScriptTriggerRegistrationIndex,
) -> str:
    """Format trigger registration rows as TSV."""
    rows = [
        "来源\t行号\t函数\t注册类型\t句柄\tAPI\t目标\t字符串参数\t摘要\t源码偏移\t函数偏移\t触发器赋值偏移\t回调偏移\t回调诊断\t回调表达式\t关联诊断"
    ]
    for item in index.registrations:
        rows.append(
            "\t".join(
                (
                    _tsv(item.source),
                    str(item.line),
                    _tsv(item.function),
                    _tsv(item.registration_type),
                    _tsv(item.handle),
                    _tsv(item.api),
                    _tsv(item.target),
                    _tsv("; ".join(item.string_args)),
                    _tsv(item.summary),
                    str(item.offset),
                    "" if item.scope_offset is None else str(item.scope_offset),
                    str(item.binding_offset),
                    ";".join(str(offset) for offset in item.callback_offsets),
                    _tsv(item.callback_diagnostic),
                    _tsv(item.callback_expression),
                    _tsv(item.binding_diagnostic),
                )
            )
        )
    return "\n".join(rows) + "\n"


def _registrations_for_script(
    source: str, text: str, functions: ScriptFunctionLookup, *, lua: bool | None = None
) -> list[ScriptTriggerRegistration]:
    lua = script_language(source) if lua is None else lua
    rows: list[ScriptTriggerRegistration] = []
    line_starts = source_line_starts(text)
    views = script_views(text, lua=lua)
    bindings = script_trigger_bindings(text, lua=lua)
    for site in bindings.structure.calls:
        api = site.name.removeprefix("_G.")
        registration_type = _registration_type(api)
        if not registration_type:
            continue
        args = extract_call_args(views, site.open + 1)
        line = bisect_right(line_starts, site.start)
        binding = bindings.by_start[site.start]
        callback = binding.callback
        target = _target(api, registration_type, args)
        if callback is not None:
            target = (
                "; ".join(item.name for item in callback.functions)
                or target
                or callback.expression
            )
        rows.append(
            ScriptTriggerRegistration(
                source=source,
                line=line,
                function=functions.name_for(source, line, offset=site.start),
                registration_type=registration_type,
                handle=_handle(args),
                api=site.name,
                target=target,
                string_args=_string_args(args),
                summary=text[site.start : site.end],
                offset=site.start,
                scope_offset=site.owner,
                binding_offset=binding.instance[2],
                callback_offsets=tuple(item.start for item in callback.functions)
                if callback is not None
                else (),
                callback_diagnostic=callback.diagnostic if callback is not None else "",
                callback_expression=callback.expression if callback is not None else "",
                binding_diagnostic=binding.diagnostic,
            )
        )
    return rows


def _registration_type(api: str) -> str:
    if api in {"TriggerAddAction", "TriggerAddActionBJ"}:
        return "动作"
    if api in {"TriggerAddCondition", "TriggerAddConditionBJ"}:
        return "条件"
    if api == "TimerStart":
        return "计时器"
    if api.startswith("TriggerRegister") and "ChatEvent" in api:
        return "聊天事件"
    if api.startswith("TriggerRegister"):
        return "事件"
    return ""


def _handle(args: tuple[str, ...]) -> str:
    return _clean_arg(args[0]) if args else ""


def _target(api: str, registration_type: str, args: tuple[str, ...]) -> str:
    if registration_type in {"动作", "条件", "计时器"}:
        return _function_ref(args)
    if registration_type == "聊天事件":
        return _chat_command(api, args)
    event = _event_constant(args)
    if event:
        return event
    return _clean_arg(args[-1]) if args else ""


def _function_ref(args: tuple[str, ...]) -> str:
    for arg in reversed(args):
        match = _FUNCTION_REF_RE.search(arg)
        if match is not None:
            return match.group(1)
    return ""


def _chat_command(api: str, args: tuple[str, ...]) -> str:
    index = 1 if api.endswith("BJ") else 2
    if index >= len(args):
        return ""
    return _clean_arg(args[index])


def _event_constant(args: tuple[str, ...]) -> str:
    for arg in reversed(args):
        match = _EVENT_RE.search(arg)
        if match is not None:
            return match.group(0)
    return ""


def _string_args(args: tuple[str, ...]) -> tuple[str, ...]:
    values: list[str] = []
    for arg in args:
        value = _quoted_value(arg)
        if value:
            values.append(value)
    return tuple(values)


def _quoted_value(arg: str) -> str:
    return literal_string_value(arg) or ""


def _clean_arg(arg: str) -> str:
    literal = literal_string_value(arg)
    return arg.strip() if literal is None else literal


def _summary(lines: list[str], line_no: int) -> str:
    if line_no > len(lines):
        return ""
    return lines[line_no - 1].strip()


def _line_starts(text: str) -> list[int]:
    starts = [0]
    starts.extend(match.end() for match in re.finditer("\n", text))
    return starts
