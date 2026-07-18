"""Strict boundary parsing for canonical global icon evidence TSV payloads."""

from __future__ import annotations

import csv
from io import StringIO
import re
import sys
from typing import Final, assert_never

from .batch_global_evidence_models import GlobalEvidenceError, GlobalIconGap
from .batch_tsv import decode_tsv_cell
from .icon_evidence_models import (
    IconCandidateEvidence,
    IconCandidateKind,
    IconDiagnosticFlag,
    IconGapReason,
)
from .icon_gap_reference_codec import parse_icon_gap_references
from .icon_path_evidence import plan_icon_path
from .icon_resources import IconObjectReference


GLOBAL_ICON_GAP_HEADER: Final = (
    "地图路径",
    "地图SHA256",
    "子地图",
    "规范路径",
    "主原因",
    "诊断标志",
    "对象分类",
    "Rawcode",
    "引用数",
    "引用集合",
)
GLOBAL_ICON_CANDIDATE_HEADER: Final = (
    "候选类型",
    "请求地图SHA256",
    "请求路径",
    "匿名地图SHA256",
    "匿名块编号",
    "候选地图SHA256",
    "候选路径",
    "内容SHA256",
    "是否采用",
)
_SHA256: Final = re.compile(r"[0-9a-f]{64}")


