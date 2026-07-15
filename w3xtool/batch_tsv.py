"""Deterministic TSV serialization for batch reports."""

from __future__ import annotations

import csv
from collections.abc import Iterable
from io import StringIO
from typing import Final
import unicodedata


_ESCAPE_PREFIX: Final = "'\u2060"
_FORMULA_PREFIXES: Final = frozenset(("=", "+", "-", "@"))
_IGNORABLE_CATEGORIES: Final = frozenset(("Cc", "Cf"))


def format_tsv_rows(rows: Iterable[tuple[str, ...]]) -> str:
    """Serialize reversible spreadsheet-safe cells with standard TSV quoting."""
    with StringIO(newline="") as output:
        writer = csv.writer(output, delimiter="\t", lineterminator="\n")
        writer.writerows(tuple(_encode_tsv_cell(cell) for cell in row) for row in rows)
        return output.getvalue()


def decode_tsv_cell(value: str) -> str:
    """Recover one exact source cell from the reversible safety envelope."""
    return value.removeprefix(_ESCAPE_PREFIX)


def _encode_tsv_cell(value: str) -> str:
    if value.startswith(_ESCAPE_PREFIX) or _starts_spreadsheet_formula(value):
        return f"{_ESCAPE_PREFIX}{value}"
    return value


def _starts_spreadsheet_formula(value: str) -> bool:
    for character in value:
        if character.isspace() or unicodedata.category(character) in _IGNORABLE_CATEGORIES:
            continue
        return character in _FORMULA_PREFIXES
    return False


__all__ = ("decode_tsv_cell", "format_tsv_rows")
