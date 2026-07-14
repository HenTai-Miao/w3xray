"""Deterministic TSV serialization for batch reports."""

from __future__ import annotations

import csv
from collections.abc import Iterable
from io import StringIO


def format_tsv_rows(rows: Iterable[tuple[str, ...]]) -> str:
    """Serialize sanitized cells with standard tab-delimited quoting."""
    with StringIO(newline="") as output:
        writer = csv.writer(output, delimiter="\t", lineterminator="\n")
        writer.writerows(tuple(_cell(value) for value in row) for row in rows)
        return output.getvalue()


def _cell(value: str) -> str:
    return (
        value.replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\t", " ")
        .replace("\n", "\\n")
    )
