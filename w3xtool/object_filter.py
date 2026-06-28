"""Object browser filtering that can run outside the Tk main thread."""

from __future__ import annotations

from dataclasses import dataclass

from .api import GameObject, MapData
from .search import compile_query
from .theme import PARALLEL_CATS


@dataclass(frozen=True, slots=True)
class ObjectFilterResult:
    """Filtered objects for every object browser category."""

    results_by_category: dict[str, list[GameObject]]
    summary: tuple[str, ...]


def filter_objects_by_query(md: MapData, query: str) -> ObjectFilterResult:
    """Return per-category search results without touching Tk widgets."""
    normalized_query = query.strip()
    compiled_query = compile_query(normalized_query)
    results: dict[str, list[GameObject]] = {}
    summary: list[str] = []

    for category in PARALLEL_CATS:
        matches = _filter_category(
            objects=md.objects.get(category, []),
            query=normalized_query,
            compiled_query=compiled_query,
        )
        results[category] = matches
        summary.append(f"{category}{len(matches)}")

    return ObjectFilterResult(results_by_category=results, summary=tuple(summary))


def _filter_category(
    *,
    objects: list[GameObject],
    query: str,
    compiled_query,
) -> list[GameObject]:
    scored: list[tuple[int, int, GameObject]] = []
    for index, obj in enumerate(objects):
        score = compiled_query.score(_object_search_text(obj))
        if score is not None:
            scored.append((score, index, obj))
    if query:
        scored.sort(key=lambda item: (-item[0], item[1]))
    return [obj for _score, _index, obj in scored]


def _object_search_text(obj: GameObject) -> str:
    if obj.search_text:
        return obj.search_text
    return " ".join((obj.obj_id, obj.base_id, obj.name))
