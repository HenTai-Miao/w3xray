"""Immutable item acquisition, equipment-skill, and evidence indexes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Literal, assert_never

type JsonValue = str | int | float | bool | None | tuple[JsonValue, ...]


class ItemRelationKind(StrEnum):
    """Supported static acquisition and equipment relation roles."""

    UNIT_DROP = "怪物直接掉落"
    DESTRUCTABLE_DROP = "可破坏物掉落"
    SHOP_SELL = "商店出售"
    SHOP_MAKE = "商店制造"
    RECIPE = "合成"
    GROUND_PLACEMENT = "地面预放置"
    PREPLACED_INVENTORY = "预放置背包"
    SCRIPT_REWARD = "脚本/触发奖励"
    ITEM_ABILITY = "装备技能"
    COOLDOWN_ABILITY = "共享冷却技能"


class RelationConfidence(StrEnum):
    """How directly the retained evidence proves a relation."""

    CONFIRMED = "已确认"
    INFERRED = "可推断"
    CLUE = "仅线索"


class RelationCompleteness(StrEnum):
    """Whether all endpoints and required context were resolved."""

    COMPLETE = "完整"
    PARTIAL = "部分"
    UNRESOLVED = "未解析"
    CONFLICT = "冲突"


@dataclass(frozen=True, slots=True)
class RelationObject:
    """One source, item, or skill endpoint."""

    category: str
    object_id: str
    name: str


@dataclass(frozen=True, slots=True)
class RelationIngredient:
    """One counted material required by a recipe."""

    item: RelationObject
    count: int


@dataclass(frozen=True, slots=True)
class RelationEvidence:
    """Static file, field, function, trigger, line, or offset evidence."""

    source: str = ""
    field_key: str = ""
    function: str = ""
    trigger: str = ""
    line: int = 0
    offset: int = 0
    location: str = ""
    raw: str = ""


@dataclass(frozen=True, slots=True)
class ItemRelation:
    """One evidence-bearing item acquisition or equipment-skill relation."""

    kind: ItemRelationKind
    item: RelationObject
    evidence: RelationEvidence
    confidence: RelationConfidence
    completeness: RelationCompleteness
    source: RelationObject | None = None
    skill: RelationObject | None = None
    map_name: str = ""
    instance_serial: int | None = None
    player: int | None = None
    x: float | None = None
    y: float | None = None
    z: float | None = None
    group_index: int | None = None
    entry_index: int | None = None
    chance: int | None = None
    slot: int | None = None
    ingredients: tuple[RelationIngredient, ...] = ()
    unresolved_reason: str = ""
    relation_id: str = field(init=False)

    def __post_init__(self) -> None:
        payload = json.dumps(
            _identity_payload(self),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        object.__setattr__(self, "relation_id", hashlib.sha256(payload).hexdigest())


@dataclass(frozen=True, slots=True)
class ItemRelationIndex:
    """Stable relations with immutable target, source, skill, and kind lookups."""

    records: tuple[ItemRelation, ...]
    by_item: Mapping[str, tuple[ItemRelation, ...]]
    by_source: Mapping[str, tuple[ItemRelation, ...]]
    by_skill: Mapping[str, tuple[ItemRelation, ...]]
    by_kind: Mapping[ItemRelationKind, tuple[ItemRelation, ...]]

    @classmethod
    def build(cls, records: Iterable[ItemRelation]) -> ItemRelationIndex:
        """Deduplicate exact evidence identities and build reverse indexes."""
        unique: dict[str, ItemRelation] = {}
        for record in records:
            unique.setdefault(record.relation_id, record)
        ordered = tuple(sorted(unique.values(), key=item_relation_sort_key))
        return cls(
            records=ordered,
            by_item=_group_by_text(ordered, "item"),
            by_source=_group_by_text(ordered, "source"),
            by_skill=_group_by_text(ordered, "skill"),
            by_kind=_group_by_kind(ordered),
        )

    def for_item(self, object_id: str) -> tuple[ItemRelation, ...]:
        """Return all acquisition and skill rows for one item."""
        return self.by_item.get(object_id, ())

    def for_source(self, object_id: str) -> tuple[ItemRelation, ...]:
        """Return all rows emitted by one monster, shop, or source item."""
        return self.by_source.get(object_id, ())

    def for_skill(self, object_id: str) -> tuple[ItemRelation, ...]:
        """Return every item that provides one skill."""
        return self.by_skill.get(object_id, ())

    def for_kind(self, kind: ItemRelationKind) -> tuple[ItemRelation, ...]:
        """Return all rows of one relation kind."""
        return self.by_kind.get(kind, ())


def item_relation_sort_key(
    row: ItemRelation,
) -> tuple[str, str, str, str, int, int, int, str, int, int, str]:
    """Return the deterministic order used by indexes and exports."""
    return (
        row.kind.value,
        row.item.object_id,
        "" if row.source is None else row.source.object_id,
        "" if row.skill is None else row.skill.object_id,
        -1 if row.instance_serial is None else row.instance_serial,
        -1 if row.group_index is None else row.group_index,
        -1 if row.entry_index is None else row.entry_index,
        row.evidence.source,
        row.evidence.line,
        row.evidence.offset,
        row.relation_id,
    )


def _identity_payload(row: ItemRelation) -> tuple[JsonValue, ...]:
    return (
        row.kind.value,
        _endpoint_payload(row.item),
        None if row.source is None else _endpoint_payload(row.source),
        None if row.skill is None else _endpoint_payload(row.skill),
        row.map_name,
        row.instance_serial,
        row.player,
        _float_identity(row.x),
        _float_identity(row.y),
        _float_identity(row.z),
        row.group_index,
        row.entry_index,
        row.chance,
        row.slot,
        tuple((_endpoint_payload(item.item), item.count) for item in row.ingredients),
        (
            row.evidence.source,
            row.evidence.field_key,
            row.evidence.function,
            row.evidence.trigger,
            row.evidence.line,
            row.evidence.offset,
            row.evidence.location,
            row.evidence.raw,
        ),
        row.confidence.value,
        row.completeness.value,
        row.unresolved_reason,
    )


def _endpoint_payload(endpoint: RelationObject) -> tuple[str, str, str]:
    return endpoint.category, endpoint.object_id, endpoint.name


def _float_identity(value: float | None) -> str | None:
    return None if value is None else value.hex()


def _group_by_text(
    records: tuple[ItemRelation, ...],
    endpoint: Literal["item", "source", "skill"],
) -> Mapping[str, tuple[ItemRelation, ...]]:
    grouped: dict[str, list[ItemRelation]] = {}
    for row in records:
        match endpoint:
            case "item":
                object_id = row.item.object_id
            case "source":
                object_id = "" if row.source is None else row.source.object_id
            case "skill":
                object_id = "" if row.skill is None else row.skill.object_id
            case unreachable:
                assert_never(unreachable)
        if object_id:
            grouped.setdefault(object_id, []).append(row)
    return MappingProxyType({key: tuple(values) for key, values in grouped.items()})


def _group_by_kind(
    records: tuple[ItemRelation, ...],
) -> Mapping[ItemRelationKind, tuple[ItemRelation, ...]]:
    grouped: dict[ItemRelationKind, list[ItemRelation]] = {}
    for row in records:
        grouped.setdefault(row.kind, []).append(row)
    return MappingProxyType({key: tuple(values) for key, values in grouped.items()})


_EMPTY_INDEX: Final = ItemRelationIndex.build(())


def empty_item_relation_index() -> ItemRelationIndex:
    """Return the shared empty immutable relation index."""
    return _EMPTY_INDEX
