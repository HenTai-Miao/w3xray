"""Per-call script argument index for static map investigation."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
import re
from typing import Final

from .api import MapData
from .resources import RESOURCE_EXTS
from .save_api_catalog import object_api_category, save_api_info
from .save_call_context import extract_call_args, unescape_arg
from .script_function_index import ScriptFunction, build_script_function_index
from .script_scan import _codes_in
from .script_tokens import script_code_text

_CALL_RE: Final = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
_FOURCC_RE: Final = re.compile(r"[A-Za-z0-9]{4}")
_FOURCC_PREFIX_RE: Final = re.compile(r"\bFourCC\s*\(\s*$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class ScriptCallArgument:
    source: str
    line: int
    function: str
    call: str
    position: int
    argument: str
    string_value: str
    object_codes: tuple[str, ...]
    mechanism: str
    purpose: str
    summary: str


@dataclass(frozen=True, slots=True)
class ScriptCallArgumentIndex:
    arguments: tuple[ScriptCallArgument, ...]


def build_script_call_argument_index(md: MapData) -> ScriptCallArgumentIndex:
    """Return each script call argument with save, resource and object-code clues."""
    functions = build_script_function_index(md).functions
    rows: list[ScriptCallArgument] = []
    for source, text in sorted(md.scripts.items()):
        if source.lower().endswith(".wts"):
            continue
        rows.extend(_arguments_for_script(source, text, functions))
    return ScriptCallArgumentIndex(tuple(rows))


def format_script_call_argument_index_tsv(index: ScriptCallArgumentIndex) -> str:
    """Format call arguments as TSV."""
    rows = ["来源\t行号\t函数\t调用\t参数序号\t参数\t字符串\t对象码\t机制\t用途\t摘要"]
    for item in index.arguments:
        rows.append("\t".join((
            _tsv(item.source),
            str(item.line),
            _tsv(item.function),
            _tsv(item.call),
            str(item.position),
            _tsv(item.argument),
            _tsv(item.string_value),
            _tsv("; ".join(item.object_codes)),
            _tsv(item.mechanism),
            _tsv(item.purpose),
            _tsv(item.summary),
        )))
    return "\n".join(rows) + "\n"


def _arguments_for_script(
    source: str,
    text: str,
    functions: tuple[ScriptFunction, ...],
) -> list[ScriptCallArgument]:
    rows: list[ScriptCallArgument] = []
    line_starts = _line_starts(text)
    code_text = script_code_text(text)
    for match in _CALL_RE.finditer(code_text):
        if _is_lua_function_definition(code_text, match.start()):
            continue
        raw_args = extract_call_args(text, match.end())
        code_args = extract_call_args(code_text, match.end())
        line_no = bisect_right(line_starts, match.start())
        call = match.group(1)
        mechanism = _mechanism(call)
        rows.extend(_argument_rows(
            source,
            line_no,
            _function_for(source, line_no, functions),
            call,
            mechanism,
            raw_args,
            code_args,
            _line_fragment(text, match.start())[:160],
        ))
    return rows


def _argument_rows(
    source: str,
    line_no: int,
    function: str,
    call: str,
    mechanism: str,
    raw_args: tuple[str, ...],
    code_args: tuple[str, ...],
    summary: str,
) -> list[ScriptCallArgument]:
    rows: list[ScriptCallArgument] = []
    for index, raw_arg in enumerate(raw_args, start=1):
        code_arg = code_args[index - 1] if index <= len(code_args) else raw_arg
        object_codes = tuple(sorted(set(_codes_in(code_arg))))
        string_value = _first_string(raw_arg)
        rows.append(ScriptCallArgument(
            source=source,
            line=line_no,
            function=function,
            call=call,
            position=index,
            argument=raw_arg,
            string_value=string_value,
            object_codes=object_codes,
            mechanism=mechanism,
            purpose=_purpose(call, mechanism, string_value, object_codes),
            summary=summary,
        ))
    return rows


def _mechanism(call: str) -> str:
    api = save_api_info(call)
    if api is not None:
        return f"{api.mechanism}:{api.operation}"
    category = object_api_category(call)
    if category is not None:
        return f"ObjectID:{category}"
    return "普通调用"


def _purpose(
    call: str,
    mechanism: str,
    string_value: str,
    object_codes: tuple[str, ...],
) -> str:
    if object_codes:
        return "对象码"
    if _looks_like_resource_path(string_value):
        return "资源路径"
    if _looks_like_save_key(call, mechanism, string_value):
        return "存档/键"
    if string_value:
        return "字符串"
    return "普通参数"


def _first_string(value: str) -> str:
    index = 0
    while index < len(value):
        if value[index] not in {"'", '"'}:
            index += 1
            continue
        quote = value[index]
        raw, end = _read_quoted(value, index)
        if not _is_object_code_quote(value, index, quote, raw):
            return unescape_arg(raw)
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


def _looks_like_resource_path(value: str) -> bool:
    if "." not in value:
        return False
    return value.rsplit(".", 1)[-1].lower() in RESOURCE_EXTS


def _looks_like_save_key(call: str, mechanism: str, value: str) -> bool:
    if mechanism.split(":", 1)[0] in {"GameCache", "Hashtable", "PlatformSave", "HashKey", "Sync"}:
        return bool(value)
    lowered = f"{call} {value}".lower()
    if any(word in lowered for word in ("save", "cache", "key", "load", "slot", "password")):
        return True
    return "." in value and not _looks_like_resource_path(value)


def _function_for(source: str, line: int, functions: tuple[ScriptFunction, ...]) -> str:
    for item in functions:
        if item.source == source and item.start_line <= line <= item.end_line:
            return item.name
    return ""


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


def _tsv(value: str) -> str:
    return value.replace("\t", " ").replace("\r", " ").replace("\n", " ")
