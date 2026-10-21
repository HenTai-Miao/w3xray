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
from .object_text_names import normalized_name, trusted_source_kind
from .script_sources import analysis_script_texts
from .slk_objects import SLK_CATEGORY_FILES

_INCOMPLETE_TEXT_STATES: Final = frozenset(
    (
        ObjectTextState.AUTHOR_UNDEFINED,
        ObjectTextState.SOURCE_UNAVAILABLE,
        ObjectTextState.SOURCE_CONFLICT,
    )
)
_OBJECT_BINARY_SUFFIXES: Final = (
    ".w3u",
    ".w3t",
    ".w3a",
    ".w3q",
    ".w3b",
    ".w3d",
    ".w3h",
)
_STRUCTURAL_SOURCE_NAMES: Final = frozenset(
    ("war3map.wtg", "war3map.wct", "war3map.doo", "war3mapunits.doo")
)
_SLK_SOURCE_NAMES: Final = frozenset(
    name.casefold() for names in SLK_CATEGORY_FILES.values() for name in names
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
    source_coverage_gap_count: int

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
        source_coverage_gap_count=_source_coverage_gap_count(maps),
    )


def _all_maps(root: MapData) -> tuple[MapData, ...]:
    pending = [root]
    maps: list[MapData] = []
    while pending:
        current = pending.pop()
        maps.append(current)
        pending.extend(reversed(current.sub_maps))
    return tuple(maps)


def _source_coverage_gap_count(maps: tuple[MapData, ...]) -> int:
    analysis_maps = tuple(
        item for item in maps if not item.path.casefold().endswith(".w3n")
    )
    if not analysis_maps:
        return int(bool(maps))
    return sum(not _has_substantive_source(item) for item in analysis_maps)


def _has_substantive_source(md: MapData) -> bool:
    if any(md.objects.values()) or analysis_script_texts(md):
        return True
    failed_sources = {normalized_name(item.source) for item in md.diagnostics}
    return any(
        _is_analysis_source(name) and normalized_name(name) not in failed_sources
        for name in md.all_files
    )


def _is_analysis_source(name: str) -> bool:
    normalized = normalized_name(name)
    basename = normalized.rsplit("\\", 1)[-1]
    if basename in _STRUCTURAL_SOURCE_NAMES or basename in _SLK_SOURCE_NAMES:
        return True
    if basename.startswith(("war3map.", "war3campaign.")) and basename.endswith(
        _OBJECT_BINARY_SUFFIXES
    ):
        return True
    return trusted_source_kind(name) is not None
