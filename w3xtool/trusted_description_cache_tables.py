"""Strict owned source-manifest and rejection-table parsing."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from io import StringIO
import re
from typing import Final

from .batch_tsv import decode_tsv_cell, format_tsv_rows
from .description_cache_migration_models import DescriptionCacheRejectionReason
from .description_cache_schema import (
    DESCRIPTION_CACHE_REJECTION_HEADER,
    DESCRIPTION_CACHE_SOURCE_HEADER,
    is_digest,
)


_POSITIVE_INTEGER: Final = re.compile(r"[1-9][0-9]*")


@dataclass(frozen=True, slots=True)
class DescriptionCacheSourceRecord:
    """One exact source report row bound by the owned source table."""

    row_number: int
    category: str
    base_id: str
    role: str
    level_text: str
    source_map_sha256: str
    report_path: str
    report_sha256: str
    report_row_number: int
    report_row_sha256: str
    source_label: str


class TrustedTableError(ValueError):
    """An owned TSV table is malformed or noncanonical."""

    __slots__ = ("detail",)

    detail: str

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail

    def __str__(self) -> str:
        return self.detail


def parse_source_manifest(payload: bytes) -> tuple[DescriptionCacheSourceRecord, ...]:
    """Parse exact source identities, paths, digests, and row numbers."""
    rows = _parse_tsv(payload, "source manifest", DESCRIPTION_CACHE_SOURCE_HEADER)
    records: list[DescriptionCacheSourceRecord] = []
    for row_number, row in enumerate(rows, 2):
        if not row[0] or not row[1] or not row[2]:
            raise TrustedTableError("empty source identity")
        if not is_digest(row[4]) or not is_digest(row[6]) or not is_digest(row[8]):
            raise TrustedTableError("invalid source digest")
        if _POSITIVE_INTEGER.fullmatch(row[7]) is None:
            raise TrustedTableError("invalid source report row number")
        records.append(
            DescriptionCacheSourceRecord(
                row_number,
                row[0],
                row[1],
                row[2],
                row[3],
                row[4],
                row[5],
                row[6],
                int(row[7]),
                row[8],
                row[9],
            )
        )
    return tuple(records)


def parse_source_level(value: str) -> int | None:
    """Parse the source table's canonical optional decimal level."""
    if not value:
        return None
    if not value.isascii() or not value.isdecimal() or str(int(value)) != value:
        raise TrustedTableError("invalid source level")
    return int(value)


def validate_rejection_table(payload: bytes) -> None:
    """Require exact rejection width, reasons, row numbers, and TSV form."""
    rows = _parse_tsv(payload, "rejection table", DESCRIPTION_CACHE_REJECTION_HEADER)
    for row in rows:
        try:
            _ = DescriptionCacheRejectionReason(row[-3])
        except ValueError as exc:
            raise TrustedTableError("invalid rejection reason") from exc
        if _POSITIVE_INTEGER.fullmatch(row[-1]) is None:
            raise TrustedTableError("invalid rejection row number")


def _parse_tsv(
    payload: bytes,
    label: str,
    header: tuple[str, ...],
) -> tuple[tuple[str, ...], ...]:
    try:
        text = payload.decode("utf-8")
        with StringIO(text, newline="") as handle:
            rows = tuple(
                tuple(decode_tsv_cell(cell) for cell in row)
                for row in csv.reader(handle, delimiter="\t", strict=True)
            )
    except (UnicodeError, csv.Error) as exc:
        raise TrustedTableError(f"invalid {label}: {type(exc).__name__}") from exc
    if not rows or rows[0] != header:
        raise TrustedTableError(f"invalid {label} header")
    if any(len(row) != len(header) for row in rows[1:]):
        raise TrustedTableError(f"invalid {label} row width")
    if format_tsv_rows((header, *rows[1:])).encode("utf-8") != payload:
        raise TrustedTableError(f"{label} TSV round-trip mismatch")
    return rows[1:]


__all__ = (
    "DescriptionCacheSourceRecord",
    "TrustedTableError",
    "parse_source_level",
    "parse_source_manifest",
    "validate_rejection_table",
)
