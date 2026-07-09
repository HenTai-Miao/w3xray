"""Compatibility facade for war3map.wtg trigger tree parsing."""

from __future__ import annotations

from .trigger_schema import TriggerSchema
from .wtg_classic import parse_classic
from .wtg_diagnostics import TriggerParseFailure, UnknownTriggerFunction, WtgReadError
from .wtg_models import (
    TriggerCategory,
    TriggerEcaFunction,
    TriggerEcaParameter,
    TriggerHeader,
    TriggerTreeSummary,
    TriggerVariable,
)
from .wtg_reader import WtgReader
from .wtg_reforged import parse_reforged

_REFORGED_MARKER = 0x80000004


def parse_wtg(data: bytes, schema: TriggerSchema | None = None) -> TriggerTreeSummary:
    """Parse trigger tree metadata and schema-backed ECA bodies from war3map.wtg."""
    reader = WtgReader(data)
    try:
        if reader.raw(4) != b"WTG!":
            raise ValueError("not a war3map.wtg file")
        marker = reader.u32()
        if marker == _REFORGED_MARKER:
            return parse_reforged(reader, schema)
        return parse_classic(reader, _to_i32(marker), schema)
    except WtgReadError as exc:
        raise ValueError("truncated war3map.wtg") from exc


def _to_i32(value: int) -> int:
    return value - 0x1_0000_0000 if value > 0x7FFF_FFFF else value


__all__ = [
    "TriggerCategory",
    "TriggerEcaFunction",
    "TriggerEcaParameter",
    "TriggerHeader",
    "TriggerParseFailure",
    "TriggerTreeSummary",
    "TriggerVariable",
    "UnknownTriggerFunction",
    "parse_wtg",
]
