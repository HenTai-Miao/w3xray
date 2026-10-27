"""Source-local JASS declaration-order evidence, without executing scripts."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace
import hashlib
import re
from typing import TYPE_CHECKING

from .batch_tsv import format_tsv_rows
from .jass_natives import NATIVE_OBJ_FUNCS
from .script_function_graph import FunctionContext, ScriptFunctions, script_functions
from .script_scopes import FunctionSpan
from .script_sources import analysis_script_sources

if TYPE_CHECKING:
    from .script_sources import ScriptSourceHost

_NATIVE = re.compile(r"\b(?:constant\s+)?native\s+([A-Za-z_]\w*)\s+takes\b")
_REFERENCE = re.compile(r"\bfunction\s+([A-Za-z_]\w*)\b(?!\s*takes\b)")
_ALIAS_REFERENCE = re.compile(r"\s*function\s+([A-Za-z_]\w*)[ \t]*(?=$|[\r\n;])")


@dataclass(frozen=True, slots=True)
class ForwardCallEvidence:
    source: str
    language: str
    line: int
    offset: int
    end_offset: int
    callee: str
    form: str
    owner: str
    binding: str
    state: str
    declarations: tuple[str, ...]
    diagnostic: str
    raw: str
    contexts: tuple[str, ...] = ()
    source_fingerprint: str = ""

    @property
    def location(self) -> str:
        return f"{self.source}:{self.line} / 偏移{self.offset}"


@dataclass(frozen=True, slots=True)
class ForwardCallReport:
    items: tuple[ForwardCallEvidence, ...]
    source_diagnostics: tuple[tuple[str, str, str], ...] = ()

    @property
    def forward_calls(self) -> tuple[ForwardCallEvidence, ...]:
        return tuple(item for item in self.items if item.state == "forward")


def build_forward_call_report(md: ScriptSourceHost) -> ForwardCallReport:
    """Check direct JASS calls and ``function Name`` references independently.

    Texts are separate translation units. A definition in another source never
    supplies an invented compilation order. Lua and unknown-language sources
    retain their coverage boundary and receive no JASS order verdict.
    """
    sources = analysis_script_sources(md)
    prepared = {
        source: script_functions(text, lua=lua)
        for source, text, lua in sources
        if lua is False
    }
    foreign: dict[str, list[str]] = {}
    for source, text, lua in sources:
        for function in script_functions(text, lua=lua).structure.functions:
            foreign.setdefault(function.name, []).append(
                f"{source}:{function.start_line} / 偏移{function.start}"
            )
    items: list[ForwardCallEvidence] = []
    boundaries: list[tuple[str, str, str]] = []
    for source, text, lua in sources:
        if lua is not False:
            boundaries.append(
                (
                    source,
                    "Lua" if lua else "unknown",
                    "Lua 不适用 JASS 声明顺序规则"
                    if lua
                    else "来源语言未确定，未应用 JASS 声明顺序规则",
                )
            )
            continue
        functions = prepared[source]
        contexts = functions.source_contexts()
        owner_contexts: dict[int | None, tuple[str, ...]] = {}
        fingerprint = (
            "analysis-text-sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
        )
        natives: dict[str, list[int]] = {}
        for match in _NATIVE.finditer(functions.views.syntax):
            natives.setdefault(match.group(1), []).append(match.start())
        declarations = {item.start for item in functions.structure.functions}
        events = [
            (call.start, call.end, call.name, "call", call.owner, call.complete)
            for call in functions.structure.calls
        ]
        for match in _REFERENCE.finditer(functions.views.syntax):
            if match.start() in declarations:
                continue
            owner = functions.structure.scopes.at(match.start())
            events.append(
                (
                    match.start(),
                    match.end(),
                    match.group(1),
                    "function-reference",
                    owner.start if owner else None,
                    True,
                )
            )
        for start, end, name, form, owner, complete in sorted(events):
            binding, state, targets, diagnostic = _binding(
                functions, source, name, start, owner, natives, foreign
            )
            if not complete:
                state = "unknown"
                diagnostic = "; ".join(
                    filter(None, (diagnostic, "调用参数范围未闭合，未确认声明顺序"))
                )
            function = (
                functions.symbols.functions.get(owner) if owner is not None else None
            )
            if function is not None and not function.complete:
                state = "unknown"
                diagnostic = "; ".join(
                    filter(None, (diagnostic, "所属函数范围未闭合，未确认声明顺序"))
                )
            if owner not in owner_contexts:
                owner_contexts[owner] = _contexts(contexts, owner)
            items.append(
                ForwardCallEvidence(
                    source,
                    "JASS",
                    bisect_right(functions.lines, start),
                    start,
                    end,
                    name,
                    form,
                    function.name if function else "<源码顶层>",
                    binding,
                    state,
                    targets,
                    diagnostic,
                    text[start:end],
                    owner_contexts[owner],
                    fingerprint,
                )
            )
    if analysis_script_sources(md) != sources:
        diagnostic = "加载的脚本来源/文本在诊断期间发生变化；保留原快照证据，未交付确认的声明顺序"
        items = [
            replace(
                item,
                state="unknown",
                diagnostic="; ".join(filter(None, (item.diagnostic, diagnostic))),
            )
            for item in items
        ]
        boundaries.append(("<loaded-script-snapshot>", "unknown", diagnostic))
    return ForwardCallReport(tuple(items), tuple(boundaries))


def _binding(
    functions: ScriptFunctions,
    source: str,
    name: str,
    start: int,
    owner: int | None,
    natives: Mapping[str, list[int]],
    foreign: Mapping[str, list[str]],
) -> tuple[str, str, tuple[str, ...], str]:
    symbol = functions.symbols.symbol(name, owner, start)
    native_offsets = natives.get(name, ())
    if functions.bound(name, owner, start):
        reference = functions.resolve(name, start, owner)
        targets = tuple(_declaration(source, item) for item in reference.functions)
        alias_targets: list[str] = []
        alias_writes: list[str] = []
        for assignment in functions.writes.get(symbol, ()):
            match = _ALIAS_REFERENCE.match(functions.views.syntax, assignment.rhs)
            if match is not None:
                target = functions.resolve(
                    match.group(1), match.start(1), assignment.owner
                )
                alias_targets.extend(
                    _declaration(source, item) for item in target.functions
                )
                alias_writes.append(
                    f"{source}:{bisect_right(functions.lines, assignment.rhs)} / "
                    f"偏移{assignment.rhs} / {name} = function {match.group(1)}"
                )
        if alias_writes:
            return (
                "alias",
                "unknown",
                tuple(dict.fromkeys((*targets, *alias_targets, *alias_writes))),
                "; ".join(
                    filter(
                        None,
                        (
                            reference.diagnostic,
                            "源码可见 function 引用赋值；保留全部别名候选，未作为全局直接调用确认",
                        ),
                    )
                ),
            )
        if reference.diagnostic:
            return "source-binding", "unknown", targets, reference.diagnostic
        if len(reference.functions) != 1 or native_offsets:
            return (
                "source-binding",
                "unknown",
                targets
                + tuple(
                    _native_declaration(source, functions, value)
                    for value in native_offsets
                ),
                "同名函数/native 或局部绑定未能唯一确定，未确认声明顺序",
            )
        target = reference.functions[0]
        if symbol in functions.writes or target.name != name:
            return (
                "alias",
                "unknown",
                targets,
                "源码可见函数别名，保留绑定目标；JASS 直接名称声明顺序不适用于别名调用",
            )
        if symbol[1] >= 0 or target.parent is not None or "." in name or ":" in name:
            return (
                "local-binding",
                "unknown",
                targets,
                "局部或扩展成员绑定，未作为 JASS 全局直接调用确认",
            )
        if target.start > start:
            return (
                "source-function",
                "forward",
                targets,
                "源码直接名称出现在同源函数声明之前；按 JASS 声明顺序存在前向引用风险",
            )
        return "source-function", "declared", targets, ""
    if native_offsets:
        targets = tuple(
            _native_declaration(source, functions, value) for value in native_offsets
        )
        if len(native_offsets) != 1:
            return "source-native", "unknown", targets, "同名 native 声明不唯一"
        # Common natives can already have been declared in the engine prelude.
        if name in NATIVE_OBJ_FUNCS or native_offsets[0] < start:
            return "source-native", "declared", targets, ""
        return (
            "source-native",
            "unknown",
            targets,
            "native 声明位于引用之后；未掌握外部前置声明，保留顺序不确定性",
        )
    other_sources = tuple(
        value for value in foreign.get(name, ()) if not value.startswith(source + ":")
    )
    if other_sources:
        return (
            "cross-source",
            "unknown",
            other_sources,
            "仅见其他来源的同名定义；来源合并/编译顺序未知，未确认前向调用",
        )
    if name in NATIVE_OBJ_FUNCS:
        return (
            "standard-dependency",
            "external",
            (),
            "标准 native/BJ 依赖；同源未见覆盖定义",
        )
    return (
        "external",
        "unknown",
        (),
        "同源未见定义；可能由 common.j/blizzard.j、外部脚本或运行时提供，未确认前向调用",
    )


def _declaration(source: str, function: FunctionSpan) -> str:
    return f"{source}:{function.start_line} / 偏移{function.start} / {function.name}"


def _native_declaration(source: str, functions: ScriptFunctions, start: int) -> str:
    return f"{source}:{bisect_right(functions.lines, start)} / 偏移{start} / native"


def _contexts(
    contexts: Mapping[int, tuple[FunctionContext, ...]], owner: int | None
) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            evidence
            for context in contexts.get(owner if owner is not None else -1, ())
            for evidence in (*context.evidence, *context.diagnostics)
        )
    )


def format_forward_call_report_tsv(report: ForwardCallReport) -> str:
    """Keep every call, unresolved binding and language boundary queryable."""
    return format_tsv_rows(_forward_call_rows(report))


def _forward_call_rows(report: ForwardCallReport) -> Iterator[tuple[str, ...]]:
    yield (
        "来源",
        "语言",
        "行",
        "偏移",
        "结束偏移",
        "调用名",
        "形式",
        "所属函数",
        "绑定",
        "状态",
        "声明证据",
        "诊断",
        "原始证据",
        "调用上下文",
        "来源指纹",
    )
    rendered_contexts: dict[int, str] = {}
    for item in report.items:
        # The immutable report keeps each tuple alive. Identity keys avoid
        # re-hashing/rejoining a potentially large tuple for every body call.
        context_identity = id(item.contexts)
        if context_identity not in rendered_contexts:
            rendered_contexts[context_identity] = "\n".join(item.contexts)
        yield (
            item.source,
            item.language,
            str(item.line),
            str(item.offset),
            str(item.end_offset),
            item.callee,
            item.form,
            item.owner,
            item.binding,
            item.state,
            "\n".join(item.declarations),
            item.diagnostic,
            item.raw,
            rendered_contexts[context_identity],
            item.source_fingerprint,
        )
    for source, language, diagnostic in report.source_diagnostics:
        yield (
            source,
            language,
            "",
            "",
            "",
            "",
            "source-coverage",
            "",
            "",
            "not-applied",
            "",
            diagnostic,
            "",
            "",
            "",
        )
