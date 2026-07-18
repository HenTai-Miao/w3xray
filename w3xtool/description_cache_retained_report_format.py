"""Canonical schema-one JSON formatting for cache retention reports."""

from __future__ import annotations

import json

from .description_cache_retained_integrity_models import (
    DescriptionCacheRetentionReport,
    MalformedDescriptionCacheArtifact,
    RetainedDescriptionCacheArtifact,
    TransientDescriptionCacheArtifact,
)
from .description_cache_retained_report_validation import validate_retention_report


type JsonValue = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)


def format_description_cache_retention_report(
    report: DescriptionCacheRetentionReport,
) -> str:
    """Serialize the exact schema-one report with canonical JSON layout."""
    validate_retention_report(report)
    value = {
        "active_device": report.active_device,
        "active_inode": report.active_inode,
        "active_root": str(report.active_root),
        "malformed": [_other_value(item) for item in report.malformed],
        "retained": [_retained_value(item) for item in report.retained],
        "schema": report.schema,
        "transient": [_other_value(item) for item in report.transient],
    }
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _retained_value(item: RetainedDescriptionCacheArtifact) -> dict[str, JsonValue]:
    return {
        "device": item.device,
        "entry_count": item.entry_count,
        "file_count": item.file_count,
        "inode": item.inode,
        "kind": item.kind.value,
        "path": str(item.path),
        "problem_path": item.problem_path,
        "role": item.role.value,
        "sha256": item.sha256,
        "size": item.size,
        "transaction_id": item.transaction_id,
        "validation": item.validation.value,
    }


def _other_value(
    item: TransientDescriptionCacheArtifact | MalformedDescriptionCacheArtifact,
) -> dict[str, JsonValue]:
    return {
        "device": item.device,
        "inode": item.inode,
        "kind": item.kind.value,
        "path": str(item.path),
        "reason": item.reason.value,
        "transaction_id": item.transaction_id,
    }


__all__ = ("format_description_cache_retention_report",)
