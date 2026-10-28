"""Read SLK records without replacing delimiters or allocating from coordinates."""

from __future__ import annotations

from decimal import Decimal
from dataclasses import replace
import re

from .slk_evidence_models import SlkCell, SlkDiagnostic, SlkField, SlkRecord


_LINES = re.compile(r"[^\r\n]*(?:\r\n|\r|\n|$)")
_KNOWN_RECORDS = frozenset({"ID", "B", "C", "F", "P", "O", "E", "NN", "NE"})


def read_slk_records(
    text: str,
) -> tuple[tuple[SlkRecord, ...], tuple[SlkCell, ...], list[SlkDiagnostic]]:
    records: list[SlkRecord] = []
    cells: list[SlkCell] = []
    diagnostics: list[SlkDiagnostic] = []
    cur_x: int | None = 1
    cur_y: int | None = 1
    dialect = "modern"
    for line_number, match in enumerate(_LINES.finditer(text), 1):
        raw = match.group()
        if not raw:
            continue
        body = raw.removesuffix("\n").removesuffix("\r")
        prefix = 1 if match.start() == 0 and body.startswith("\ufeff") else 0
        content = body[prefix:]
        if content.startswith("ID;"):
            dialect = "scalc3" if "PSCALC3" in content.split(";")[1:] else "modern"
        fields = _fields(content, match.start() + prefix, dialect)
        kind = fields[0].raw
        index = len(records)
        records.append(
            SlkRecord(line_number, match.start(), match.end(), raw, kind, fields)
        )
        if any(not field.complete for field in fields):
            diagnostics.append(
                SlkDiagnostic("incomplete_quote", "incomplete SLK quote", (index,))
            )
        if kind not in _KNOWN_RECORDS:
            if body:
                diagnostics.append(
                    SlkDiagnostic("opaque_record", "unknown SLK record", (index,))
                )
            continue
        if kind not in {"C", "F", "B"}:
            continue
        if kind == "B":
            for axis in ("X", "Y"):
                _axis(fields, axis, None, index, diagnostics, dimension=True)
            continue
        cur_x = _axis(fields, "X", cur_x, index, diagnostics)
        cur_y = _axis(fields, "Y", cur_y, index, diagnostics)
        if kind != "C":
            continue
        unsupported = tuple(
            field
            for field in fields[1:]
            if field.raw and field.raw[0] not in {"X", "Y", "K"}
        )
        if unsupported:
            diagnostics.append(
                SlkDiagnostic(
                    "opaque_cell_fields",
                    "unsupported cell fields; cached value is not confirmed",
                    (index,),
                )
            )
        has_value = False
        for field_index, field in enumerate(fields[1:], 1):
            if not field.raw.startswith("K"):
                continue
            has_value = True
            value, value_kind = _value(field, dialect)
            if value is None and field.complete:
                diagnostics.append(
                    SlkDiagnostic("invalid_value", "unknown SLK value syntax", (index,))
                )
            cells.append(
                SlkCell(
                    index,
                    field_index,
                    cur_x,
                    cur_y,
                    value,
                    value_kind,
                    value is not None and not unsupported,
                )
            )
        if not has_value:
            for field_index, field in enumerate(fields[1:], 1):
                if field.raw and field.raw[0] not in {"X", "Y", "K"}:
                    cells.append(
                        SlkCell(index, field_index, cur_x, cur_y, None, "opaque", False)
                    )
    nonempty = tuple(i for i, record in enumerate(records) if record.kind)
    if not nonempty or records[nonempty[0]].kind != "ID":
        diagnostics.append(
            SlkDiagnostic("missing_id", "missing SLK ID header", nonempty[:1])
        )
    if not nonempty or records[nonempty[-1]].kind != "E":
        diagnostics.append(
            SlkDiagnostic("missing_terminator", "missing SLK terminator", nonempty[-1:])
        )
    by_record: dict[int, list[int]] = {}
    for index, cell in enumerate(cells):
        by_record.setdefault(cell.record_index, []).append(index)
    diagnostics = [
        replace(
            issue,
            cell_indexes=tuple(
                index
                for record_index in issue.record_indexes
                for index in by_record.get(record_index, ())
            ),
        )
        for issue in diagnostics
    ]
    return tuple(records), tuple(cells), diagnostics


def _fields(line: str, offset: int, dialect: str) -> tuple[SlkField, ...]:
    fields: list[SlkField] = []
    start = 0
    while start <= len(line):
        opening = start if line[start : start + 1] == '"' else start + 1
        if line[opening : opening + 1] == '"':
            end, complete = _quoted_end(line, opening, dialect)
        else:
            end = start
            while end < len(line):
                if line[end] == ";":
                    if (
                        dialect == "modern"
                        and line[start : start + 1] in {"E", "M"}
                        and line[end : end + 2] == ";;"
                    ):
                        end += 2
                        continue
                    break
                end += 1
            complete = True
        fields.append(SlkField(line[start:end], offset + start, offset + end, complete))
        if end == len(line):
            break
        start = end + 1
    return tuple(fields)


def _quoted_end(line: str, opening: int, dialect: str) -> tuple[int, bool]:
    """SYLK closes at a quote followed by a field delimiter or record end.

    Modern OOO32/OTHER producers keep embedded quotes literally and escape
    semicolons. Only declared SCALC3 doubles embedded quotes instead.
    """
    index = opening + 1
    while index < len(line):
        if line[index] == '"':
            following = line[index + 1 : index + 3]
            if dialect == "scalc3" and following.startswith('"'):
                index += 2
                continue
            if dialect == "modern" and following == ";;":
                index += 3
                continue
            if index + 1 == len(line) or following.startswith(";"):
                return index + 1, True
        index += 1
    return len(line), False


def _axis(
    fields: tuple[SlkField, ...],
    axis: str,
    previous: int | None,
    record_index: int,
    diagnostics: list[SlkDiagnostic],
    *,
    dimension: bool = False,
) -> int | None:
    declared = tuple(field for field in fields[1:] if field.raw.startswith(axis))
    if not declared:
        return previous
    values: set[int] = set()
    valid = True
    for field in declared:
        digits = field.raw[1:]
        if (
            not field.complete
            or not digits
            or not digits.isascii()
            or not digits.isdecimal()
        ):
            valid = False
        else:
            # Decimal -> int uses neither the decimal-string conversion quota
            # nor a mutable global numeric context. Coordinates stay sparse.
            value = int(Decimal(digits))
            if value < 1:
                valid = False
            else:
                values.add(value)
    if not valid:
        diagnostics.append(
            SlkDiagnostic(
                "invalid_dimension" if dimension else "invalid_coordinate",
                f"invalid SLK {'column' if axis == 'X' else 'row'} declaration",
                (record_index,),
                conflict=True,
            )
        )
    if len(declared) > 1:
        diagnostics.append(
            SlkDiagnostic(
                "duplicate_coordinate",
                f"repeated SLK {axis} declarations",
                (record_index,),
                conflict=not valid or len(values) != 1,
            )
        )
    return next(iter(values)) if valid and len(values) == 1 else None


def _value(field: SlkField, dialect: str) -> tuple[str | None, str]:
    raw = field.raw[1:]
    if not field.complete:
        return None, "invalid"
    if not raw.startswith('"'):
        return (None, "invalid") if '"' in raw else (raw, "bare")
    if not raw.endswith('"') or len(raw) < 2:
        return None, "invalid"
    value = raw[1:-1]
    value = (
        value.replace('""', '"') if dialect == "scalc3" else value.replace(";;", ";")
    )
    return value.replace("\x1b :", "\n"), "quoted"
