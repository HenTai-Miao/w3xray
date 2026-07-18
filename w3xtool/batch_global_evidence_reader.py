"""Parse verified per-map report snapshots into global icon evidence."""

from __future__ import annotations

import json
import re
from typing import Final, assert_never

from .batch_global_evidence_models import (
    GlobalAnonymousIcon,
    GlobalEvidenceError,
    GlobalIconGap,
    GlobalResolvedIcon,
)
from .batch_icon_models import IconKind
from .batch_icon_reports import ICON_REPORT_HEADER
from .batch_models import MapBatchResult
from .batch_report_reader import read_report_rows_bytes
from .icon_evidence_exports import UNRESOLVED_ICON_HEADER
from .icon_evidence_models import (
    IconDiagnosticFlag,
    IconGapReason,
    IconResolutionLayer,
)
from .icon_gap_reference_codec import parse_icon_gap_references
from .icon_path_evidence import plan_icon_path
from .icon_resources import IconObjectReference


_SHA256: Final = re.compile(r"[0-9a-f]{64}")
_GAP_COLUMNS: Final = {name: index for index, name in enumerate(UNRESOLVED_ICON_HEADER)}
_ICON_COLUMNS: Final = {name: index for index, name in enumerate(ICON_REPORT_HEADER)}


def read_global_gap_rows(
    content: bytes,
    result: MapBatchResult,
) -> tuple[GlobalIconGap, ...]:
    """Parse canonical unresolved rows from verified report bytes."""
    parsed: list[GlobalIconGap] = []
    rows = read_report_rows_bytes(content, "图标未解析.tsv", UNRESOLVED_ICON_HEADER)
    for row in rows:
        normalized = row[_GAP_COLUMNS["规范路径"]]
        if not normalized or plan_icon_path(normalized).normalized != normalized:
            raise GlobalEvidenceError("invalid normalized global gap path")
        try:
            reason = IconGapReason(row[_GAP_COLUMNS["主原因"]])
            diagnostics = _diagnostics(row[_GAP_COLUMNS["诊断标志"]])
            identities = parse_icon_gap_references(row[_GAP_COLUMNS["引用集合"]])
        except ValueError as exc:
            raise GlobalEvidenceError("invalid global gap evidence") from exc
        map_path = row[_GAP_COLUMNS["地图路径"]]
        map_scope = row[_GAP_COLUMNS["子地图"]]
        references = tuple(
            IconObjectReference(
                item.category,
                item.rawcode,
                item.name,
                item.base,
                item.map,
                result.source.sha256,
                item.scope,
                item.field,
                item.label,
                item.type,
                item.source,
                item.wts,
                normalized_path=normalized,
            )
            for item in identities
        )
        categories = _split_evidence(row[_GAP_COLUMNS["对象分类"]])
        rawcodes = _split_evidence(row[_GAP_COLUMNS["Rawcode"]])
        declared = _nonnegative(row[_GAP_COLUMNS["引用数"]], "gap reference count")
        if (
            declared != len(references)
            or categories != _ordered_unique(item.category for item in references)
            or rawcodes != _ordered_unique(item.object_id for item in references)
            or any(
                item.map_path.casefold() != map_path.casefold() for item in references
            )
            or any(item.map_scope != map_scope for item in references)
        ):
            raise GlobalEvidenceError("global gap reference reconciliation failed")
        parsed.append(
            GlobalIconGap(
                map_path,
                result.source.sha256,
                map_scope,
                normalized,
                reason,
                diagnostics,
                categories,
                rawcodes,
                references,
                declared,
            )
        )
    return tuple(parsed)


def read_global_icon_rows(
    content: bytes,
    result: MapBatchResult,
) -> tuple[tuple[GlobalResolvedIcon, ...], tuple[GlobalAnonymousIcon, ...]]:
    """Parse named and anonymous rows from verified report bytes."""
    named: list[GlobalResolvedIcon] = []
    anonymous: list[GlobalAnonymousIcon] = []
    rows = read_report_rows_bytes(content, "图标索引.tsv", ICON_REPORT_HEADER)
    for row in rows:
        try:
            kind = IconKind(row[_ICON_COLUMNS["类型"]])
        except ValueError as exc:
            raise GlobalEvidenceError("unknown global icon kind") from exc
        digest = row[_ICON_COLUMNS["SHA256"]]
        if _SHA256.fullmatch(digest) is None:
            raise GlobalEvidenceError("invalid global icon SHA-256")
        match kind:
            case IconKind.NAMED:
                named.append(_named_icon(row, result, digest))
            case IconKind.ANONYMOUS:
                anonymous.append(_anonymous_icon(row, result, digest))
            case unreachable:
                assert_never(unreachable)
    return tuple(named), tuple(anonymous)


def _named_icon(
    row: tuple[str, ...], result: MapBatchResult, digest: str
) -> GlobalResolvedIcon:
    normalized = plan_icon_path(row[_ICON_COLUMNS["原始路径"]]).normalized
    try:
        layer = IconResolutionLayer(row[_ICON_COLUMNS["解析层"]])
    except ValueError as exc:
        raise GlobalEvidenceError("unknown global icon resolution layer") from exc
    if not normalized or row[_ICON_COLUMNS["块编号"]]:
        raise GlobalEvidenceError("invalid named global icon row")
    return GlobalResolvedIcon(
        result.source.path,
        result.source.sha256,
        normalized,
        layer,
        digest,
        row[_ICON_COLUMNS["真实来源"]],
    )


def _anonymous_icon(
    row: tuple[str, ...], result: MapBatchResult, digest: str
) -> GlobalAnonymousIcon:
    if (
        row[_ICON_COLUMNS["原始路径"]]
        or row[_ICON_COLUMNS["解析路径"]]
        or row[_ICON_COLUMNS["解析层"]]
    ):
        raise GlobalEvidenceError("invalid anonymous global icon row")
    block_index = _nonnegative(row[_ICON_COLUMNS["块编号"]], "anonymous block index")
    return GlobalAnonymousIcon(
        result.source.path,
        result.source.sha256,
        block_index,
        digest,
        row[_ICON_COLUMNS["真实来源"]],
    )


def _diagnostics(text: str) -> tuple[IconDiagnosticFlag, ...]:
    value = json.loads(text)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise GlobalEvidenceError("invalid global icon diagnostics")
    diagnostics = tuple(IconDiagnosticFlag(item) for item in value)
    if diagnostics != tuple(sorted(set(diagnostics), key=lambda item: item.value)):
        raise GlobalEvidenceError("unordered global icon diagnostics")
    return diagnostics


def _split_evidence(text: str) -> tuple[str, ...]:
    values = () if not text else tuple(text.split(";"))
    if values != _ordered_unique(values):
        raise GlobalEvidenceError("unordered global gap identity cells")
    return values


def _ordered_unique(values) -> tuple[str, ...]:
    return tuple(sorted(set(values), key=lambda value: (value.casefold(), value)))


def _nonnegative(text: str, label: str) -> int:
    if not text.isdecimal():
        raise GlobalEvidenceError(f"invalid {label}")
    return int(text)


__all__ = ("read_global_gap_rows", "read_global_icon_rows")
