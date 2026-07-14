"""Deterministic TSV serialization for batch reports."""

from __future__ import annotations

import csv
from collections.abc import Iterable
from io import StringIO


def format_tsv_rows(rows: Iterable[tuple[str, ...]]) -> str:
    """Serialize lossless cells with standard tab-delimited quoting."""
    with StringIO(newline="") as output:
        writer = csv.writer(output, delimiter="\t", lineterminator="\n")
        writer.writerows(rows)
        return output.getvalue()
