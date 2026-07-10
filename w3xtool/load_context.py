"""Shared context for one map/campaign loading operation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .client_object_data import ClientBaseObject, collect_client_base_objects
from .trigger_schema import TriggerSchema


@dataclass(frozen=True, slots=True)
class MapLoadContext:
    external_names: tuple[str, ...] = ()
    trigger_schema: TriggerSchema | None = None
    author_bundle_path: str | None = None
    client_base_objects: tuple[ClientBaseObject, ...] = ()


def build_map_load_context(
    *,
    external_names: Sequence[str] = (),
    game_data_path: str | None = None,
    author_bundle_path: str | None = None,
) -> MapLoadContext:
    """Build immutable map inputs from the selected optional data sources."""
    from .game_data_source import open_game_data_source
    from .triggerdata import load_trigger_schema_from_source

    source = open_game_data_source(game_data_path)
    try:
        schema = load_trigger_schema_from_source(source)
        client_base_objects = collect_client_base_objects(source)
    finally:
        if source is not None:
            try:
                source.close()
            except OSError:
                source = None
    return MapLoadContext(
        tuple(external_names),
        schema,
        author_bundle_path,
        client_base_objects,
    )
