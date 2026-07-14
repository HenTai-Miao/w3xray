"""Immutable item-relation records and reverse indexes."""

from dataclasses import FrozenInstanceError
from types import MappingProxyType

import pytest

from w3xtool.item_relation_models import (
    ItemRelation,
    ItemRelationIndex,
    ItemRelationKind,
    RelationCompleteness,
    RelationConfidence,
    RelationEvidence,
    RelationObject,
)


def _drop_relation(*, group_index: int, entry_index: int = 0) -> ItemRelation:
    return ItemRelation(
        kind=ItemRelationKind.UNIT_DROP,
        item=RelationObject("物品", "I001", "力量指环"),
        source=RelationObject("单位", "n001", "掉落怪"),
        instance_serial=10,
        group_index=group_index,
        entry_index=entry_index,
        chance=50,
        evidence=RelationEvidence(source="war3mapUnits.doo", offset=128),
        confidence=RelationConfidence.CONFIRMED,
        completeness=RelationCompleteness.COMPLETE,
    )


def test_relation_id_is_stable_but_distinct_per_drop_group() -> None:
    # Given: duplicate evidence and an otherwise identical entry from another group.
    first = _drop_relation(group_index=0)
    same = _drop_relation(group_index=0)
    other_group = _drop_relation(group_index=1)

    # When: records are indexed.
    index = ItemRelationIndex.build((first, same, other_group))

    # Then: exact duplicates collapse, group identity survives, and reverse indexes agree.
    assert first.relation_id == same.relation_id
    assert first.relation_id != other_group.relation_id
    assert index.records == (first, other_group)
    assert index.for_item("I001") == (first, other_group)
    assert index.for_source("n001") == (first, other_group)
    assert index.for_kind(ItemRelationKind.UNIT_DROP) == (first, other_group)


def test_relation_records_and_indexes_are_immutable() -> None:
    # Given: one fully resolved relation.
    relation = _drop_relation(group_index=0)
    index = ItemRelationIndex.build((relation,))

    # When/Then: callers cannot mutate either the record or a reverse index mapping.
    with pytest.raises(FrozenInstanceError):
        setattr(relation, "chance", 100)
    assert isinstance(index.by_item, MappingProxyType)
