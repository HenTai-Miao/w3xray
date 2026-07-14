"""Aggregate loaded indexes and render per-map item-intelligence reports."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Final

from .item_relation_exports import (
    format_equipment_skills_tsv,
    format_item_acquisition_tsv,
    format_relation_completeness,
)
from .item_relation_models import (
    ItemRelationIndex,
    ItemRelationKind,
    RelationCompleteness,
)
from .map_data import GameObject, MapData
from .object_text_exports import format_object_text_tsv
from .object_text_models import ObjectTextIndex, ObjectTextState

_INCOMPLETE_TEXT_STATES: Final = frozenset(
    (
        ObjectTextState.AUTHOR_UNDEFINED,
        ObjectTextState.SOURCE_UNAVAILABLE,
        ObjectTextState.SOURCE_CONFLICT,
    )
)


@dataclass(frozen=True, slots=True)
class BatchItemReports:
    """One immutable aggregate over a root map and all campaign children."""

    maps: tuple[MapData, ...]
    objects: tuple[GameObject, ...]
    object_texts: ObjectTextIndex
    item_relations: ItemRelationIndex
    description_counts: tuple[tuple[str, int], ...]
    text_incomplete_count: int
    relation_counts: tuple[tuple[str, int], ...]
    relation_incomplete_count: int

    def artifacts(self) -> tuple[tuple[str, str], ...]:
        """Render lossless complete-text and relation artifacts."""
        return (
            ("对象完整描述.tsv", format_object_text_tsv(self.object_texts)),
            ("掉落与获取关系.tsv", format_item_acquisition_tsv(self.item_relations)),
            ("装备技能关系.tsv", format_equipment_skills_tsv(self.item_relations)),
            ("关系完整性.txt", format_relation_completeness(self.item_relations)),
        )


def build_batch_item_reports(root: MapData) -> BatchItemReports:
    """Combine existing indexes without reparsing scripts or placement data."""
    maps = _all_maps(root)
    objects = tuple(
        obj for item in maps for values in item.objects.values() for obj in values
    )
    object_texts = ObjectTextIndex.build(
        record for item in maps for record in item.object_texts.records
    )
    item_relations = ItemRelationIndex.build(
        relation for item in maps for relation in item.item_relations.records
    )
    text_counts = Counter(record.state for record in object_texts.records)
    relation_counts = Counter(relation.kind for relation in item_relations.records)
    return BatchItemReports(
        maps=maps,
        objects=objects,
        object_texts=object_texts,
        item_relations=item_relations,
        description_counts=tuple(
            (state.value, text_counts[state]) for state in ObjectTextState
        ),
        text_incomplete_count=sum(
            record.state in _INCOMPLETE_TEXT_STATES for record in object_texts.records
        ),
        relation_counts=tuple(
            (kind.value, relation_counts[kind]) for kind in ItemRelationKind
        ),
        relation_incomplete_count=sum(
            relation.completeness is not RelationCompleteness.COMPLETE
            for relation in item_relations.records
        ),
    )


def _all_maps(root: MapData) -> tuple[MapData, ...]:
    pending = [root]
    maps: list[MapData] = []
    while pending:
        current = pending.pop()
        maps.append(current)
        pending.extend(reversed(current.sub_maps))
    return tuple(maps)
