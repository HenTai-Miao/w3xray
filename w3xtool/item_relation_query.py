"""Pure filtering shared by the relation GUI and acceptance checks."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final

from .base_names import BASE_NAMES_EN
from .item_relation_models import ItemRelation, relation_endpoints
from .item_relation_presentation import format_relation_evidence
from .search import compile_query

ALL_RELATIONS_LABEL: Final = "全部"


def _relation_search_text(relation: ItemRelation) -> str:
    """Evidence text plus endpoint English names for bilingual search."""
    english_names: list[str] = []
    for endpoint in relation_endpoints(relation):
        english = BASE_NAMES_EN.get(endpoint.object_id)
        if english:
            english_names.append(english)
    extras = " ".join(dict.fromkeys(english_names))
    text = format_relation_evidence(relation)
    return f"{text}\n{extras}" if extras else text


def filter_item_relations(
    records: Iterable[ItemRelation],
    query: str,
    kind_filter: str = ALL_RELATIONS_LABEL,
    confidence_filter: str = ALL_RELATIONS_LABEL,
    fine_filter: str = ALL_RELATIONS_LABEL,
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
        and (
            fine_filter == ALL_RELATIONS_LABEL
            or any(
                endpoint.fine_category == fine_filter
                for endpoint in relation_endpoints(relation)
            )
        )
        and compiled.score(_relation_search_text(relation)) is not None
    )
