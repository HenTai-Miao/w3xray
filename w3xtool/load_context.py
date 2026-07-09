"""Shared context for one map/campaign loading operation."""

from __future__ import annotations

from dataclasses import dataclass

from .trigger_schema import TriggerSchema


@dataclass(frozen=True, slots=True)
class MapLoadContext:
    external_names: tuple[str, ...] = ()
    trigger_schema: TriggerSchema | None = None
