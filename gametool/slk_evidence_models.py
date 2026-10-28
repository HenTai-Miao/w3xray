"""Immutable source locations for sparse, lossless SLK evidence."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import json


def coordinate_text(value: int | None) -> str | None:
    """Format arbitrarily long coordinates without the int/string digit quota."""
    return None if value is None else str(Decimal(value))


@dataclass(frozen=True, slots=True)
class SlkField:
    raw: str
    start: int
    end: int
    complete: bool = True


@dataclass(frozen=True, slots=True)
class SlkRecord:
    line_number: int
    start: int
    end: int
    raw: str
    kind: str
    fields: tuple[SlkField, ...]


@dataclass(frozen=True, slots=True)
class SlkCell:
    record_index: int
    field_index: int
    x: int | None
    y: int | None
    value: str | None
    value_kind: str
    valid: bool


@dataclass(frozen=True, slots=True)
class SlkDiagnostic:
    code: str
    message: str
    record_indexes: tuple[int, ...] = ()
    cell_indexes: tuple[int, ...] = ()
    conflict: bool = False


@dataclass(frozen=True, slots=True)
class SlkColumn:
    number: int
    name: str | None
    candidate_names: tuple[str, ...]
    cell_indexes: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class SlkRow:
    number: int
    key: str | None
    cell_indexes: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class SlkObjectRow:
    key: str
    fields: tuple[tuple[str, str], ...]
    row_numbers: tuple[int, ...]
    value_kinds: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class SlkEvidence:
    """Original input plus every encoded record, cell and physical row.

    Locations are character offsets into ``raw``; record raw text includes its
    original CR/LF ending. ``raw_bytes`` retains archive bytes when supplied.
    Coordinates describe encoded cells only; no rectangular ranges are built.
    ``objects`` is the conservative named projection, never a last-write view.
    """

    raw: str
    raw_bytes: bytes | None
    records: tuple[SlkRecord, ...]
    cells: tuple[SlkCell, ...]
    columns: tuple[SlkColumn, ...]
    rows: tuple[SlkRow, ...]
    objects: tuple[SlkObjectRow, ...]
    opaque: tuple[int, ...]
    diagnostics: tuple[SlkDiagnostic, ...]
    blocked_fields: frozenset[tuple[str, str]]
    max_x: int
    max_y: int

    def as_dict(self) -> dict[str, dict[str, str]]:
        """Return a fresh compatibility view, including explicitly empty cells."""
        return {row.key: dict(row.fields) for row in self.objects}

    def diagnostic_text(self, diagnostic: SlkDiagnostic) -> str:
        """Serialize complete relevant evidence without flattening raw controls."""
        indexes = dict.fromkeys(diagnostic.record_indexes)
        for index in diagnostic.cell_indexes:
            indexes[self.cells[index].record_index] = None
        payload = {
            "code": diagnostic.code,
            "message": diagnostic.message,
            "conflict": diagnostic.conflict,
            "records": [self.record_payload(index) for index in indexes],
            "cells": [self.cell_payload(index) for index in diagnostic.cell_indexes],
        }
        # Map diagnostics normalize control characters. JSON escapes retain the
        # exact source text through that existing boundary, including TAB/CR/LF.
        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))

    def record_payload(self, index: int) -> dict[str, object]:
        record = self.records[index]
        return {
            "index": index,
            "line_number": record.line_number,
            "start": record.start,
            "end": record.end,
            "raw": record.raw,
            "kind": record.kind,
            "fields": [
                {
                    "raw": field.raw,
                    "start": field.start,
                    "end": field.end,
                    "complete": field.complete,
                }
                for field in record.fields
            ],
        }

    def cell_payload(self, index: int) -> dict[str, object]:
        cell = self.cells[index]
        record = self.records[cell.record_index]
        field = record.fields[cell.field_index]
        return {
            "index": index,
            "record_index": cell.record_index,
            "field_index": cell.field_index,
            "line_number": record.line_number,
            "x": coordinate_text(cell.x),
            "y": coordinate_text(cell.y),
            "start": field.start,
            "end": field.end,
            "raw": field.raw,
            "value": cell.value,
            "value_kind": cell.value_kind,
            "valid": cell.valid,
        }
