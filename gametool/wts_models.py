"""Immutable, byte-attributed evidence for Warcraft string-table members."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class WtsRecordState(StrEnum):
    CONFIRMED = "confirmed"
    DUPLICATE = "duplicate"
    CONFLICT = "conflict"
    INCOMPLETE = "incomplete"
    INVALID = "invalid"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class WtsRecord:
    ordinal: int
    string_id: int | None
    id_text: str
    state: WtsRecordState
    byte_start: int
    byte_end: int
    line_start: int
    line_end: int
    raw_bytes: bytes
    raw_text: str
    body_start: int | None = None
    body_end: int | None = None
    body_bytes: bytes | None = None
    text: str | None = None


@dataclass(frozen=True, slots=True)
class WtsRegion:
    """Every byte outside logical records, including BOM and accepted trivia."""

    kind: str
    byte_start: int
    byte_end: int
    line_start: int
    line_end: int
    raw_bytes: bytes
    raw_text: str


@dataclass(frozen=True, slots=True)
class WtsDiagnostic:
    kind: str
    message: str
    record_ordinals: tuple[int, ...]
    byte_start: int
    byte_end: int
    line_start: int
    line_end: int
    blocking: bool = True


@dataclass(frozen=True, slots=True)
class WtsReport:
    source: str
    raw_bytes: bytes
    table: Mapping[int, str]
    records: tuple[WtsRecord, ...]
    regions: tuple[WtsRegion, ...]
    diagnostics: tuple[WtsDiagnostic, ...]

    @property
    def complete(self) -> bool:
        return not any(item.blocking for item in self.diagnostics)


def wts_report_to_dict(report: WtsReport) -> dict[str, object]:
    """Return complete JSON-safe evidence without decimal integer text quotas.

    IDs are decimal strings, offsets are zero-based half-open byte ranges, and
    lines/record ordinals are one-based. Base64 preserves even undecodable bytes.
    """
    return {
        "source": report.source,
        "complete": report.complete,
        "raw_bytes_base64": _base64(report.raw_bytes),
        "confirmed": [
            {"string_id": str(Decimal(sid)), "text": text}
            for sid, text in report.table.items()
        ],
        "records": [
            {
                "ordinal": row.ordinal,
                "string_id": (
                    str(Decimal(row.string_id)) if row.string_id is not None else None
                ),
                "id_text": row.id_text,
                "state": row.state.value,
                "byte_start": row.byte_start,
                "byte_end": row.byte_end,
                "line_start": row.line_start,
                "line_end": row.line_end,
                "raw_bytes_base64": _base64(row.raw_bytes),
                "raw_text": row.raw_text,
                "body_start": row.body_start,
                "body_end": row.body_end,
                "body_bytes_base64": (
                    _base64(row.body_bytes) if row.body_bytes is not None else None
                ),
                "text": row.text,
            }
            for row in report.records
        ],
        "regions": [
            {
                "kind": row.kind,
                "byte_start": row.byte_start,
                "byte_end": row.byte_end,
                "line_start": row.line_start,
                "line_end": row.line_end,
                "raw_bytes_base64": _base64(row.raw_bytes),
                "raw_text": row.raw_text,
            }
            for row in report.regions
        ],
        "diagnostics": [
            {
                "kind": row.kind,
                "message": row.message,
                "record_ordinals": list(row.record_ordinals),
                "byte_start": row.byte_start,
                "byte_end": row.byte_end,
                "line_start": row.line_start,
                "line_end": row.line_end,
                "blocking": row.blocking,
            }
            for row in report.diagnostics
        ],
    }


def _base64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")
