"""Shared context for one map/campaign loading operation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .trigger_schema import TriggerSchema


@dataclass(frozen=True, slots=True)
class MapLoadContext:
    external_names: tuple[str, ...] = ()
    trigger_schema: TriggerSchema | None = None


def build_map_load_context(
    *,
    external_names: Sequence[str] = (),
    game_data_path: str | None = None,
) -> MapLoadContext:
    """Build immutable map inputs from the selected optional data sources."""
    from .game_data_source import open_game_data_source
    from .triggerdata import load_trigger_schema_from_source

    source = open_game_data_source(game_data_path)
    try:
        schema = load_trigger_schema_from_source(source)
    finally:
        close = getattr(source, "close", None)
        if callable(close):
            try:
                close()
            except OSError:
                pass
    return MapLoadContext(tuple(external_names), schema)
