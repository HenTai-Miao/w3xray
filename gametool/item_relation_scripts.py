"""Extract bounded JASS/Lua item calls and conservative event context."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Final

from .item_relation_endpoints import resolve_relation_object
from .item_relation_models import (
    ItemRelation,
    ItemRelationKind,
    RelationCompleteness,
    RelationConfidence,
    RelationEvidence,
)
from .item_relation_wtg import build_wtg_item_relations
from .map_data import MapData
from .script_call_argument_index import (
    ScriptCallArgument,
    build_script_call_argument_index,
)
from .script_sources import analysis_script_sources
from .script_scopes import source_line_starts, script_structure
from .script_trigger_bindings import script_trigger_bindings
from .script_behavior_index import ScriptBehaviorCall, build_script_behavior_index
from .script_lexing import ScriptViews, script_views
from .script_object_literals import literal_object_code, strip_outer_parentheses
from bisect import bisect_right


@dataclass(frozen=True, slots=True)
class _CallSignature:
    item_position: int
    subject_position: int | None = None
    x_position: int | None = None
    y_position: int | None = None
    location_position: int | None = None
    slot_position: int | None = None


@dataclass(frozen=True, slots=True)
class _CallGroup:
    source: str
    line: int
    function: str
    call: str
    summary: str
    arguments: tuple[ScriptCallArgument, ...]
    offset: int | None = None
    primary: bool = True

    def at(self, position: int | None) -> ScriptCallArgument | None:
        if position is None:
            return None
        return next(
            (item for item in self.arguments if item.position == position), None
        )


_SIGNATURES: Final[Mapping[str, _CallSignature]] = MappingProxyType(
    {
        "CreateItem": _CallSignature(1, x_position=2, y_position=3),
        "CreateItemLoc": _CallSignature(1, location_position=2),
        "UnitAddItemById": _CallSignature(2, subject_position=1),
        "UnitAddItemByIdSwapped": _CallSignature(1, subject_position=2),
        "UnitAddItemToSlotById": _CallSignature(2, subject_position=1, slot_position=3),
        "AddItemToStock": _CallSignature(2, subject_position=1),
        "AddItemToAllStock": _CallSignature(1),
    }
)


def build_script_item_relations(md: MapData) -> tuple[ItemRelation, ...]:
    """Return fixed or explicitly clue-level script calls plus WTG item actions."""
    rows = list(build_script_call_item_relations(md))
    rows.extend(build_wtg_item_relations(md))
    return tuple(rows)


def build_script_call_item_relations(md: MapData) -> tuple[ItemRelation, ...]:
    """Return script-call evidence without coupling it to WTG parsing."""
    return _script_call_relations(md)


def _script_call_relations(md: MapData) -> tuple[ItemRelation, ...]:
    calls = _call_groups(build_script_call_argument_index(md).arguments)
    sources = analysis_script_sources(md)
    source_by_name = {source.source: source for source in sources}
    behavior = {
        (call.source, call.offset, call.callee): call
        for call in build_script_behavior_index(sources).calls
    }
    legacy_bindings: dict[
        tuple[str, int, str, bool, tuple[str, ...]], list[ScriptBehaviorCall]
    ] = {}
    if any(call.offset is None for call in calls):
        for binding in behavior.values():
            key = (
                binding.source,
                binding.line,
                binding.callee,
                binding.primary,
                binding.arguments,
            )
            legacy_bindings.setdefault(key, []).append(binding)
    death_contexts = _death_contexts(md)
    scopes = {
        source: script_trigger_bindings(text, lua=lua).structure.scopes
        for source, text, lua in sources
    }
    source_views = {
        source.source: script_views(source.text, lua=source.lua) for source in sources
    }
    rows: list[ItemRelation] = []
    for call in calls:
        if call.offset is None and tuple(
            argument.position for argument in call.arguments
        ) == tuple(range(1, len(call.arguments) + 1)):
            candidates = legacy_bindings.get(
                (
                    call.source,
                    call.line,
                    call.call,
                    call.primary,
                    tuple(argument.argument for argument in call.arguments),
                ),
                (),
            )
            if len(candidates) == 1:
                call = replace(call, offset=candidates[0].offset)
        binding = (
            behavior.get((call.source, call.offset, call.call))
            if call.offset is not None
            else None
        )
        signature = _SIGNATURES.get(
            binding.canonical
            if binding is not None and binding.canonical
            else call.call.removeprefix("_G.").removeprefix("_ENV.")
        )
        if signature is None or _is_nested_call(call):
            continue
        item_argument = call.at(signature.item_position)
        if item_argument is None:
            continue
        source = source_by_name[call.source]
        literal = literal_object_code(item_argument.argument)
        if source.lua is True and strip_outer_parentheses(
            item_argument.argument
        ).startswith("'"):
            literal = ""  # A Lua string is not an integer object identifier.
        codes = (literal,) if literal else item_argument.object_codes
        if len(codes) != 1:
            continue
        item_id = codes[0]
        binding_note = (
            ""
            if binding is not None and binding.binding == "standard-global"
            else "调用绑定未确认为标准物品函数"
            + (
                ": " + "; ".join(binding.diagnostics)
                if binding is not None and binding.diagnostics
                else "；同名源码函数或动态绑定仅保留为线索"
            )
        )
        direct = bool(literal) and not binding_note
        if direct:
            direct, literal_note = _literal_binding(
                call, item_argument, source_views[call.source], behavior
            )
            binding_note = literal_note
        confidence = RelationConfidence.CONFIRMED if direct else RelationConfidence.CLUE
        lookup = scopes.get(call.source)
        owner = (
            lookup.at(call.offset)
            if lookup is not None and call.offset is not None
            else None
        )
        contexts = death_contexts.get(
            (call.source, owner.start if owner is not None else None), ()
        )
        if contexts and confidence is RelationConfidence.CONFIRMED:
            confidence = RelationConfidence.INFERRED
        item, resolved = resolve_relation_object(md, item_id, "物品")
        completeness, reason = _script_completeness(item_id, resolved, bool(literal))
        if binding_note and completeness is RelationCompleteness.COMPLETE:
            completeness = RelationCompleteness.PARTIAL
        reason = "; ".join(filter(None, (reason, binding_note)))
        x = _float_argument(call.at(signature.x_position)) if not binding_note else None
        y = _float_argument(call.at(signature.y_position)) if not binding_note else None
        rows.append(
            ItemRelation(
                kind=ItemRelationKind.SCRIPT_REWARD,
                item=item,
                x=x,
                y=y,
                slot=_int_argument(call.at(signature.slot_position))
                if not binding_note
                else None,
                evidence=RelationEvidence(
                    source=call.source,
                    function=call.function,
                    line=call.line,
                    offset=call.offset or 0,
                    location=_call_location(call, signature),
                    raw=_raw_evidence(call.summary, contexts)
                    + ("\n绑定诊断: " + binding_note if binding_note else ""),
                ),
                confidence=confidence,
                completeness=completeness,
                unresolved_reason=reason,
                map_name=md.name,
            ),
        )
    return tuple(rows)


def _call_groups(arguments: tuple[ScriptCallArgument, ...]) -> tuple[_CallGroup, ...]:
    grouped: dict[
        tuple[str, int, str, str, str, int | None, bool], list[ScriptCallArgument]
    ] = {}
    for row in arguments:
        key = (
            row.source,
            row.line,
            row.function,
            row.call,
            row.summary,
            row.call_offset,
            row.primary,
        )
        grouped.setdefault(key, []).append(row)
    result: list[_CallGroup] = []
    for key, raw_rows in grouped.items():
        rows = raw_rows
        # 同一物理行可能出现多个同名调用（压缩/单行脚本）：position 是
        # 调用内参数序号、每个调用都从 1 严格递增，position 回落（<= 前值）
        # 即新调用边界。此前遇到重叠位置会整组静默丢弃，压缩脚图的
        # SCRIPT_REWARD 关系会整体消失。
        batch: list[ScriptCallArgument] = []
        prev = 0
        for row in rows:
            if batch and row.position <= prev:
                result.append(_CallGroup(*key[:5], tuple(batch), key[5], key[6]))
                batch = []
            batch.append(row)
            prev = row.position
        if batch:
            result.append(_CallGroup(*key[:5], tuple(batch), key[5], key[6]))
    return tuple(result)


def _death_contexts(md: MapData) -> Mapping[tuple[str, int | None], tuple[str, ...]]:
    contexts: dict[tuple[str, int | None], list[str]] = {}
    for source, text, lua in analysis_script_sources(md):
        bindings = script_trigger_bindings(text, lua=lua)
        lines = source_line_starts(text)
        for sites in bindings.instances.values():
            if any(site.diagnostic for site in sites):
                continue
            values = [
                f"{site.call.name} {event} @ 第 {bisect_right(lines, site.call.start)} 行"
                for site in sites
                for event in site.events
                if "DEATH" in event
            ]
            if not values:
                continue
            for site in sites:
                callback = site.callback
                if (
                    site.call.name.removeprefix("_G.")
                    not in {"TriggerAddAction", "TriggerAddActionBJ"}
                    or callback is None
                ):
                    continue
                # A candidate set is evidence of ambiguity, never a definite death link.
                if len(callback.functions) == 1 and not callback.diagnostic:
                    contexts.setdefault(
                        (source, callback.functions[0].start), []
                    ).extend(values)
    return MappingProxyType(
        {key: tuple(dict.fromkeys(values)) for key, values in contexts.items()}
    )


def _is_nested_call(call: _CallGroup) -> bool:
    if call.offset is not None:
        return not call.primary
    marker = re.search(rf"\b{re.escape(call.call)}\s*\(", call.summary)
    if marker is None:
        return False
    prefix = call.summary[: marker.start()]
    return prefix.count("(") > prefix.count(")")


def _literal_binding(
    call: _CallGroup,
    argument: ScriptCallArgument,
    views: ScriptViews,
    behavior: Mapping[tuple[str, int, str], ScriptBehaviorCall],
) -> tuple[bool, str]:
    """A FourCC spelling requires the same proved binding as the outer call."""
    nested = script_structure(argument.argument, lua=views.lua).calls
    if not nested:
        return True, ""
    if call.offset is None:
        return False, "对象码构造函数缺少源码偏移，绑定未确定"
    outer = behavior.get((call.source, call.offset, call.call))
    if outer is None:
        return False, "对象码构造函数缺少源码调用证据，绑定未确定"
    cursor = views.syntax.find("(", call.offset, outer.end_offset) + 1
    start = -1
    for item in call.arguments:
        start = views.arguments.find(item.argument, cursor, outer.end_offset)
        if start < 0:
            return False, "对象码实参未能绑定到原始源码偏移"
        if item is argument:
            break
        cursor = start + len(item.argument)
    notes: list[str] = []
    for inner in nested:
        resolved = behavior.get((call.source, start + inner.start, inner.name))
        if (
            resolved is None
            or resolved.binding != "standard-global"
            or resolved.canonical != "FourCC"
        ):
            notes.extend(resolved.diagnostics if resolved is not None else ())
            if not notes:
                notes.append("源码函数或动态绑定未确认为标准 FourCC")
    return not notes, "对象码构造函数绑定未确定: " + "; ".join(notes) if notes else ""


def _script_completeness(
    item_id: str,
    resolved: bool,
    direct: bool,
) -> tuple[RelationCompleteness, str]:
    if not resolved:
        return RelationCompleteness.UNRESOLVED, f"物品 {item_id} 未解析"
    if not direct:
        return RelationCompleteness.PARTIAL, "物品参数包含固定码，但表达式为动态"
    return RelationCompleteness.COMPLETE, ""


def _float_argument(argument: ScriptCallArgument | None) -> float | None:
    if argument is None:
        return None
    try:
        value = float(argument.argument.strip())
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def _int_argument(argument: ScriptCallArgument | None) -> int | None:
    if argument is None:
        return None
    try:
        return int(argument.argument.strip())
    except ValueError:
        return None


def _call_location(call: _CallGroup, signature: _CallSignature) -> str:
    parts: list[str] = []
    subject = call.at(signature.subject_position)
    location = call.at(signature.location_position)
    x_value = call.at(signature.x_position)
    y_value = call.at(signature.y_position)
    if subject is not None:
        parts.append(f"接收者/库存对象: {subject.argument}")
    if location is not None:
        parts.append(f"位置: {location.argument}")
    if x_value is not None and y_value is not None:
        parts.append(f"坐标: {x_value.argument}, {y_value.argument}")
    return "；".join(parts)


def _raw_evidence(summary: str, contexts: tuple[str, ...]) -> str:
    if not contexts:
        return summary
    return summary + "\n事件上下文: " + "；".join(contexts)
