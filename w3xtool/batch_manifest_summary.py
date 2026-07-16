"""Strict JSON codec for the report-reconciled manifest result summary."""

from __future__ import annotations

from .batch_manifest_models import BatchManifestFormatError, ManifestResultSummary
from .batch_models import MapBatchState

type JsonValue = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)


def manifest_summary_payload(
    summary: ManifestResultSummary,
) -> dict[str, str | int | list[list[str | int]]]:
    """Return the deterministic JSON-compatible summary mapping."""
    return {
        "anonymous_icon_count": summary.anonymous_icon_count,
        "description_counts": [list(item) for item in summary.description_counts],
        "icon_failure_count": summary.icon_failure_count,
        "named_icon_count": summary.named_icon_count,
        "object_count": summary.object_count,
        "original_written_count": summary.original_written_count,
        "png_written_count": summary.png_written_count,
        "relation_counts": [list(item) for item in summary.relation_counts],
        "relation_incomplete_count": summary.relation_incomplete_count,
        "restricted_block_count": summary.restricted_block_count,
        "stage": summary.stage,
        "state": summary.state.value,
        "valid_icon_reference_count": summary.valid_icon_reference_count,
        "resolved_icon_reference_count": summary.resolved_icon_reference_count,
        "filtered_icon_field_count": summary.filtered_icon_field_count,
        "unresolved_icon_count": summary.unresolved_icon_count,
        "unresolved_icon_reference_count": summary.unresolved_icon_reference_count,
        "anonymous_read_failure_count": summary.anonymous_read_failure_count,
        "original_write_failure_count": summary.original_write_failure_count,
        "png_failure_count": summary.png_failure_count,
    }


def parse_manifest_summary(value: JsonValue) -> ManifestResultSummary:
    """Parse an exact-key, nonnegative manifest result summary."""
    raw = _mapping(value, "result")
    keys = {
        "anonymous_icon_count",
        "description_counts",
        "icon_failure_count",
        "named_icon_count",
        "object_count",
        "original_written_count",
        "png_written_count",
        "relation_counts",
        "relation_incomplete_count",
        "restricted_block_count",
        "stage",
        "state",
        "valid_icon_reference_count",
        "resolved_icon_reference_count",
        "filtered_icon_field_count",
        "unresolved_icon_count",
        "unresolved_icon_reference_count",
        "anonymous_read_failure_count",
        "original_write_failure_count",
        "png_failure_count",
    }
    _require_keys(raw, keys)
    return ManifestResultSummary(
        _string(raw["stage"], "result stage"),
        MapBatchState(_string(raw["state"], "result state")),
        _nonnegative(raw["object_count"], "object count"),
        _counts(raw["description_counts"], "description counts"),
        _nonnegative(raw["named_icon_count"], "named icon count"),
        _nonnegative(raw["anonymous_icon_count"], "anonymous icon count"),
        _nonnegative(raw["original_written_count"], "original written count"),
        _nonnegative(raw["png_written_count"], "PNG written count"),
        _nonnegative(raw["icon_failure_count"], "icon failure count"),
        _nonnegative(raw["restricted_block_count"], "restricted block count"),
        _counts(raw["relation_counts"], "relation counts"),
        _nonnegative(raw["relation_incomplete_count"], "relation incomplete count"),
        _nonnegative(raw["valid_icon_reference_count"], "valid icon reference count"),
        _nonnegative(
            raw["resolved_icon_reference_count"], "resolved icon reference count"
        ),
        _nonnegative(raw["filtered_icon_field_count"], "filtered icon field count"),
        _nonnegative(raw["unresolved_icon_count"], "unresolved icon count"),
        _nonnegative(
            raw["unresolved_icon_reference_count"],
            "unresolved icon reference count",
        ),
        _nonnegative(
            raw["anonymous_read_failure_count"], "anonymous read failure count"
        ),
        _nonnegative(
            raw["original_write_failure_count"], "original write failure count"
        ),
        _nonnegative(raw["png_failure_count"], "PNG failure count"),
    )


def _counts(value: JsonValue, label: str) -> tuple[tuple[str, int], ...]:
    if not isinstance(value, list):
        raise BatchManifestFormatError(f"{label} must be a list")
    result: list[tuple[str, int]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, list) or len(item) != 2:
            raise BatchManifestFormatError(f"invalid {label} row")
        name = _string(item[0], f"{label} label")
        if not name or name in seen:
            raise BatchManifestFormatError(f"duplicate {label} label")
        seen.add(name)
        result.append((name, _nonnegative(item[1], f"{label} value")))
    return tuple(result)


def _mapping(value: JsonValue, label: str) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise BatchManifestFormatError(f"{label} must be an object")
    return value


def _require_keys(value: dict[str, JsonValue], expected: set[str]) -> None:
    if set(value) != expected:
        raise BatchManifestFormatError("unexpected JSON keys")


def _string(value: JsonValue, label: str) -> str:
    if not isinstance(value, str):
        raise BatchManifestFormatError(f"{label} must be text")
    return value


def _nonnegative(value: JsonValue, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BatchManifestFormatError(f"{label} must be an integer")
    if value < 0:
        raise BatchManifestFormatError(f"{label} must be nonnegative")
    return value
