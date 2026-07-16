"""Strict schema-1 batch-state parsing for cache migration."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Final

from .description_cache_migration_models import (
    DescriptionCacheMigrationError,
    LegacyStateResult,
)
from .description_cache_schema import is_digest
from .safe_output import safe_relative_path


_STATE_KEYS: Final = frozenset(("schema_version", "results"))
_SOURCE_KEYS: Final = frozenset(("path", "size", "mtime_ns", "sha256"))
_RESULT_KEYS: Final = frozenset(
    (
        "source",
        "display_name",
        "output_directory",
        "stage",
        "state",
        "first_error",
        "object_count",
        "description_counts",
        "named_icon_count",
        "anonymous_icon_count",
        "original_written_count",
        "png_written_count",
        "icon_failure_count",
        "restricted_block_count",
        "elapsed_ms",
    )
)
_COUNT_KEYS: Final = tuple(
    _RESULT_KEYS
    - {
        "source",
        "display_name",
        "output_directory",
        "stage",
        "state",
        "first_error",
        "description_counts",
    }
)

type JsonValue = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)


def parse_legacy_state(payload: bytes) -> tuple[LegacyStateResult, ...]:
    """Parse exact schema-1 state and reject ambiguous result identities."""
    try:
        value: JsonValue = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_unique_mapping,
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DescriptionCacheMigrationError("legacy state JSON is unreadable") from exc
    root = _mapping(value, "legacy state")
    _require_keys(root, _STATE_KEYS)
    if _integer(root["schema_version"], "schema version") != 1:
        raise DescriptionCacheMigrationError("unsupported legacy state schema")
    raw_results = root["results"]
    if not isinstance(raw_results, list):
        raise DescriptionCacheMigrationError("legacy state results must be a list")
    results = tuple(_parse_result(item) for item in raw_results)
    if len({item.source_sha256 for item in results}) != len(results):
        raise DescriptionCacheMigrationError("duplicate legacy state source digest")
    if len({item.output_directory for item in results}) != len(results):
        raise DescriptionCacheMigrationError("duplicate legacy state output directory")
    if len({item.source_path for item in results}) != len(results):
        raise DescriptionCacheMigrationError("duplicate legacy state source path")
    return results


def _unique_mapping(pairs: list[tuple[str, JsonValue]]) -> Mapping[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, value in pairs:
        if key in result:
            raise DescriptionCacheMigrationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _parse_result(value: JsonValue) -> LegacyStateResult:
    raw = _mapping(value, "legacy result")
    _require_keys(raw, _RESULT_KEYS)
    source = _mapping(raw["source"], "legacy source")
    _require_keys(source, _SOURCE_KEYS)
    source_path = _text(source["path"], "source path")
    digest = _text(source["sha256"], "source SHA-256")
    output_directory = _text(raw["output_directory"], "output directory")
    if not source_path or not is_digest(digest):
        raise DescriptionCacheMigrationError("invalid legacy source identity")
    if safe_relative_path(output_directory) is None:
        raise DescriptionCacheMigrationError("legacy output directory escapes root")
    _ = _nonnegative(source["size"], "source size")
    _ = _nonnegative(source["mtime_ns"], "source mtime")
    for name in _COUNT_KEYS:
        _ = _nonnegative(raw[name], name)
    _validate_counts(raw["description_counts"])
    for name in ("display_name", "stage", "state", "first_error"):
        _ = _text(raw[name], name)
    return LegacyStateResult(
        source_path,
        digest,
        output_directory,
        _text(raw["stage"], "stage"),
    )


def _mapping(value: JsonValue, label: str) -> Mapping[str, JsonValue]:
    if not isinstance(value, dict):
        raise DescriptionCacheMigrationError(f"{label} must be an object")
    return value


def _require_keys(value: Mapping[str, JsonValue], expected: frozenset[str]) -> None:
    if set(value) != expected:
        raise DescriptionCacheMigrationError("unexpected legacy JSON keys")


def _text(value: JsonValue, label: str) -> str:
    if not isinstance(value, str):
        raise DescriptionCacheMigrationError(f"{label} must be text")
    return value


def _integer(value: JsonValue, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DescriptionCacheMigrationError(f"{label} must be an integer")
    return value


def _nonnegative(value: JsonValue, label: str) -> int:
    number = _integer(value, label)
    if number < 0:
        raise DescriptionCacheMigrationError(f"{label} must be nonnegative")
    return number


def _validate_counts(value: JsonValue) -> None:
    if not isinstance(value, list):
        raise DescriptionCacheMigrationError("description counts must be a list")
    labels: set[str] = set()
    for row in value:
        if not isinstance(row, list) or len(row) != 2:
            raise DescriptionCacheMigrationError("invalid description count row")
        label = _text(row[0], "description count label")
        if not label or label in labels:
            raise DescriptionCacheMigrationError("duplicate description count label")
        labels.add(label)
        _ = _nonnegative(row[1], "description count")


__all__ = ("parse_legacy_state",)