def parse_global_icon_gaps_tsv(text: str) -> tuple[GlobalIconGap, ...]:
    """Parse exact global gap rows and reject noncanonical identities."""
    columns = _columns(GLOBAL_ICON_GAP_HEADER)
    parsed: list[GlobalIconGap] = []
    for row in _rows(text, GLOBAL_ICON_GAP_HEADER):
        map_path = row[columns["地图路径"]]
        map_sha256 = _digest(row[columns["地图SHA256"]], "gap map SHA-256")
        map_scope = row[columns["子地图"]]
        normalized = row[columns["规范路径"]]
        if not normalized or plan_icon_path(normalized).normalized != normalized:
            raise GlobalEvidenceError("invalid normalized global gap path")
        try:
            reason = IconGapReason(row[columns["主原因"]])
            diagnostics = _diagnostics(row[columns["诊断标志"]])
            identities = parse_icon_gap_references(row[columns["引用集合"]])
        except ValueError as exc:
            raise GlobalEvidenceError("invalid global gap row") from exc
        references = tuple(
            IconObjectReference(
                item.category,
                item.rawcode,
                item.name,
                item.base,
                item.map,
                map_sha256,
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
        categories = _evidence_cell(row[columns["对象分类"]])
        rawcodes = _evidence_cell(row[columns["Rawcode"]])
        reference_count = _nonnegative(row[columns["引用数"]], "reference count")
        if (
            reference_count != len(references)
            or categories != _ordered(item.category for item in references)
            or rawcodes != _ordered(item.object_id for item in references)
            or any(
                item.map_path.casefold() != map_path.casefold() for item in references
            )
            or any(item.map_scope != map_scope for item in references)
        ):
            raise GlobalEvidenceError("global gap references do not reconcile")
        parsed.append(
            GlobalIconGap(
                map_path,
                map_sha256,
                map_scope,
                normalized,
                reason,
                diagnostics,
                categories,
                rawcodes,
                references,
                reference_count,
            )
        )
    identities = {
        (row.map_path.casefold(), row.map_sha256, row.normalized_path.casefold())
        for row in parsed
    }
    if len(identities) != len(parsed):
        raise GlobalEvidenceError("duplicate global gap row")
    return tuple(parsed)


def parse_icon_candidates_tsv(text: str) -> tuple[IconCandidateEvidence, ...]:
    """Parse only the two closed, explicitly non-adopted candidate variants."""
    columns = _columns(GLOBAL_ICON_CANDIDATE_HEADER)
    parsed: list[IconCandidateEvidence] = []
    for row in _rows(text, GLOBAL_ICON_CANDIDATE_HEADER):
        try:
            kind = IconCandidateKind(row[columns["候选类型"]])
        except ValueError as exc:
            raise GlobalEvidenceError("unknown global icon candidate kind") from exc
        if row[columns["是否采用"]] != "否":
            raise GlobalEvidenceError("global icon candidate was adopted")
        requested_sha = row[columns["请求地图SHA256"]]
        requested_path = row[columns["请求路径"]]
        anonymous_sha = row[columns["匿名地图SHA256"]]
        block_text = row[columns["匿名块编号"]]
        candidate_sha = _digest(row[columns["候选地图SHA256"]], "candidate map SHA-256")
        candidate_path = row[columns["候选路径"]]
        content_sha = _digest(row[columns["内容SHA256"]], "candidate content SHA-256")
        if (
            not candidate_path
            or plan_icon_path(candidate_path).normalized != candidate_path
        ):
            raise GlobalEvidenceError("invalid global candidate path")
        match kind:
            case IconCandidateKind.EXACT_OTHER_MAP_PATH:
                requested_sha = _digest(requested_sha, "requested map SHA-256")
                if (
                    not requested_path
                    or plan_icon_path(requested_path).normalized != requested_path
                    or requested_path.casefold() != candidate_path.casefold()
                    or requested_sha == candidate_sha
                    or anonymous_sha
                    or block_text
                ):
                    raise GlobalEvidenceError("invalid exact-path candidate")
                block_index = None
            case IconCandidateKind.ANONYMOUS_HASH_MATCH:
                anonymous_sha = _digest(anonymous_sha, "anonymous map SHA-256")
                if requested_sha or requested_path or anonymous_sha == candidate_sha:
                    raise GlobalEvidenceError("invalid anonymous-hash candidate")
                block_index = _nonnegative(block_text, "anonymous block index")
            case unreachable:
                assert_never(unreachable)
        parsed.append(
            IconCandidateEvidence(
                kind,
                requested_sha,
                requested_path,
                anonymous_sha,
                block_index,
                candidate_sha,
                candidate_path,
                content_sha,
            )
        )
    if len(set(parsed)) != len(parsed):
        raise GlobalEvidenceError("duplicate global icon candidate")
    return tuple(parsed)


def _rows(text: str, header: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    previous_limit = csv.field_size_limit()
    try:
        csv.field_size_limit(sys.maxsize)
        reader = csv.reader(StringIO(text, newline=""), delimiter="\t")
        first = next(reader, None)
        decoded = (
            None if first is None else tuple(decode_tsv_cell(cell) for cell in first)
        )
        if decoded != header:
            raise GlobalEvidenceError("unexpected global evidence header")
        rows = tuple(tuple(decode_tsv_cell(cell) for cell in row) for row in reader)
    finally:
        csv.field_size_limit(previous_limit)
    if any(len(row) != len(header) for row in rows):
        raise GlobalEvidenceError("malformed global evidence row")
    return rows


def _diagnostics(text: str) -> tuple[IconDiagnosticFlag, ...]:
    import json

    value = json.loads(text)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise GlobalEvidenceError("invalid global diagnostics")
    flags = tuple(IconDiagnosticFlag(item) for item in value)
    if flags != tuple(sorted(set(flags), key=lambda item: item.value)):
        raise GlobalEvidenceError("unordered global diagnostics")
    return flags


def _columns(header: tuple[str, ...]) -> dict[str, int]:
    return {name: index for index, name in enumerate(header)}


def _evidence_cell(text: str) -> tuple[str, ...]:
    values = () if not text else tuple(text.split(";"))
    if values != _ordered(values):
        raise GlobalEvidenceError("unordered global identity cell")
    return values


def _ordered(values) -> tuple[str, ...]:
    return tuple(sorted(set(values), key=lambda value: (value.casefold(), value)))


def _digest(text: str, label: str) -> str:
    if _SHA256.fullmatch(text) is None:
        raise GlobalEvidenceError(f"invalid {label}")
    return text


def _nonnegative(text: str, label: str) -> int:
    if not text.isdecimal():
        raise GlobalEvidenceError(f"invalid {label}")
    return int(text)


__all__ = (
    "GLOBAL_ICON_CANDIDATE_HEADER",
    "GLOBAL_ICON_GAP_HEADER",
    "parse_global_icon_gaps_tsv",
    "parse_icon_candidates_tsv",
)
