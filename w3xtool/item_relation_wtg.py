"""Conservatively extract fixed item actions from WTG ECA trees."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
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
from .map_data import MapData
from .wtg_models import TriggerEcaFunction, TriggerEcaParameter


@dataclass(frozen=True, slots=True)
class _WtgSignature:
    item_position: int


_WTG_SIGNATURES: Final[Mapping[str, _WtgSignature]] = MappingProxyType({
    "createitem": _WtgSignature(0),
    "createitemloc": _WtgSignature(0),
    "unitadditembyid": _WtgSignature(1),
    "unitadditembyidswapped": _WtgSignature(0),
    "unitadditemtoslotbyid": _WtgSignature(1),
    "additemtostock": _WtgSignature(1),
    "additemtoallstock": _WtgSignature(0),
})


def build_wtg_item_relations(md: MapData) -> tuple[ItemRelation, ...]:
    """Return enabled fixed-item WTG actions with trigger and binary evidence."""
    summary = md.trigger_summary
    if summary is None:
        return ()
    rows: list[ItemRelation] = []
    for node in _walk_functions(summary.eca_functions):
        signature = _WTG_SIGNATURES.get(node.name.casefold())
        if signature is None or not node.is_enabled or node.function_type != 2:
            continue
        if signature.item_position >= len(node.parameters):
            continue
        parameter = node.parameters[signature.item_position]
        item_id = _fixed_item_code(parameter)
        if item_id is None:
            continue
        item, resolved = resolve_relation_object(md, item_id, "物品")
        rows.append(
            ItemRelation(
                kind=ItemRelationKind.SCRIPT_REWARD,
                item=item,
                evidence=RelationEvidence(
                    source="war3map.wtg",
                    function=node.name,
                    trigger=node.trigger_name,
                    offset=node.source_offset,
                    location=_eca_location(node),
                    raw=f"{node.name}({', '.join(value.value for value in node.parameters)})",
                ),
                confidence=RelationConfidence.CONFIRMED,
                completeness=(
                    RelationCompleteness.COMPLETE
                    if resolved
                    else RelationCompleteness.UNRESOLVED
                ),
                unresolved_reason="" if resolved else f"物品 {item_id} 未解析",
                map_name=md.name,
            ),
        )
    return tuple(rows)


def _walk_functions(nodes: Iterable[TriggerEcaFunction]) -> Iterator[TriggerEcaFunction]:
    for node in nodes:
        yield node
        for parameter in node.parameters:
            yield from _parameter_functions(parameter)
        yield from _walk_functions(node.children)


def _parameter_functions(parameter: TriggerEcaParameter) -> Iterator[TriggerEcaFunction]:
    if parameter.nested_function is not None:
        yield from _walk_functions((parameter.nested_function,))
    if parameter.array_indexer is not None:
        yield from _parameter_functions(parameter.array_indexer)


def _fixed_item_code(parameter: TriggerEcaParameter) -> str | None:
    if parameter.parameter_type != 0 or parameter.expected_type.casefold() != "itemcode":
        return None
    if parameter.nested_function is not None or parameter.array_indexer is not None:
        return None
    value = parameter.value.strip().strip("\x00")
    if len(value) != 4 or not value.isascii() or not value.isalnum():
        return None
    return value


def _eca_location(node: TriggerEcaFunction) -> str:
    branch = f" 分支{node.branch}" if node.branch else ""
    return f"ECA {node.ordinal}{branch} @ 0x{node.source_offset:X}"
