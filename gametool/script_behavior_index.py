"""Complete source call evidence with lexical bindings, never script execution.

Offsets refer to Unicode characters in the supplied source text. Fingerprints
hash its UTF-8 ``surrogatepass`` encoding; pack readers separately prove original
file bytes. Control ranges describe lexical context, not runtime reachability.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterable
from dataclasses import dataclass, replace
import hashlib
import heapq
import re

from .script_behavior_catalog import STANDARD_CALL_CATEGORIES
from .script_behavior_syntax import script_call_syntax_diagnostics
from .script_assignments import reference_parts
from .script_control_ranges import ControlRange
from .script_function_bindings import ScriptFunctionBindings
from .script_scopes import CallSpan
from .script_sources import AnalysisScriptSource, analysis_script_text


@dataclass(frozen=True, slots=True)
class ScriptBehaviorPredicate:
    line: int
    offset: int
    end_offset: int
    raw: str
    negated: bool
    role: str


@dataclass(frozen=True, slots=True)
class ScriptBehaviorControl:
    kind: str
    offset: int
    end_offset: int
    condition: str
    selector: str
    predicates: tuple[ScriptBehaviorPredicate, ...]
    complete: bool


@dataclass(frozen=True, slots=True)
class ScriptBehaviorTarget:
    name: str
    line: int
    offset: int
    end_offset: int
    complete: bool


@dataclass(frozen=True, slots=True)
class ScriptBehaviorCall:
    source: str
    language: str
    line: int
    offset: int
    end_offset: int
    owner: str
    owner_offset: int | None
    callee: str
    canonical: str
    binding: str
    arguments: tuple[str, ...]
    raw: str
    primary: bool
    complete: bool
    controls: tuple[ScriptBehaviorControl, ...]
    targets: tuple[ScriptBehaviorTarget, ...]
    diagnostics: tuple[str, ...]
    source_fingerprint: str
    category: str
    language_candidates: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ScriptBehaviorDiagnostic:
    source: str
    language: str
    code: str
    message: str
    line: int
    offset: int
    end_offset: int
    raw: str
    source_fingerprint: str


@dataclass(frozen=True, slots=True)
class ScriptBehaviorIndex:
    calls: tuple[ScriptBehaviorCall, ...]
    diagnostics: tuple[ScriptBehaviorDiagnostic, ...]


@dataclass(frozen=True, slots=True)
class _Prepared:
    original: AnalysisScriptSource
    source: AnalysisScriptSource
    bindings: ScriptFunctionBindings
    fingerprint: str
    ordinal: int


def _language(lua: bool | None) -> str:
    return "Lua" if lua is True else "JASS" if lua is False else "unknown"


def _diagnostic(
    prepared: _Prepared,
    code: str,
    message: str,
    offset: int,
    end_offset: int,
) -> ScriptBehaviorDiagnostic:
    return ScriptBehaviorDiagnostic(
        prepared.original.source,
        _language(prepared.original.lua),
        code,
        message,
        bisect_right(prepared.bindings.lines, offset),
        offset,
        end_offset,
        prepared.original.text[offset:end_offset],
        prepared.fingerprint,
    )


def _control(prepared: _Prepared, control: ControlRange) -> ScriptBehaviorControl:
    return ScriptBehaviorControl(
        control.kind,
        control.start,
        control.end,
        control.condition,
        control.selector,
        tuple(
            ScriptBehaviorPredicate(
                bisect_right(prepared.bindings.lines, predicate.start),
                predicate.start,
                predicate.end,
                prepared.original.text[predicate.start : predicate.end],
                predicate.negated,
                predicate.role,
            )
            for predicate in control.predicates
        ),
        control.complete,
    )


def _controls_by_call(
    prepared: _Prepared, calls: tuple[CallSpan, ...]
) -> dict[int, tuple[ScriptBehaviorControl, ...]]:
    """Sweep each owner once; work follows actual enclosing context evidence."""
    grouped: dict[int | None, list[CallSpan]] = {}
    for call in calls:
        grouped.setdefault(call.owner, []).append(call)
    result: dict[int, tuple[ScriptBehaviorControl, ...]] = {}
    for owner, owned in grouped.items():
        ranges = prepared.bindings.symbols.control_data(owner)[0]
        active: dict[int, ScriptBehaviorControl] = {}
        ending: list[tuple[int, int]] = []
        cursor = 0
        for call in sorted(owned, key=lambda item: item.start):
            while cursor < len(ranges) and ranges[cursor].start <= call.start:
                current = ranges[cursor]
                if current.end > call.start:
                    active[cursor] = _control(prepared, current)
                    heapq.heappush(ending, (current.end, cursor))
                cursor += 1
            while ending and ending[0][0] <= call.start:
                _end, index = heapq.heappop(ending)
                active.pop(index, None)
            result[call.start] = tuple(active.values())
    return result


def _raw_arguments(prepared: _Prepared, call: CallSpan) -> tuple[tuple[str, ...], bool]:
    """Split complete expressions while preserving comments and literal bytes.

    The shared structure masks child function bodies, so callback commas never
    become outer arguments. Source text is retained; nothing is evaluated.
    """
    bindings = prepared.bindings
    start = call.open + 1
    end = call.end - int(call.complete)
    syntax = bindings.structure.own_text(bindings.views.syntax, start, end, call.owner)
    arguments: list[str] = []
    chunk = start
    stack: list[str] = []
    valid = True
    for match in re.finditer(r"[()\[\]{},]", syntax):
        position, token = start + match.start(), match.group()
        if token in "([{":
            stack.append({"(": ")", "[": "]", "{": "}"}[token])
        elif token in ")]}":
            if not stack or stack.pop() != token:
                valid = False
        elif not stack:
            if not bindings.views.arguments[chunk:position].strip():
                valid = False
            arguments.append(prepared.original.text[chunk:position].strip())
            chunk = position + 1
    if bindings.views.arguments[chunk:end].strip() or arguments:
        if not bindings.views.arguments[chunk:end].strip():
            valid = False
        arguments.append(prepared.original.text[chunk:end].strip())
    return tuple(arguments), valid and not stack


def _global_bindings(
    prepared: tuple[_Prepared, ...],
) -> dict[str, tuple[tuple[int, str], ...]]:
    result: dict[str, dict[tuple[int, str], None]] = {}
    for item in prepared:
        bindings = item.bindings
        for symbol in bindings.definitions.keys() | bindings.writes.keys():
            if symbol[0] is not None or symbol[1] >= 0:
                continue
            spans = [
                (function.start, function.end, "函数声明")
                for function in bindings.definitions.get(symbol, ())
            ]
            for assignment in bindings.writes.get(symbol, ()):
                atom = bindings.atoms.assignment(assignment)
                spans.append(
                    (
                        assignment.start,
                        atom.end if atom else assignment.rhs,
                        "赋值" if atom else "赋值目标",
                    )
                )
            target = result.setdefault(symbol[2], {})
            for start, end, kind in spans:
                label = (
                    f"{item.original.source}:{bisect_right(bindings.lines, start)}"
                    f" / 偏移 {start}:{end} · {_language(item.source.lua)} {kind} · "
                    + item.original.text[start:end]
                )
                target[item.ordinal, label] = None
    return {name: tuple(values) for name, values in result.items()}


def _call_evidence(
    prepared: _Prepared,
    call: CallSpan,
    controls: tuple[ScriptBehaviorControl, ...],
    foreign: dict[str, tuple[tuple[int, str], ...]],
) -> ScriptBehaviorCall:
    bindings = prepared.bindings
    reference = bindings.resolve(call.name, call.start, call.owner)
    function = (
        bindings.symbols.functions.get(call.owner) if call.owner is not None else None
    )
    arguments, arguments_complete = _raw_arguments(prepared, call)
    complete = call.complete and arguments_complete
    notes: list[str] = [reference.diagnostic] if reference.diagnostic else []
    canonical = reference.builtin
    binding = (
        "standard-global"
        if canonical and not reference.diagnostic
        else "source-function"
        if len(reference.functions) == 1 and not reference.diagnostic
        else "unknown"
    )
    symbol = bindings.symbols.symbol(call.name, call.owner, call.start)
    relevant = {canonical} if canonical else set()
    for prefix in reference_parts(call.name, lua=prepared.source.lua)[0][:-1]:
        prefix_symbol = bindings.symbols.symbol(prefix, call.owner, call.start)
        if prefix_symbol[0] is None and prefix_symbol[1] < 0:
            relevant.add(prefix_symbol[2])
    for target in reference.functions:
        target_symbol = bindings.symbols.symbol(
            target.name, target.parent, target.start
        )
        if target_symbol[0] is None and target_symbol[1] < 0:
            relevant.add(target_symbol[2])
        for prefix in reference_parts(target.name, lua=prepared.source.lua)[0][:-1]:
            prefix_symbol = bindings.symbols.symbol(prefix, target.parent, target.start)
            if prefix_symbol[0] is None and prefix_symbol[1] < 0:
                relevant.add(prefix_symbol[2])
    if symbol[0] is None and symbol[1] < 0:
        relevant.add(symbol[2])
    if call.name.startswith("_G."):
        relevant.add("_G")
    if call.name.startswith("_ENV."):
        relevant.add("_ENV")
    cross_source = tuple(
        dict.fromkeys(
            label
            for name in sorted(relevant)
            for ordinal, label in foreign.get(name, ())
            if ordinal != prepared.ordinal
        )
    )
    if cross_source:
        binding = "unknown"
        notes.append(
            "其他脚本存在同名全局绑定；加载顺序未确定：\n" + "\n".join(cross_source)
        )
    if prepared.source.lua is False and any(c in call.name for c in ".:"):
        binding = "unknown"
        notes.append("JASS 限定名称不是已确认的标准调用形式")
    elif prepared.source.lua is False and canonical in {
        "FourCC",
        "select",
        "table.unpack",
    }:
        binding = "unknown"
        notes.append("Lua 标准名称不是已确认的 JASS 标准函数")
    elif ":" in call.name and canonical:
        binding = "unknown"
        notes.append("冒号调用包含隐式接收者，未按标准函数签名解释")
    if not complete:
        binding = "unknown"
        notes.append("调用或参数定界未闭合；保留完整可读原文")
    if function is not None and not function.complete:
        binding = "unknown"
        notes.append("所属函数范围未闭合；未确定完整绑定范围")
    if any(not control.complete for control in controls):
        notes.append("词法控制上下文未闭合；不据此推断执行路径")
    if prepared.original.lua is None:
        binding = "unknown"
        notes.append(
            f"来源语言未知；{_language(prepared.source.lua)} 词法候选，"
            "未确认标准函数身份、目标定义或控制流"
        )
        controls = ()
    if binding != "standard-global":
        canonical = ""
    targets = tuple(
        ScriptBehaviorTarget(
            target.name,
            target.start_line,
            target.start,
            target.end,
            target.complete,
        )
        for target in reference.functions
    )
    if prepared.original.lua is None:
        targets = ()
    return ScriptBehaviorCall(
        prepared.original.source,
        _language(prepared.original.lua),
        bisect_right(bindings.lines, call.start),
        call.start,
        call.end,
        function.name if function else "<全局>",
        call.owner,
        call.name,
        canonical,
        binding,
        arguments,
        prepared.original.text[call.start : call.end],
        call.primary,
        complete,
        controls,
        targets,
        tuple(dict.fromkeys(notes)),
        prepared.fingerprint,
        STANDARD_CALL_CATEGORIES.get(canonical, "标准调用") if canonical else "",
        (_language(prepared.source.lua),) if prepared.original.lua is None else (),
    )


def _unknown_key(item: ScriptBehaviorCall) -> ScriptBehaviorCall:
    return replace(item, diagnostics=(), language_candidates=())


def _primary_calls(calls: list[ScriptBehaviorCall]) -> list[ScriptBehaviorCall]:
    """A dynamic receiver chain may share a start while enclosing earlier calls."""
    ancestors: list[ScriptBehaviorCall] = []
    result: list[ScriptBehaviorCall] = []
    for item in sorted(calls, key=lambda call: (call.offset, -call.end_offset)):
        while ancestors and ancestors[-1].end_offset <= item.offset:
            ancestors.pop()
        parent = ancestors[-1] if ancestors else None
        result.append(
            replace(
                item,
                primary=parent is None or parent.owner_offset != item.owner_offset,
            )
        )
        ancestors.append(item)
    return sorted(result, key=lambda call: (call.offset, call.end_offset))


def build_script_behavior_index(
    sources: Iterable[AnalysisScriptSource],
) -> ScriptBehaviorIndex:
    """Index every supplied source without execution, count, or depth ceilings.

    Repeated source names remain separate evidence. Unknown source languages
    retain both lexer candidates, never a guessed native identity. The category
    vocabulary is an exact reference catalogue, not an effect/reachability claim.
    """
    work: list[_Prepared] = []
    for ordinal, original in enumerate(sources):
        fingerprint = hashlib.sha256(
            original.text.encode("utf-8", errors="surrogatepass")
        ).hexdigest()
        for lua in (False, True) if original.lua is None else (original.lua,):
            source = AnalysisScriptSource(
                original.source,
                analysis_script_text(original.source, original.text, lua),
                lua,
            )
            work.append(
                _Prepared(
                    original,
                    source,
                    ScriptFunctionBindings(
                        source.text,
                        lua=lua,
                        additional_builtins=(
                            name
                            for name in STANDARD_CALL_CATEGORIES
                            if lua is True or name not in {"select", "table.unpack"}
                        ),
                    ),
                    fingerprint,
                    ordinal,
                )
            )
    prepared_sources = tuple(work)
    foreign = _global_bindings(prepared_sources)
    calls: list[tuple[int, ScriptBehaviorCall]] = []
    diagnostics: dict[ScriptBehaviorDiagnostic, None] = {}
    unknown: dict[tuple[int, ScriptBehaviorCall], list[ScriptBehaviorCall]] = {}
    for prepared in prepared_sources:
        bindings = prepared.bindings
        spans = bindings.structure.calls
        syntax = script_call_syntax_diagnostics(
            prepared.source.text,
            lua=prepared.source.lua is True,
            known_calls=spans,
        )
        dynamic_spans: dict[tuple[int, int, str], CallSpan] = {}
        for item in syntax:
            if not item.callee:
                continue
            owner = bindings.structure.scopes.at(item.offset)
            dynamic_spans[item.offset, item.end_offset, item.callee] = CallSpan(
                item.callee,
                item.offset,
                item.offset,
                item.end_offset,
                owner.start if owner else None,
                None,
                True,
                item.complete,
            )
        controls = _controls_by_call(prepared, (*spans, *dynamic_spans.values()))
        source_calls = [
            _call_evidence(prepared, call, controls[call.start], foreign)
            for call in spans
        ]
        for item in syntax:
            if item.callee:
                owner = bindings.structure.scopes.at(item.offset)
                source_calls.append(
                    ScriptBehaviorCall(
                        prepared.original.source,
                        _language(prepared.original.lua),
                        bisect_right(bindings.lines, item.offset),
                        item.offset,
                        item.end_offset,
                        owner.name if owner else "<全局>",
                        owner.start if owner else None,
                        item.callee,
                        "",
                        "unknown",
                        item.arguments,
                        prepared.original.text[item.offset : item.end_offset],
                        True,
                        item.complete,
                        controls[item.offset]
                        if prepared.original.lua is not None
                        else (),
                        (),
                        (item.message,),
                        prepared.fingerprint,
                        "",
                        (_language(prepared.source.lua),)
                        if prepared.original.lua is None
                        else (),
                    )
                )
            else:
                diagnostics[
                    _diagnostic(
                        prepared,
                        item.code,
                        item.message,
                        item.offset,
                        item.end_offset,
                    )
                ] = None
        for function in bindings.structure.functions:
            if not function.complete:
                diagnostics[
                    _diagnostic(
                        prepared,
                        "script.function.incomplete",
                        "函数范围未闭合；保留完整原文，不宣称完整执行结构",
                        function.start,
                        function.end,
                    )
                ] = None
        for owner in (None, *bindings.symbols.functions):
            for control in bindings.symbols.control_data(owner)[0]:
                if not control.complete:
                    start = min(
                        (predicate.start for predicate in control.predicates),
                        default=control.start,
                    )
                    diagnostics[
                        _diagnostic(
                            prepared,
                            "script.control.incomplete",
                            "词法控制范围或条件未闭合；保留已读取的全部条件和原文",
                            start,
                            control.end,
                        )
                    ] = None
        if prepared.original.lua is None:
            diagnostics[
                _diagnostic(
                    prepared,
                    "script.language.unknown",
                    "来源语言未知；同时保留 JASS/Lua 词法候选，不据此证明原生绑定或控制流",
                    0,
                    len(prepared.original.text),
                )
            ] = None
        for item in _primary_calls(source_calls):
            if prepared.original.lua is None:
                unknown.setdefault((prepared.ordinal, _unknown_key(item)), []).append(
                    item
                )
            else:
                calls.append((prepared.ordinal, item))
            for note in item.diagnostics:
                diagnostics[
                    _diagnostic(
                        prepared,
                        "script.call.binding"
                        if item.binding == "unknown"
                        else "script.call.context",
                        note,
                        item.offset,
                        item.end_offset,
                    )
                ] = None
    for (ordinal, key), candidates in unknown.items():
        calls.append(
            (
                ordinal,
                replace(
                    key,
                    diagnostics=tuple(
                        dict.fromkeys(
                            note for item in candidates for note in item.diagnostics
                        )
                    ),
                    language_candidates=tuple(
                        dict.fromkeys(
                            language
                            for item in candidates
                            for language in item.language_candidates
                        )
                    ),
                ),
            )
        )
    return ScriptBehaviorIndex(
        tuple(
            item
            for _ordinal, item in sorted(
                calls, key=lambda row: (row[0], row[1].offset, row[1].end_offset)
            )
        ),
        tuple(diagnostics),
    )
