"""Trigger/event registration index for static script investigation."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
import re
from typing import Final

from .api import MapData
from .save_call_context import extract_call_args, unescape_arg
from .script_function_index import ScriptFunction, build_script_function_index
from .script_sources import analysis_script_texts
from .script_tokens import script_code_text

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


@dataclass(frozen=True, slots=True)
class ScriptTriggerRegistrationIndex:
    registrations: tuple[ScriptTriggerRegistration, ...]


def build_script_trigger_registration_index(md: MapData) -> ScriptTriggerRegistrationIndex:
    """Return trigger, action, condition and timer registrations from script code."""
    functions = build_script_function_index(md).functions
    rows: list[ScriptTriggerRegistration] = []
    for source, text in analysis_script_texts(md):
        rows.extend(_registrations_for_script(source, text, functions))
    return ScriptTriggerRegistrationIndex(tuple(rows))


def format_script_trigger_registration_index_tsv(
    index: ScriptTriggerRegistrationIndex,
) -> str:
    """Format trigger registration rows as TSV."""
    rows = ["来源\t行号\t函数\t注册类型\t句柄\tAPI\t目标\t字符串参数\t摘要"]
    for item in index.registrations:
        rows.append("\t".join((
            _tsv(item.source),
            str(item.line),
            _tsv(item.function),
            _tsv(item.registration_type),
            _tsv(item.handle),
            _tsv(item.api),
            _tsv(item.target),
            _tsv("; ".join(item.string_args)),
            _tsv(item.summary),
        )))
    return "\n".join(rows) + "\n"


def _registrations_for_script(
    source: str,
    text: str,
    functions: tuple[ScriptFunction, ...],
) -> list[ScriptTriggerRegistration]:
    rows: list[ScriptTriggerRegistration] = []
    line_starts = _line_starts(text)
    code_text = script_code_text(text)
    raw_lines = text.splitlines()
    for match in _CALL_RE.finditer(code_text):
        api = match.group(1)
        registration_type = _registration_type(api)
        if not registration_type:
            continue
        args = extract_call_args(text, match.end())
        line = bisect_right(line_starts, match.start())
        rows.append(ScriptTriggerRegistration(
            source=source,
            line=line,
            function=_function_for(source, line, functions),
            registration_type=registration_type,
            handle=_handle(args),
            api=api,
            target=_target(api, registration_type, args),
            string_args=_string_args(args),
            summary=_summary(raw_lines, line),
        ))
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
    value = arg.strip()
    if len(value) < 2 or value[0] != value[-1] or value[0] not in {"'", '"'}:
        return ""
    return unescape_arg(value[1:-1])


def _clean_arg(arg: str) -> str:
    value = arg.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return unescape_arg(value[1:-1])
    return value


def _function_for(source: str, line: int, functions: tuple[ScriptFunction, ...]) -> str:
    for item in functions:
        if item.source == source and item.start_line <= line <= item.end_line:
            return item.name
    return ""


def _summary(lines: list[str], line_no: int) -> str:
    if line_no > len(lines):
        return ""
    return _strip_comment(lines[line_no - 1]).strip()[:160]


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


def _line_starts(text: str) -> list[int]:
    starts = [0]
    starts.extend(match.end() for match in re.finditer("\n", text))
    return starts


def _tsv(value: str) -> str:
    return value.replace("\t", " ").replace("\r", " ").replace("\n", " ")
