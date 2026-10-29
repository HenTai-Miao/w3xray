"""Source-bound local-state diagnostics; map script text is never executed."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, replace
import hashlib
import re
from typing import TYPE_CHECKING

from .jass_natives import NATIVE_OBJ_FUNCS
from .script_control_ranges import ControlPredicate, ControlRange
from .script_function_bindings import ScriptFunctionBindings
from .script_lexing import script_views
from .script_names import IDENTIFIER, qualified_name
from .script_scopes import CallSpan
from .script_sources import (
    AnalysisScriptSource,
    analysis_script_sources,
    analysis_script_text,
)

if TYPE_CHECKING:
    from .api import MapData

_IDENTIFIER = re.compile(r"\b" + IDENTIFIER + r"\b")
_MUTATION = re.compile(
    r"(?:CreateUnit|CreateItem|CreateDestructable|KillUnit|RemoveUnit|RemoveItem|"
    r"RemoveDestructable|SetUnit\w*|SetHero\w*|SetWidgetLife|SetPlayerState|"
    r"SetPlayerTechResearched|SetResourceAmount|SetItem\w*|SetDestructable\w*|"
    r"UnitAddAbility|UnitRemoveAbility)"
)
# Exact established names supplement the shared object-native catalogue. Prefix
# matches outside this set remain candidates, never proved native identities.
_KNOWN = frozenset(
    {
        "GetLocalPlayer",
        "GetCameraTargetPositionX",
        "GetCameraTargetPositionY",
        "GetCameraTargetPositionZ",
        "GetCameraTargetPositionLoc",
        "GetCameraEyePositionX",
        "GetCameraEyePositionY",
        "GetCameraEyePositionZ",
        "GetCameraEyePositionLoc",
        "GetCameraField",
        "GetCameraMargin",
        "GetCameraBoundMinX",
        "GetCameraBoundMinY",
        "GetCameraBoundMaxX",
        "GetCameraBoundMaxY",
        "KillUnit",
        "RemoveUnit",
        "RemoveItem",
        "RemoveDestructable",
        "SetWidgetLife",
        "SetPlayerState",
        "SetResourceAmount",
        "SetUnitState",
        "SetUnitX",
        "SetUnitY",
        "SetUnitPosition",
        "SetUnitPositionLoc",
        "SetUnitOwner",
        "SetUnitFacing",
        "SetUnitFacingTimed",
        "SetUnitMoveSpeed",
        "SetUnitFlyHeight",
        "SetUnitTurnSpeed",
        "SetUnitPropWindow",
        "SetUnitAcquireRange",
        "SetUnitScale",
        "SetUnitTimeScale",
        "SetUnitBlendTime",
        "SetUnitAnimation",
        "SetUnitAnimationByIndex",
        "SetUnitAnimationWithRarity",
        "SetUnitLookAt",
        "SetUnitVertexColor",
        "SetUnitInvulnerable",
        "SetUnitPathing",
        "SetHeroStr",
        "SetHeroAgi",
        "SetHeroInt",
        "SetHeroXP",
        "SetHeroLevel",
        "SetItemPosition",
        "SetItemCharges",
        "SetItemPlayer",
        "SetItemInvulnerable",
        "SetItemVisible",
        "SetItemDropOnDeath",
        "SetItemDroppable",
        "SetItemPawnable",
        "SetItemUserData",
        "SetDestructableLife",
        "SetDestructableMaxLife",
        "SetDestructableInvulnerable",
        "SetDestructableAnimation",
        "SetDestructableAnimationSpeed",
        "SetDestructableOccluderHeight",
        *NATIVE_OBJ_FUNCS,
    }
)


def _families(name: str) -> tuple[str, ...]:
    result: list[str] = []
    if name == "GetLocalPlayer":
        result.append("script.get_local_player")
    if re.fullmatch(r"GetCamera[A-Za-z0-9_]*", name):
        result.append("script.local_state.camera")
    if re.fullmatch(r"(?:DzGetMouse|DzTriggerRegisterMouse)[A-Za-z0-9_]*", name):
        result.append("script.local_state.mouse")
    if re.fullmatch(r"Dz[A-Za-z0-9_]*", name):
        result.append("script.dz_api")
    return tuple(result)


def _risk_name(name: str) -> bool:
    return bool(_families(name) or _MUTATION.fullmatch(name))


def _standard_spelling(name: str) -> str:
    if name.startswith(("_G.", "_ENV.")):
        name = name.split(".", 1)[1]
    return name if _IDENTIFIER.fullmatch(name) else ""


@dataclass(frozen=True, slots=True)
class DiagnosticPredicateEvidence:
    line: int
    offset: int
    end_offset: int
    raw: str
    negated: bool
    role: str
    call_offsets: tuple[int, ...]
    calls: tuple[str, ...]
    bindings: tuple[str, ...]
    diagnostics: tuple[str, ...]
    complete: bool


@dataclass(frozen=True, slots=True)
class DiagnosticCallEvidence:
    source: str
    language: str
    line: int
    offset: int
    end_offset: int
    callee: str
    canonical: str
    owner: str
    owner_offset: int | None
    binding: str
    diagnostic: str
    raw: str
    source_fingerprint: str
    predicates: tuple[DiagnosticPredicateEvidence, ...] = ()
    language_candidates: tuple[str, ...] = ()

    @property
    def location(self) -> str:
        return f"{self.source}:{self.line} / 偏移 {self.offset}:{self.end_offset}"

    @property
    def detail(self) -> str:
        text = (
            f"{self.location} · {self.language} · 所属函数 {self.owner} · "
            f"调用 {self.callee} → {self.canonical or '未确定'} · 绑定 {self.binding} · "
            f"{self.diagnostic} · 原文 {self.raw}"
        )
        if self.language_candidates:
            text += " · 候选词法 " + "/".join(self.language_candidates)
        for predicate in self.predicates:
            text += (
                f"\n    条件 {self.source}:{predicate.line} / 偏移 "
                f"{predicate.offset}:{predicate.end_offset} · "
                f"{'循环退出条件（可能影响后续迭代）' if predicate.role == 'loop-exit' else '此前分支不成立' if predicate.negated else '当前条件'} · "
                f"范围{'完整' if predicate.complete else '未闭合'} · "
                f"本地调用 {', '.join(f'{name}@{offset}' for name, offset in zip(predicate.calls, predicate.call_offsets))} · "
                f"绑定 {'; '.join(predicate.bindings)} · {'; '.join(predicate.diagnostics)} · "
                f"原文 {predicate.raw}"
            )
        return text


@dataclass(frozen=True, slots=True)
class LocalStateAnalysis:
    groups: dict[str, tuple[DiagnosticCallEvidence, ...]]


def _alias_candidates(bindings: ScriptFunctionBindings, names: set[str]) -> set[str]:
    """Keep uncertain aliases visible without treating their spelling as a native."""
    result = set(names)
    dependents: dict[str, set[str]] = {}
    for rows in bindings.writes.values():
        for assignment in rows:
            value = qualified_name(
                script_views(bindings.atoms.value(assignment), lua=bindings.lua).syntax
            )
            if value is not None:
                dependents.setdefault(value, set()).add(assignment.key)
                canonical = _standard_spelling(value)
                if canonical:
                    dependents.setdefault(canonical, set()).add(assignment.key)
    pending = list(result)
    while pending:
        for alias in dependents.get(pending.pop(), ()):
            if alias not in result:
                result.add(alias)
                pending.append(alias)
    return result


def _call_evidence(
    source: AnalysisScriptSource,
    bindings: ScriptFunctionBindings,
    call: CallSpan,
    fingerprint: str,
    candidates: set[str],
    foreign: dict[str, tuple[str, ...]],
) -> DiagnosticCallEvidence | None:
    nominal = _standard_spelling(call.name)
    reference = bindings.resolve(call.name, call.start, call.owner)
    canonical = reference.builtin
    if not _risk_name(canonical) and not (
        _risk_name(nominal) or call.name in candidates
    ):
        return None
    # A proved script function replaces the name; its body is analyzed separately.
    if reference.functions and not reference.diagnostic:
        return None
    note = reference.diagnostic
    binding = "standard-global" if canonical in _KNOWN else "candidate-global"
    if not canonical:
        binding = "unknown"
    elif source.lua is False and any(separator in call.name for separator in ".:"):
        binding, note = "unknown", "JASS 限定名称未按标准原生调用形式解释"
    elif ":" in call.name:
        binding, note = "unknown", "冒号调用包含隐式接收者，未按标准原生签名解释"
    elif canonical in foreign or call.name.startswith("_G.") and "_G" in foreign:
        binding, note = (
            "unknown",
            "其他脚本含同名绑定，加载顺序未确定："
            + "; ".join(foreign.get(canonical, ()) + foreign.get("_G", ())),
        )
    elif canonical not in _KNOWN:
        note = "仅名称符合风险 API 家族；未确认其原生声明、实现或运行效果"
    else:
        note = "默认全局 API 绑定；静态调用证据不证明执行路径或联机效果"
    function = (
        bindings.symbols.functions.get(call.owner) if call.owner is not None else None
    )
    if not call.complete or function is not None and not function.complete:
        binding = "unknown"
        note += "；调用或所属函数范围未闭合"
    if source.lua is None:
        binding = "unknown"
        note += "；来源语言未确定，未据此推断控制流"
    return DiagnosticCallEvidence(
        source.source,
        "Lua" if source.lua is True else "JASS" if source.lua is False else "unknown",
        bisect_right(bindings.lines, call.start),
        call.start,
        call.end,
        call.name,
        canonical or nominal,
        function.name if function else "<全局>",
        call.owner,
        binding,
        note,
        source.text[call.start : call.end],
        fingerprint,
    )


def _predicate_evidence(
    source: AnalysisScriptSource,
    bindings: ScriptFunctionBindings,
    predicate: ControlPredicate,
    local_calls: tuple[DiagnosticCallEvidence, ...],
    offsets: tuple[int, ...],
    complete: bool,
) -> DiagnosticPredicateEvidence | None:
    first = bisect_left(offsets, predicate.start)
    last = bisect_left(offsets, predicate.end)
    selected = local_calls[first:last]
    if not selected:
        return None
    return DiagnosticPredicateEvidence(
        bisect_right(bindings.lines, predicate.start),
        predicate.start,
        predicate.end,
        source.text[predicate.start : predicate.end],
        predicate.negated,
        predicate.role,
        tuple(item.offset for item in selected),
        tuple(item.callee for item in selected),
        tuple(item.binding for item in selected),
        tuple(item.diagnostic for item in selected),
        complete,
    )


def _local_mutations(
    source: AnalysisScriptSource,
    bindings: ScriptFunctionBindings,
    calls: list[DiagnosticCallEvidence],
) -> tuple[DiagnosticCallEvidence, ...]:
    if source.lua is None:
        return ()
    by_owner: dict[int | None, list[DiagnosticCallEvidence]] = {}
    for item in calls:
        by_owner.setdefault(item.owner_offset, []).append(item)
    result: list[DiagnosticCallEvidence] = []
    for owner, owned in by_owner.items():
        local = tuple(item for item in owned if item.canonical == "GetLocalPlayer")
        if not local:
            continue
        offsets = tuple(item.offset for item in local)
        controls: list[
            tuple[ControlRange, tuple[DiagnosticPredicateEvidence, ...]]
        ] = []
        for control in bindings.symbols.control_data(owner)[0]:
            condition_evidence = tuple(
                evidence
                for predicate in control.predicates
                if (
                    evidence := _predicate_evidence(
                        source, bindings, predicate, local, offsets, control.complete
                    )
                )
                is not None
            )
            if condition_evidence:
                controls.append((control, condition_evidence))
        # Evidence is proportional to actual enclosing local conditions; no fixed
        # line/count/depth budget is used and callbacks have their own owner.
        for item in owned:
            if not _MUTATION.fullmatch(item.canonical):
                continue
            predicates: dict[tuple[int, int, bool], DiagnosticPredicateEvidence] = {}
            for control, evidence in controls:
                if control.start <= item.offset < control.end:
                    for predicate in evidence:
                        predicates.setdefault(
                            (predicate.offset, predicate.end_offset, predicate.negated),
                            predicate,
                        )
            if predicates:
                if item.binding != "standard-global" or any(
                    not p.complete
                    or any(binding != "standard-global" for binding in p.bindings)
                    for p in predicates.values()
                ):
                    item = replace(
                        item,
                        binding="unknown",
                        diagnostic=item.diagnostic
                        + "；本地条件下修改调用的绑定或范围未确定",
                    )
                result.append(replace(item, predicates=tuple(predicates.values())))
    return tuple(result)


def _global_binding_evidence(
    source: AnalysisScriptSource,
    bindings: ScriptFunctionBindings,
    unknown_language: bool,
    result: dict[str, dict[str, set[str]]],
) -> None:
    for symbol in bindings.definitions.keys() | bindings.writes.keys():
        if not (
            symbol[0] is None
            and symbol[1] < 0
            and (_risk_name(symbol[2]) or symbol[2] == "_G")
        ):
            continue
        spans = [
            (item.start, item.end, "函数声明")
            for item in bindings.definitions.get(symbol, ())
        ]
        for assignment in bindings.writes.get(symbol, ()):
            atom = bindings.atoms.assignment(assignment)
            spans.append(
                (
                    assignment.start,
                    atom.end if atom else assignment.rhs,
                    "赋值" if atom else "赋值目标（右值未静态拆解）",
                )
            )
        language = "Lua" if source.lua is True else "JASS"
        status = (
            f"语言未知；{language} 词法下的潜在覆盖"
            if unknown_language
            else f"{language} 来源绑定"
        )
        target = result.setdefault(symbol[2], {}).setdefault(source.source, set())
        for start, end, kind in spans:
            target.add(
                f"{source.source}:{bisect_right(bindings.lines, start)} / 偏移 {start}:{end} · "
                f"{status} · {kind} · 原文 {source.text[start:end]}"
            )


def _unknown_language_evidence(
    candidates: dict[DiagnosticCallEvidence, list[DiagnosticCallEvidence]],
    item: DiagnosticCallEvidence,
) -> None:
    predicates = tuple(
        replace(
            predicate,
            bindings=tuple("unknown" for _ in predicate.bindings),
            diagnostics=tuple(
                f"候选绑定 {binding}；来源语言未确定；{diagnostic}"
                for binding, diagnostic in zip(
                    predicate.bindings, predicate.diagnostics
                )
            ),
        )
        for predicate in item.predicates
    )
    key = replace(
        item,
        language="unknown",
        binding="unknown",
        diagnostic="",
        predicates=predicates,
    )
    candidates.setdefault(key, []).append(item)


def build_local_state_analysis(md: MapData) -> LocalStateAnalysis:
    prepared: list[
        tuple[AnalysisScriptSource, ScriptFunctionBindings, set[str], bool]
    ] = []
    global_bindings: dict[str, dict[str, set[str]]] = {}
    for original in analysis_script_sources(md):
        unknown_language = original.lua is None
        # Neither the mixed comment view nor auto-selected function syntax is
        # evidence that an unknown source has a particular language.
        for lua in (False, True) if unknown_language else (original.lua,):
            source = AnalysisScriptSource(
                original.source,
                analysis_script_text(original.source, original.text, lua),
                lua,
            )
            names = {
                match.group()
                for match in _IDENTIFIER.finditer(
                    script_views(source.text, lua=lua).syntax
                )
                if _risk_name(match.group())
            }
            bindings = ScriptFunctionBindings(
                source.text, lua=lua, additional_builtins=names
            )
            prepared.append(
                (source, bindings, _alias_candidates(bindings, names), unknown_language)
            )
            _global_binding_evidence(
                source, bindings, unknown_language, global_bindings
            )
    grouped: dict[str, list[DiagnosticCallEvidence]] = {}
    unknown: dict[DiagnosticCallEvidence, list[DiagnosticCallEvidence]] = {}
    for source, bindings, candidates, unknown_language in prepared:
        foreign = {}
        for name, paths in global_bindings.items():
            evidence = tuple(
                sorted(
                    label
                    for path, labels in paths.items()
                    if path != source.source
                    for label in labels
                )
            )
            if evidence:
                foreign[name] = evidence
        fingerprint = hashlib.sha256(
            md.scripts[source.source].encode("utf-8", errors="surrogatepass")
        ).hexdigest()
        calls: list[DiagnosticCallEvidence] = []
        for call in bindings.structure.calls:
            item = _call_evidence(
                source, bindings, call, fingerprint, candidates, foreign
            )
            if item is None:
                continue
            calls.append(item)
            families = _families(item.canonical)
            if unknown_language:
                if families or item.binding in {"unknown", "candidate-global"}:
                    _unknown_language_evidence(unknown, item)
                continue
            for code in families:
                grouped.setdefault(code, []).append(item)
            if (
                item.binding == "unknown"
                or item.binding == "candidate-global"
                and not families
            ):
                grouped.setdefault("script.binding.unknown", []).append(item)
        for item in _local_mutations(source, bindings, calls):
            if unknown_language:
                _unknown_language_evidence(unknown, item)
                continue
            code = (
                "script.get_local_player.sync_mutation"
                if item.binding == "standard-global"
                else "script.local_mutation.unknown"
            )
            grouped.setdefault(code, []).append(item)
    for key, alternatives in unknown.items():
        grouped.setdefault("script.language.unknown", []).append(
            replace(
                key,
                diagnostic="来源语言未确定；以下仅是风险候选，未确认原生身份、控制流或运行效果：\n"
                + "\n".join(
                    f"{item.language} 词法候选 · 候选绑定 {item.binding} · {item.diagnostic}"
                    for item in alternatives
                ),
                language_candidates=tuple(
                    dict.fromkeys(item.language for item in alternatives)
                ),
            )
        )
    return LocalStateAnalysis({code: tuple(rows) for code, rows in grouped.items()})
