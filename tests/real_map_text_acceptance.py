"""Shared lossless-TSV helpers for real-map text acceptance."""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from w3xtool.batch_tsv import decode_tsv_cell

_PLACEHOLDERS: Final = frozenset(("", "-", "_", ",", '""', "''"))


@dataclass(frozen=True, slots=True)
class TsvTable:
    """One parsed TSV table whose quoted fields may contain newlines."""

    header: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]

    def value(self, row: tuple[str, ...], column: str) -> str:
        return row[self.header.index(column)]


@dataclass(frozen=True, slots=True)
class TextIdentity:
    """Stable object-text identity used by schema-v2 acceptance."""

    category: str
    object_id: str
    level: str
    role: str


def read_tsv(path: Path) -> TsvTable:
    """Read a UTF-8 TSV using standard quoting and newline semantics."""
    with path.open("r", encoding="utf-8", newline="") as handle:
        return _table_from_rows(
            tuple(
                tuple(decode_tsv_cell(cell) for cell in row)
                for row in csv.reader(handle, delimiter="\t")
            )
        )


def read_tsv_text(text: str) -> TsvTable:
    """Parse one in-memory TSV export without normalizing physical newlines."""
    return _table_from_rows(
        tuple(
            tuple(decode_tsv_cell(cell) for cell in row)
            for row in csv.reader(io.StringIO(text), delimiter="\t")
        )
    )


def missing_legacy_text(
    digest: str,
    old: TsvTable,
    new: TsvTable,
) -> tuple[str, ...]:
    """Report legacy text values absent from the complete-text publication."""
    compatible_values: defaultdict[TextIdentity, set[str]] = defaultdict(set)
    for row in new.rows:
        identity = TextIdentity(
            new.value(row, "分类"),
            new.value(row, "对象ID"),
            new.value(row, "等级/变体"),
            new.value(row, "文本角色"),
        )
        value = new.value(row, "原始全文")
        compatible_values[identity].update(
            (value, legacy_report_value(value), legacy_text_report_value(value))
        )
    missing: list[str] = []
    for column, default_role in (
        ("原始提示", "基础提示"),
        ("原始说明", "扩展提示"),
    ):
        for row in old.rows:
            value = old.value(row, column)
            category = old.value(row, "分类")
            role = default_role
            if category == "增益":
                role = "Buff提示" if column == "原始提示" else "Buff扩展提示"
            identity = TextIdentity(
                category,
                old.value(row, "对象ID"),
                old.value(row, "等级"),
                role,
            )
            identities = (identity,)
            if identity.level:
                identities = (
                    identity,
                    TextIdentity(
                        identity.category,
                        identity.object_id,
                        "",
                        identity.role,
                    ),
                )
            if identity.category == "科技" and not identity.level:
                identities = (
                    identity,
                    TextIdentity(
                        identity.category,
                        identity.object_id,
                        "1",
                        identity.role,
                    ),
                )
            if column == "原始说明":
                identities = (
                    *identities,
                    TextIdentity(
                        identity.category,
                        identity.object_id,
                        identity.level,
                        "编辑器描述",
                    ),
                    TextIdentity(
                        identity.category,
                        identity.object_id,
                        "",
                        "编辑器描述",
                    ),
                )
            if value.strip() not in _PLACEHOLDERS and not any(
                value in compatible_values[candidate] for candidate in identities
            ):
                level = identity.level or "无等级"
                missing.append(
                    f"{digest[:8]}:{identity.category}:{identity.object_id}:"
                    f"{level}:{identity.role}"
                )
    return tuple(missing)


def legacy_report_value(value: str) -> str:
    """Reproduce the legacy TSV writer's newline and tab serialization."""
    return (
        value.replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\t", " ")
        .replace("\n", "\\n")
    )


def legacy_text_report_value(value: str) -> str:
    """Also reproduce whitespace trimming by the legacy anonymous parser."""
    return legacy_report_value(value.strip())


def _table_from_rows(rows: tuple[tuple[str, ...], ...]) -> TsvTable:
    assert rows
    header = rows[0]
    assert all(len(row) == len(header) for row in rows[1:])
    return TsvTable(header, rows[1:])
