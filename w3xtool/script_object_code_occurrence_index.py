"""Per-occurrence script object-code index for static map investigation."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import re
from typing import Final

from .api import GameObject, MapData
from .base_names import BASE_NAMES
from .object_id_usage import code_decimal
from .script_call_catalog import ScriptCall, build_script_call_catalog
from .script_function_index import ScriptFunction, build_script_function_index
from .script_scan import _codes_in, scan_object_refs
from .script_sources import analysis_script_texts
from .script_tokens import script_code_text

_JASS_SET_RE: Final = re.compile(
    r"^\s*set\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?:\[[^\]]+\])?\s*=",
)
_LUA_ASSIGN_RE: Final = re.compile(
    r"^\s*(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?:\[[^\]]+\])?\s*=",
)
_GLOBAL_DECL_RE: Final = re.compile(
    r"^\s*(?:(?:private|public)\s+)?(?:constant\s+)?"
    r"[A-Za-z_][A-Za-z0-9_]*\s+(?:array\s+)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?:\s*=.*)?$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ScriptObjectCodeOccurrence:
    source: str
    line: int
    function: str
    code: str
    decimal: int
    category: str
    name: str
    object_source: str
    context: str
    mechanism: str
    summary: str


@dataclass(frozen=True, slots=True)
class ScriptObjectCodeOccurrenceIndex:
    occurrences: tuple[ScriptObjectCodeOccurrence, ...]


def build_script_object_code_occurrence_index(md: MapData) -> ScriptObjectCodeOccurrenceIndex:
    """Return executable script object-code occurrences with readable context."""
    functions = build_script_function_index(md).functions
    calls = build_script_call_catalog(md).calls
    objects = _object_lookup(md)
    rows: list[ScriptObjectCodeOccurrence] = []
    for source, text in analysis_script_texts(md):
        rows.extend(_occurrences_for_script(source, text, functions, calls, objects))
    return ScriptObjectCodeOccurrenceIndex(tuple(rows))


def format_script_object_code_occurrence_index_tsv(
    index: ScriptObjectCodeOccurrenceIndex,
) -> str:
    """Format script object-code occurrences as TSV."""
    rows = ["来源\t行号\t函数\t对象码\t10进制\t分类\t名称\t对象来源\t上下文\t机制\t摘要"]
    for item in index.occurrences:
        rows.append("\t".join((
            _tsv(item.source),
            str(item.line),
            _tsv(item.function),
            _tsv(item.code),
            str(item.decimal),
            _tsv(item.category),
            _tsv(item.name),
            _tsv(item.object_source),
            _tsv(item.context),
            _tsv(item.mechanism),
            _tsv(item.summary),
        )))
    return "\n".join(rows) + "\n"


def _occurrences_for_script(
    source: str,
    text: str,
    functions: tuple[ScriptFunction, ...],
    calls: tuple[ScriptCall, ...],
    objects: dict[str, GameObject],
) -> list[ScriptObjectCodeOccurrence]:
    code_lines = script_code_text(text).splitlines()
    raw_lines = text.splitlines()
    calls_by_line = _calls_by_line(source, calls)
    categories = _script_categories(text)
    is_lua = source.lower().endswith(".lua")
    rows: list[ScriptObjectCodeOccurrence] = []
    for line_no, code_line in enumerate(code_lines, start=1):
        for code in _codes_in(code_line):
            context, mechanism = _context_for(code_line, code, is_lua, calls_by_line.get(line_no, ()))
            obj = objects.get(code)
            rows.append(ScriptObjectCodeOccurrence(
                source=source,
                line=line_no,
                function=_function_for(source, line_no, functions),
                code=code,
                decimal=code_decimal(code),
                category=_category(code, obj, mechanism, categories),
                name=_name(code, obj),
                object_source=_object_source(obj),
                context=context,
                mechanism=mechanism,
                summary=_summary(raw_lines, line_no),
            ))
    return rows


def _object_lookup(md: MapData) -> dict[str, GameObject]:
    lookup = {obj.obj_id: obj for objects in md.objects.values() for obj in objects}
    for code, obj in md.obj_index.items():
        if isinstance(code, str) and isinstance(obj, GameObject):
            lookup.setdefault(code, obj)
    return lookup


def _calls_by_line(source: str, calls: tuple[ScriptCall, ...]) -> dict[int, tuple[ScriptCall, ...]]:
    grouped: dict[int, list[ScriptCall]] = {}
    for call in calls:
        if call.source != source:
            continue
        grouped.setdefault(call.line, []).append(call)
    return {line: tuple(items) for line, items in grouped.items()}


def _script_categories(text: str) -> dict[str, str]:
    by_code: dict[str, set[str]] = {}
    for category, codes in scan_object_refs(text).items():
        for code in codes:
            by_code.setdefault(code, set()).add(category)
    return {code: _category_label(categories) for code, categories in by_code.items()}


def _context_for(
    line: str,
    code: str,
    is_lua: bool,
    calls: tuple[ScriptCall, ...],
) -> tuple[str, str]:
    assignment = _assignment_target(line, is_lua)
    if assignment:
        return assignment, "赋值"
    global_name = _global_name(line)
    if global_name:
        return global_name, "全局声明"
    call = _call_for_code(code, calls, prefer_non_fourcc=True)
    if call is not None:
        return call.function, call.mechanism
    call = _call_for_code(code, calls, prefer_non_fourcc=False)
    if call is not None:
        return call.function, call.mechanism
    return "字面量", "对象码"


def _assignment_target(line: str, is_lua: bool) -> str:
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


def _global_name(line: str) -> str:
    match = _GLOBAL_DECL_RE.match(line)
    return match.group("name") if match is not None else ""


def _call_for_code(
    code: str,
    calls: tuple[ScriptCall, ...],
    *,
    prefer_non_fourcc: bool,
) -> ScriptCall | None:
    for call in calls:
        if code not in call.object_codes:
            continue
        if prefer_non_fourcc and call.function == "FourCC":
            continue
        return call
    return None


def _category(
    code: str,
    obj: GameObject | None,
    mechanism: str,
    categories: dict[str, str],
) -> str:
    if obj is not None:
        return obj.category
    if mechanism.startswith("ObjectID:"):
        return mechanism.split(":", 1)[1]
    return categories.get(code, "未知")


def _category_label(categories: Iterable[str]) -> str:
    values = tuple(sorted(categories))
    if len(values) == 1:
        return values[0]
    if values:
        return "/".join(values)
    return "未知"


def _name(code: str, obj: GameObject | None) -> str:
    if obj is not None:
        return obj.name
    return BASE_NAMES.get(code) or ""


def _object_source(obj: GameObject | None) -> str:
    if obj is not None:
        return obj.ext
    return "未解析"


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


def _tsv(value: str) -> str:
    return value.replace("\t", " ").replace("\r", " ").replace("\n", " ")
