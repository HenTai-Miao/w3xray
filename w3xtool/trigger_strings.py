"""Helpers for parsing TriggerStrings.txt duplicate-key records."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator
import csv
from io import StringIO


def parse_trigger_string_sections(text: str) -> dict[str, dict[str, tuple[str, ...]]]:
    """Parse TriggerStrings sections while preserving repeated keys in order."""
    sections: dict[str, dict[str, tuple[str, ...]]] = {}
    current = ""
    grouped: dict[str, list[str]] = defaultdict(list)
    for section, key, value in _iter_lines(text):
        if section != current:
            if current:
                sections[current] = {name: tuple(values) for name, values in grouped.items()}
            current = section
            grouped = defaultdict(list)
        grouped[key].append(value)
    if current:
        sections[current] = {name: tuple(values) for name, values in grouped.items()}
    return sections


def build_display_strings(records: tuple[str, ...]) -> tuple[str | None, str | None]:
    """Return localized display name and positional template for one function."""
    if not records:
        return None, None
    display_name = records[0] or None
    template = _build_template(records[1]) if len(records) > 1 else None
    return display_name, template


def _build_template(record: str) -> str | None:
    fields = tuple(_parse_csv_fields(record))
    if not fields:
        return None
    parts: list[str] = []
    parameter_index = 0
    for field in fields:
        if field.startswith("~"):
            parameter_index += 1
            parts.append(f"%{parameter_index}")
            continue
        parts.append(field)
    return "".join(parts)


def _iter_lines(text: str) -> Iterator[tuple[str, str, str]]:
    current = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("//", ";", "#")):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1].strip()
            continue
        if "=" not in line or not current:
            continue
        key, value = line.split("=", 1)
        yield current, key.strip(), value.strip()


def _parse_csv_fields(value: str) -> tuple[str, ...]:
    return tuple(
        field
        for field in next(csv.reader(StringIO(value), skipinitialspace=False))
    )
