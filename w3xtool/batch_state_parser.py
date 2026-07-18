"""Strict root parser for authoritative schema-five batch state."""

from __future__ import annotations

import json
from typing import Final

from .batch_models import (
    BATCH_SCHEMA_VERSION,
    BatchState,
    BatchStateFormatError,
)
from .batch_result_parser import JsonValue, parse_map_batch_result
from .batch_state_validation import require_unique_results


_STATE_KEYS: Final = frozenset(("schema_version", "results"))


def parse_state_json(text: str) -> BatchState:
    """Parse exact root JSON/schema/identities and delegate result rows."""
    try:
        value: JsonValue = json.loads(text)
    except json.JSONDecodeError as exc:
        raise BatchStateFormatError(f"invalid batch state JSON: {exc.msg}") from exc
    root = _mapping(value, "batch state")
    _require_keys(root, _STATE_KEYS)
    if _integer(root["schema_version"], "schema version") != BATCH_SCHEMA_VERSION:
        raise BatchStateFormatError("unsupported batch state schema")
    raw_results = root["results"]
    if not isinstance(raw_results, list):
        raise BatchStateFormatError("batch state results must be a list")
    results = tuple(parse_map_batch_result(item) for item in raw_results)
    require_unique_results(results)
    return BatchState(BATCH_SCHEMA_VERSION, results)


def _mapping(value: JsonValue, label: str) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise BatchStateFormatError(f"{label} must be an object")
    return value


def _require_keys(value: dict[str, JsonValue], expected: frozenset[str]) -> None:
    if set(value) != expected:
        raise BatchStateFormatError("unexpected batch state keys")


def _integer(value: JsonValue, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BatchStateFormatError(f"{label} must be an integer")
    return value


__all__ = ("parse_state_json",)
