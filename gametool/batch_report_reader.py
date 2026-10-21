"""Standard lossless TSV reader for required batch publication reports."""

from __future__ import annotations

import csv
from io import StringIO
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
    return read_report_rows_bytes(path.read_bytes(), path.name, header)


def read_report_rows_bytes(
    content: bytes,
    report_name: str,
    header: tuple[str, ...],
    legacy_headers: tuple[tuple[str, ...], ...] = (),
) -> tuple[tuple[str, ...], ...]:
    """Decode one exact-header TSV from its verified byte snapshot.

    ``legacy_headers`` 允许"现表头去掉表尾追加列"的历史形态（只允许更短）：
    命中旧表头时数据行右侧补空对齐到现表头长度，其余校验不变，
    以便历史批次产物在新版本下继续通过续跑/校验。
    """
    previous_limit = csv.field_size_limit()
    try:
        csv.field_size_limit(sys.maxsize)
        reader = csv.reader(
            StringIO(content.decode("utf-8"), newline=""), delimiter="\t"
        )
        first = next(reader, None)
        decoded_header = (
            None if first is None else tuple(decode_tsv_cell(cell) for cell in first)
        )
        rows = tuple(tuple(decode_tsv_cell(cell) for cell in row) for row in reader)
    finally:
        csv.field_size_limit(previous_limit)
    matched: tuple[str, ...] | None = None
    if decoded_header == header:
        matched = header
    else:
        for variant in legacy_headers:
            if decoded_header == variant:
                matched = variant
                break
    if matched is None:
        raise BatchReportValidationError(f"unexpected report header: {report_name}")
    pad = len(header) - len(matched)
    if pad < 0:
        raise BatchReportValidationError(f"unexpected report header: {report_name}")
    if any(len(row) != len(matched) for row in rows):
        raise BatchReportValidationError(f"malformed report row: {report_name}")
    if pad:
        rows = tuple(row + ("",) * pad for row in rows)
    return rows


__all__ = (
    "BatchReportValidationError",
    "read_report_rows",
    "read_report_rows_bytes",
)
