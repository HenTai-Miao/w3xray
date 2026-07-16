"""Standard lossless TSV reader for required batch publication reports."""

from __future__ import annotations

import csv
from pathlib import Path
import sys

from .batch_tsv import decode_tsv_cell


class BatchReportValidationError(ValueError):
    """A required publication report has an invalid tabular schema."""

    __slots__ = ("detail",)

    detail: str

    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail

    def __str__(self) -> str:
        return self.detail


def read_report_rows(
    path: Path,
    header: tuple[str, ...],
) -> tuple[tuple[str, ...], ...]:
    """Decode one exact-header TSV report with the shared cell codec."""
    previous_limit = csv.field_size_limit()
    try:
        csv.field_size_limit(sys.maxsize)
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle, delimiter="\t")
            first = next(reader, None)
            decoded_header = (
                None
                if first is None
                else tuple(decode_tsv_cell(cell) for cell in first)
            )
            if decoded_header != header:
                raise BatchReportValidationError(
                    f"unexpected report header: {path.name}"
                )
            rows = tuple(tuple(decode_tsv_cell(cell) for cell in row) for row in reader)
    finally:
        csv.field_size_limit(previous_limit)
    if any(len(row) != len(header) for row in rows):
        raise BatchReportValidationError(f"malformed report row: {path.name}")
    return rows
