"""Convert source-aware recipe evidence into item relations."""

from __future__ import annotations

from collections import Counter

from .item_relation_endpoints import resolve_relation_object
from .item_relation_models import (
    ItemRelation,
    ItemRelationKind,
    RelationCompleteness,
    RelationConfidence,
    RelationEvidence,
    RelationIngredient,
)
from .map_data import MapData
from .script_scan import scan_recipes
from .script_sources import analysis_script_texts


def build_recipe_item_relations(md: MapData) -> tuple[ItemRelation, ...]:
    """Return one counted, source-bearing relation per recognized recipe result."""
    rows: list[ItemRelation] = []
    for source, text in analysis_script_texts(md):
        for recipe in scan_recipes(text, source=source):
            result, result_resolved = resolve_relation_object(md, recipe.result, "物品")
            ingredients: list[RelationIngredient] = []
            unresolved: list[str] = []
            for item_id, count in sorted(Counter(recipe.ingredients).items()):
                item, resolved = resolve_relation_object(md, item_id, "物品")
                ingredients.append(RelationIngredient(item=item, count=count))
                if not resolved:
                    unresolved.append(f"材料 {item_id} 未解析")
            if not result_resolved:
                unresolved.append(f"成品 {recipe.result} 未解析")
            rows.append(
                ItemRelation(
                    kind=ItemRelationKind.RECIPE,
                    item=result,
                    ingredients=tuple(ingredients),
                    evidence=RelationEvidence(
                        source=recipe.source,
                        function=recipe.func,
                        line=recipe.line,
                        location=f"第 {recipe.line} 行" if recipe.line else "",
                        raw=recipe.evidence,
                    ),
                    confidence=RelationConfidence.CONFIRMED,
                    completeness=(
                        RelationCompleteness.UNRESOLVED
                        if unresolved
                        else RelationCompleteness.COMPLETE
                    ),
                    unresolved_reason="；".join(unresolved),
                    map_name=md.name,
                ),
            )
    return tuple(rows)
