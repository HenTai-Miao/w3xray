"""Lossless per-map reports derived from immutable icon evidence."""

from __future__ import annotations

from collections.abc import Iterable
import json
from typing import Final, TypedDict

from .batch_icon_models import IconExportRecord
from .batch_tsv import format_tsv_rows
from .icon_evidence_counts import (
    icon_gap_identity,
    icon_integrity_counts,
    normalized_icon_gap_count as normalized_icon_gap_count,
)
from .icon_evidence_index import IconEvidenceIndex
from .icon_evidence_models import IconLookupAttempt, UnresolvedIconEvidence
from .icon_resources import IconObjectReference

UNRESOLVED_ICON_HEADER: Final = (
    "地图路径",
    "地图SHA256",
    "子地图",
    "原始路径集合",
    "规范路径",
    "尝试路径",
    "主原因",
    "诊断标志",
    "查询证据",
    "对象分类",
    "Rawcode",
    "引用数",
    "引用集合",
)


class _ReferenceJson(TypedDict):
    category: str
    rawcode: str
    base: str
    name: str
    field: str
    label: str
    type: str
    source: str
    wts: str
    map: str
    scope: str


class _AttemptJson(TypedDict):
    layer: str
    candidate: str
    source: str
    found: bool
    resolved: str
    sha256: str


def format_unresolved_icon_tsv(index: IconEvidenceIndex) -> str:
    """Render one stable row per logical map and normalized missing path."""
    rows: list[tuple[str, ...]] = [UNRESOLVED_ICON_HEADER]
    for group in _gap_groups(index):
        primary = group[0]
        references = _references(group)
        attempts = _attempts(group)
        rows.append(
            (
                primary.reference.map_path,
                primary.reference.map_sha256,
                primary.reference.map_scope,
                _compact_json(
                    _ordered_unique(row.reference.requested_path for row in group)
                ),
                primary.reference.normalized_path,
                _compact_json(
                    _ordered_unique(item.candidate_path for item in attempts)
                ),
                primary.reason.value,
                _compact_json(
                    tuple(
                        sorted(
                            {flag.value for row in group for flag in row.diagnostics}
                        )
                    )
                ),
                _compact_json(tuple(_attempt_json(item) for item in attempts)),
                ";".join(_ordered_unique(item["category"] for item in references)),
                ";".join(_ordered_unique(item["rawcode"] for item in references)),
                str(len(references)),
                _compact_json(references),
            )
        )
    return format_tsv_rows(rows)


def format_icon_integrity(
    index: IconEvidenceIndex,
    exports: Iterable[IconExportRecord],
) -> str:
    """Render explicit reconciled counters for evidence and write outcomes."""
    counts = icon_integrity_counts(index, exports)
    lines = (
        ("有效引用", counts.valid_reference_count),
        ("已解析引用", counts.resolved_reference_count),
        ("过滤字段", counts.filtered_field_count),
        ("具名未解析", counts.normalized_gap_count),
        ("未解析引用", counts.unresolved_reference_count),
        ("匿名载荷", counts.anonymous_payload_count),
        ("匿名读取失败", counts.anonymous_read_failure_count),
        ("原始写出失败", counts.original_write_failure_count),
        ("PNG失败", counts.png_failure_count),
    )
    return "\n".join(f"{label}：{count}" for label, count in lines) + "\n"


def _gap_groups(
    index: IconEvidenceIndex,
) -> tuple[tuple[UnresolvedIconEvidence, ...], ...]:
    grouped: dict[tuple[str, str, str], list[UnresolvedIconEvidence]] = {}
    for row in index.unresolved:
        key = icon_gap_identity(row.reference)
        grouped.setdefault(key, []).append(row)
    return tuple(tuple(grouped[key]) for key in sorted(grouped))


def _references(
    rows: tuple[UnresolvedIconEvidence, ...],
) -> tuple[_ReferenceJson, ...]:
    by_identity: dict[tuple[str, ...], _ReferenceJson] = {}
    for row in rows:
        reference = row.reference
        payload = _reference_json(reference)
        identity = tuple(payload[key] for key in _REFERENCE_KEY_ORDER)
        by_identity.setdefault(identity, payload)
    return tuple(by_identity[key] for key in sorted(by_identity, key=_text_tuple_key))


_REFERENCE_KEY_ORDER: Final = (
    "category",
    "rawcode",
    "base",
    "name",
    "field",
    "label",
    "type",
    "source",
    "wts",
    "map",
    "scope",
)


def _reference_json(reference: IconObjectReference) -> _ReferenceJson:
    return _ReferenceJson(
        category=reference.category,
        rawcode=reference.object_id,
        base=reference.base_id,
        name=reference.object_name,
        field=reference.field_key,
        label=reference.field_label,
        type=reference.field_type,
        source=reference.field_source,
        wts=reference.wts_source,
        map=reference.map_path,
        scope=reference.map_scope,
    )


def _attempts(
    rows: tuple[UnresolvedIconEvidence, ...],
) -> tuple[IconLookupAttempt, ...]:
    unique = {item for row in rows for item in row.attempts}
    return tuple(sorted(unique, key=_attempt_key))


def _attempt_json(attempt: IconLookupAttempt) -> _AttemptJson:
    return _AttemptJson(
        layer=attempt.layer.value,
        candidate=attempt.candidate_path,
        source=attempt.source_path,
        found=attempt.found,
        resolved=attempt.resolved_path,
        sha256=attempt.content_sha256,
    )


def _attempt_key(attempt: IconLookupAttempt) -> tuple[str, ...]:
    return (
        attempt.layer.value,
        attempt.candidate_path.casefold(),
        attempt.candidate_path,
        attempt.source_path.casefold(),
        attempt.source_path,
        str(int(attempt.found)),
        attempt.resolved_path,
        attempt.content_sha256,
    )


def _ordered_unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(set(values), key=lambda value: (value.casefold(), value)))


def _text_tuple_key(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(part for value in values for part in (value.casefold(), value))


def _compact_json(
    value: tuple[str, ...] | tuple[_ReferenceJson, ...] | tuple[_AttemptJson, ...],
) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
