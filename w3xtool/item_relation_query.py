"""Pure filtering shared by the relation GUI and acceptance checks."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final

from .item_relation_models import ItemRelation
from .item_relation_presentation import format_relation_evidence
from .search import compile_query

ALL_RELATIONS_LABEL: Final = "全部"


def filter_item_relations(
    records: Iterable[ItemRelation],
    query: str,
    kind_filter: str = ALL_RELATIONS_LABEL,
    confidence_filter: str = ALL_RELATIONS_LABEL,
) -> tuple[ItemRelation, ...]:
    """Return every matching relation in source order without a display limit."""
    compiled = compile_query(query.strip())
    return tuple(
        relation
        for relation in records
        if (kind_filter == ALL_RELATIONS_LABEL or relation.kind.value == kind_filter)
        and (
            confidence_filter == ALL_RELATIONS_LABEL
            or relation.confidence.value == confidence_filter
        )
        and compiled.score(format_relation_evidence(relation)) is not None
    )
