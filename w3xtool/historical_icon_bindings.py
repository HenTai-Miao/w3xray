"""Select conflict-free object icon paths from exact-map history."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from .icon_path_evidence import plan_icon_path
from .icon_resources import HistoricalIconEvidenceSet, NamedIconResource
from .map_data import GameObject


def unique_historical_object_icons(
    objects: Iterable[GameObject],
    load_history: Callable[[], HistoricalIconEvidenceSet],
) -> tuple[tuple[GameObject, NamedIconResource], ...]:
    """Return only exact category/rawcode bindings with one historical path."""
    missing = tuple(
        obj
        for obj in objects
        if obj.icon_field_evidence is None and not obj.icon_fields_evidence
    )
    if not missing:
        return ()
    grouped: dict[
        tuple[str, str],
        dict[tuple[str, str, str], NamedIconResource],
    ] = {}
    for resource in load_history().resources:
        binding = (
            resource.normalized_path.casefold(),
            resource.resolved_path.casefold(),
            resource.sha256,
        )
        for historical_object in resource.objects:
            grouped.setdefault(
                (historical_object.category, historical_object.object_id), {}
            ).setdefault(binding, resource)
    result: list[tuple[GameObject, NamedIconResource]] = []
    for obj in missing:
        bindings = grouped.get((obj.category, obj.obj_id), {})
        if len(bindings) != 1:
            continue
        resource = next(iter(bindings.values()))
        current_path = plan_icon_path(obj.icon).normalized
        if (
            current_path
            and current_path.casefold() != resource.normalized_path.casefold()
        ):
            continue
        result.append((obj, resource))
    return tuple(result)
