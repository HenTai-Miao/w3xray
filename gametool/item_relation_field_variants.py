"""Select highest-priority object-field variants for item relations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from .item_relation_models import ItemRelationKind
from .map_data import GameObject, GameObjectFieldEvidence, MapData

_FIELD_ROLES: Final[Mapping[str, ItemRelationKind]] = MappingProxyType(
    {
        "sellitems": ItemRelationKind.SHOP_SELL,
        "usei": ItemRelationKind.SHOP_SELL,
        "makeitems": ItemRelationKind.SHOP_MAKE,
        "umki": ItemRelationKind.SHOP_MAKE,
        "abillist": ItemRelationKind.ITEM_ABILITY,
        "iabi": ItemRelationKind.ITEM_ABILITY,
        "cooldownid": ItemRelationKind.COOLDOWN_ABILITY,
        "icid": ItemRelationKind.COOLDOWN_ABILITY,
    }
)
_PLACEHOLDER_CODES: Final = frozenset(("____", "----", "0000"))


@dataclass(frozen=True, slots=True)
class RelationFieldVariant:
    kind: ItemRelationKind
    field: GameObjectFieldEvidence
    conflict: bool


def relation_objects(md: MapData) -> tuple[GameObject, ...]:
    """Return category-safe relation objects with legacy-map compatibility."""
    values = (
        md.obj_identity_index.values()
        if md.obj_identity_index
        else md.obj_index.values()
    )
    unique = {(item.category, item.obj_id): item for item in values}
    return tuple(
        unique[key]
        for key in sorted(unique, key=lambda value: (value[0].casefold(), value[1]))
    )


def relation_field_variants(obj: GameObject) -> tuple[RelationFieldVariant, ...]:
    """Retain every highest-tier field value and mark differing values as conflicts."""
    evidence = tuple(
        row for row in obj.field_evidence if row.key.casefold() in _FIELD_ROLES
    )
    if not evidence:
        evidence = tuple(
            GameObjectFieldEvidence(
                key=key,
                label=obj.field_labels.get(key, key),
                value=raw,
                source=obj.field_sources.get(key, "对象字段"),
                source_priority=0,
            )
            for key, raw in obj.field_values.items()
            if key.casefold() in _FIELD_ROLES
        )
    grouped: dict[ItemRelationKind, list[GameObjectFieldEvidence]] = {}
    for row in evidence:
        kind = _FIELD_ROLES[row.key.casefold()]
        grouped.setdefault(kind, []).append(row)
    variants: list[RelationFieldVariant] = []
    for kind, rows in grouped.items():
        highest = max(row.source_priority for row in rows)
        selected = tuple(
            sorted(
                {row for row in rows if row.source_priority == highest},
                key=lambda row: (
                    row.key.casefold(),
                    row.source.casefold(),
                    row.source,
                    row.value,
                ),
            )
        )
        conflict = len({row.value for row in selected}) > 1
        variants.extend(RelationFieldVariant(kind, row, conflict) for row in selected)
    return tuple(sorted(variants, key=_relation_field_sort_key))


def split_relation_codes(raw: str) -> tuple[str, ...]:
    """Split a relation-bearing list without inventing placeholder endpoints."""
    codes: list[str] = []
    for token in raw.replace("|", ",").split(","):
        code = token.strip().strip("\x00")
        if len(code) != 4 or code in _PLACEHOLDER_CODES or code.isdigit():
            continue
        if code not in codes:
            codes.append(code)
    return tuple(codes)


def _relation_field_sort_key(
    variant: RelationFieldVariant,
) -> tuple[str, str, str, str]:
    return (
        variant.kind.value,
        variant.field.key.casefold(),
        variant.field.source.casefold(),
        variant.field.value,
    )
