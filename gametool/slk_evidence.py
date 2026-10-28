"""Lossless SLK evidence with a conservative named-table projection."""

from __future__ import annotations

from .slk_evidence_models import (
    SlkCell,
    SlkColumn,
    SlkDiagnostic,
    SlkEvidence,
    SlkObjectRow,
    SlkRow,
)
from .slk_evidence_records import read_slk_records


__all__ = ("SlkEvidence", "parse_slk_evidence")


def parse_slk_evidence(text: str, *, raw_bytes: bytes | None = None) -> SlkEvidence:
    """Retain every record and cell; project only unambiguous declared fields.

    Repeated identical cells retain every source location. Conflicting cells,
    columns and object fields remain diagnostics and opaque evidence, while
    independent fields and rows survive. Absence is distinct from ``K\"\"``.
    """
    records, cells, diagnostics = read_slk_records(text)
    positions: dict[tuple[int, int], list[int]] = {}
    physical_rows: dict[int, list[int]] = {}
    opaque: set[int] = set()
    for index, cell in enumerate(cells):
        if cell.y is not None and cell.y > 1:
            physical_rows.setdefault(cell.y, []).append(index)
        if cell.x is None or cell.y is None:
            opaque.add(index)
            continue
        positions.setdefault((cell.y, cell.x), []).append(index)
    if opaque:
        diagnostics.append(
            SlkDiagnostic(
                "unbound_cell",
                "cell has no valid unambiguous cursor; source value remains opaque",
                cell_indexes=tuple(sorted(opaque)),
                conflict=True,
            )
        )
    resolved: dict[tuple[int, int], str] = {}
    for position, indexes in positions.items():
        value = _confirmed(cells, indexes)
        if value is not None:
            resolved[position] = value
        else:
            opaque.update(indexes)
        if len(indexes) > 1:
            diagnostics.append(
                SlkDiagnostic(
                    "duplicate_cell",
                    "conflicting SLK cell values"
                    if value is None
                    else "repeated identical SLK cell",
                    cell_indexes=tuple(indexes),
                    conflict=value is None,
                )
            )
    columns = _columns(positions, resolved, cells, diagnostics)
    names = {column.number: column.name for column in columns}
    candidates = {column.number: column.candidate_names for column in columns}
    opaque.update(
        index
        for (_y, x), indexes in positions.items()
        if names.get(x) is None
        for index in indexes
    )
    key_header = names.get(1)
    if not key_header:
        diagnostics.append(
            SlkDiagnostic(
                "missing_key_header",
                "first-column row-key header is absent or ambiguous",
                cell_indexes=tuple(positions.get((1, 1), ())),
                conflict=True,
            )
        )
    rows: list[SlkRow] = []
    keyed_rows: dict[str, list[int]] = {}
    fields: dict[tuple[str, str], list[int]] = {}
    blocked: set[tuple[str, str]] = set()
    for y, indexes in physical_rows.items():
        key = resolved.get((y, 1)) if key_header else None
        key = key if key else None
        rows.append(SlkRow(y, key, tuple(indexes)))
        if key is None:
            opaque.update(indexes)
            diagnostics.append(
                SlkDiagnostic(
                    "missing_row_key",
                    "row has no confirmed key under a unique declared header",
                    cell_indexes=tuple(indexes),
                    conflict=True,
                )
            )
            continue
        keyed_rows.setdefault(key, []).append(y)
        for index in indexes:
            cell = cells[index]
            if cell.x == 1:
                continue
            name = names.get(cell.x) if cell.x is not None else None
            if name is None:
                opaque.add(index)
                for candidate in (
                    candidates.get(cell.x, ()) if cell.x is not None else ()
                ):
                    blocked.add((key, candidate))
                continue
            fields.setdefault((key, name), []).append(index)
    projected: dict[str, list[tuple[str, str]]] = {key: [] for key in keyed_rows}
    for identity, indexes in fields.items():
        key, name = identity
        value = _confirmed(cells, indexes)
        if value is None or identity in blocked:
            blocked.add(identity)
            opaque.update(indexes)
            if len({cells[index].y for index in indexes}) > 1:
                diagnostics.append(
                    SlkDiagnostic(
                        "conflicting_object_field",
                        f"duplicate object rows disagree for {key!r}/{name!r}",
                        cell_indexes=tuple(indexes),
                        conflict=True,
                    )
                )
        else:
            projected[key].append((name, value))
    for key, row_numbers in keyed_rows.items():
        if len(row_numbers) > 1:
            diagnostics.append(
                SlkDiagnostic(
                    "duplicate_object_id",
                    f"object key {key!r} occurs in multiple physical rows",
                    cell_indexes=tuple(
                        index for y in row_numbers for index in physical_rows[y]
                    ),
                )
            )
    return SlkEvidence(
        text,
        raw_bytes,
        records,
        cells,
        columns,
        tuple(rows),
        tuple(
            SlkObjectRow(
                key,
                tuple(values),
                tuple(keyed_rows[key]),
                tuple(
                    (name, cells[fields[(key, name)][0]].value_kind)
                    for name, _value in values
                ),
            )
            for key, values in projected.items()
        ),
        tuple(sorted(opaque)),
        tuple(diagnostics),
        frozenset(blocked),
        max((cell.x for cell in cells if cell.x is not None), default=0),
        max((cell.y for cell in cells if cell.y is not None), default=0),
    )


def _confirmed(cells: tuple[SlkCell, ...], indexes: list[int]) -> str | None:
    values = {(cells[index].value_kind, cells[index].value) for index in indexes}
    if len(values) != 1 or not all(cells[index].valid for index in indexes):
        return None
    return cells[indexes[0]].value


def _columns(
    positions: dict[tuple[int, int], list[int]],
    resolved: dict[tuple[int, int], str],
    cells: tuple[SlkCell, ...],
    diagnostics: list[SlkDiagnostic],
) -> tuple[SlkColumn, ...]:
    headers: dict[str, list[int]] = {}
    actual_columns: dict[int, list[int]] = {}
    for (_y, x), indexes in positions.items():
        actual_columns.setdefault(x, []).extend(indexes)
    for x in actual_columns:
        name = resolved.get((1, x))
        if name:
            headers.setdefault(name, []).append(x)
    ambiguous: set[int] = set()
    for name, numbers in headers.items():
        if len(numbers) > 1:
            ambiguous.update(numbers)
            diagnostics.append(
                SlkDiagnostic(
                    "duplicate_header",
                    f"column name {name!r} is declared at multiple positions",
                    cell_indexes=tuple(
                        index for x in numbers for index in actual_columns[x]
                    ),
                    conflict=True,
                )
            )
    result: list[SlkColumn] = []
    for x, indexes in actual_columns.items():
        header_indexes = tuple(positions.get((1, x), ()))
        name = resolved.get((1, x))
        candidates = tuple(
            dict.fromkeys(
                value
                for index in header_indexes
                for value in (cells[index].value,)
                if value
            )
        )
        if not name:
            diagnostics.append(
                SlkDiagnostic(
                    "unnamed_column",
                    "column has no confirmed nonempty header; cells remain opaque",
                    cell_indexes=tuple(indexes),
                    conflict=True,
                )
            )
        result.append(
            SlkColumn(
                x,
                name if name and x not in ambiguous else None,
                candidates,
                header_indexes,
            )
        )
    return tuple(result)
