"""Strict JSON boundary parser for cache retention reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from .description_cache_publication_models import RetainedCacheRole
from .description_cache_retained_integrity_models import (
    CacheArtifactKind,
    DescriptionCacheRetentionError,
    DescriptionCacheRetentionReport,
    MalformedDescriptionCacheArtifact,
    RetainedArtifactValidation,
    RetainedDescriptionCacheArtifact,
    RetentionArtifactReason,
    TransientDescriptionCacheArtifact,
)
from .description_cache_retained_report_validation import validate_retention_report


type JsonValue = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)

_TOP_KEYS: Final = frozenset(
    (
        "schema",
        "active_root",
        "active_device",
        "active_inode",
        "retained",
        "transient",
        "malformed",
    )
)
_RETAINED_KEYS: Final = frozenset(
    (
        "path",
        "transaction_id",
        "role",
        "kind",
        "device",
        "inode",
        "validation",
        "size",
        "file_count",
        "entry_count",
        "sha256",
        "problem_path",
    )
)
_OTHER_KEYS: Final = frozenset(
    ("path", "transaction_id", "kind", "device", "inode", "reason")
)


def parse_description_cache_retention_report(
    payload: str,
) -> DescriptionCacheRetentionReport:
    """Parse exact fields, enums, identities, proof totals, and ordering."""
    try:
        value: JsonValue = json.loads(payload, object_pairs_hook=_unique_mapping)
    except json.JSONDecodeError as exc:
        raise DescriptionCacheRetentionError(
            f"invalid retention report JSON: {exc.msg}"
        ) from exc
    root = _mapping(value, "report")
    _keys(root, _TOP_KEYS, "report")
    report = DescriptionCacheRetentionReport(
        _integer(root["schema"], "schema"),
        Path(_text(root["active_root"], "active root")),
        _nonnegative(root["active_device"], "active device"),
        _nonnegative(root["active_inode"], "active inode"),
        tuple(_parse_retained(item) for item in _rows(root["retained"], "retained")),
        tuple(_parse_transient(item) for item in _rows(root["transient"], "transient")),
        tuple(_parse_malformed(item) for item in _rows(root["malformed"], "malformed")),
    )
    validate_retention_report(report)
    return report


def _parse_retained(value: JsonValue) -> RetainedDescriptionCacheArtifact:
    row = _mapping(value, "retained row")
    _keys(row, _RETAINED_KEYS, "retained row")
    return RetainedDescriptionCacheArtifact(
        Path(_text(row["path"], "retained path")),
        _text(row["transaction_id"], "transaction ID"),
        _role(row["role"]),
        _kind(row["kind"]),
        _optional_nonnegative(row["device"], "device"),
        _optional_nonnegative(row["inode"], "inode"),
        _validation(row["validation"]),
        _optional_nonnegative(row["size"], "size"),
        _optional_nonnegative(row["file_count"], "file count"),
        _optional_nonnegative(row["entry_count"], "entry count"),
        _optional_text(row["sha256"], "SHA-256"),
        _optional_text(row["problem_path"], "problem path"),
    )


def _parse_transient(value: JsonValue) -> TransientDescriptionCacheArtifact:
    row = _mapping(value, "transient row")
    _keys(row, _OTHER_KEYS, "transient row")
    return TransientDescriptionCacheArtifact(
        Path(_text(row["path"], "transient path")),
        _optional_text(row["transaction_id"], "transaction ID"),
        _kind(row["kind"]),
        _optional_nonnegative(row["device"], "device"),
        _optional_nonnegative(row["inode"], "inode"),
        _reason(row["reason"]),
    )


def _parse_malformed(value: JsonValue) -> MalformedDescriptionCacheArtifact:
    row = _mapping(value, "malformed row")
    _keys(row, _OTHER_KEYS, "malformed row")
    return MalformedDescriptionCacheArtifact(
        Path(_text(row["path"], "malformed path")),
        _optional_text(row["transaction_id"], "transaction ID"),
        _kind(row["kind"]),
        _optional_nonnegative(row["device"], "device"),
        _optional_nonnegative(row["inode"], "inode"),
        _reason(row["reason"]),
    )


def _mapping(value: JsonValue, label: str) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise DescriptionCacheRetentionError(f"{label} must be an object")
    return value


def _rows(value: JsonValue, label: str) -> list[JsonValue]:
    if not isinstance(value, list):
        raise DescriptionCacheRetentionError(f"{label} must be a list")
    return value


def _keys(value: dict[str, JsonValue], expected: frozenset[str], label: str) -> None:
    if set(value) != expected:
        raise DescriptionCacheRetentionError(f"unexpected {label} keys")


def _text(value: JsonValue, label: str) -> str:
    if not isinstance(value, str):
        raise DescriptionCacheRetentionError(f"{label} must be text")
    return value


def _optional_text(value: JsonValue, label: str) -> str | None:
    return None if value is None else _text(value, label)


def _integer(value: JsonValue, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DescriptionCacheRetentionError(f"{label} must be an integer")
    return value


def _nonnegative(value: JsonValue, label: str) -> int:
    result = _integer(value, label)
    if result < 0:
        raise DescriptionCacheRetentionError(f"{label} must be nonnegative")
    return result


def _optional_nonnegative(value: JsonValue, label: str) -> int | None:
    return None if value is None else _nonnegative(value, label)


def _role(value: JsonValue) -> RetainedCacheRole:
    try:
        return RetainedCacheRole(_text(value, "role"))
    except ValueError as exc:
        raise DescriptionCacheRetentionError("unknown retained role") from exc


def _kind(value: JsonValue) -> CacheArtifactKind:
    try:
        return CacheArtifactKind(_text(value, "kind"))
    except ValueError as exc:
        raise DescriptionCacheRetentionError("unknown artifact kind") from exc


def _validation(value: JsonValue) -> RetainedArtifactValidation:
    try:
        return RetainedArtifactValidation(_text(value, "validation"))
    except ValueError as exc:
        raise DescriptionCacheRetentionError("unknown retained validation") from exc


def _reason(value: JsonValue) -> RetentionArtifactReason:
    try:
        return RetentionArtifactReason(_text(value, "reason"))
    except ValueError as exc:
        raise DescriptionCacheRetentionError("unknown retention reason") from exc


def _unique_mapping(pairs: list[tuple[str, JsonValue]]) -> dict[str, JsonValue]:
    result: dict[str, JsonValue] = {}
    for key, value in pairs:
        if key in result:
            raise DescriptionCacheRetentionError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


__all__ = ("parse_description_cache_retention_report",)
