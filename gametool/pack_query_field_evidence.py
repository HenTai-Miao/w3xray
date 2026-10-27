"""Shared immutable field records, source labels and lossless display."""

from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass

from .pack_query_objects import valid_object_code


@dataclass(frozen=True, slots=True)
class ObjectField:
    key: str
    label: str
    value: str
    source: str
    extras: tuple[tuple[str, str], ...] = ()

    def search_fields(self, clean: Callable[[str], str]) -> Iterator[str]:
        yield self.key
        yield self.label
        yield clean(self.value)
        yield self.source
        for label, value in self.extras:
            yield label
            yield clean(value)

    def render_lines(self, indent: str = "    ") -> tuple[str, ...]:
        key = self.key or "（字段键未记录）"
        label = " / " + self.label if self.label and self.label != self.key else ""
        inherited = (
            "（继承字段原文）" if self.key.casefold().startswith("base:") else ""
        )
        return (
            f"{indent}{key}{label}{inherited}: {self.value or '（显式空值）'}  [来源: {self.source or '来源未记录'}]",
            *(
                f"{indent}  {label}: {value or '（显式空值）'}"
                for label, value in self.extras
            ),
        )


def field_record(
    row: tuple[str, ...], header: tuple[str, ...], clean: Callable[[str], str]
) -> ObjectField:
    extras = tuple(
        (header[index] if index < len(header) else f"扩展字段{index + 1}", value)
        for index, value in enumerate(row[7:], 7)
    )
    return ObjectField(row[3], clean(row[4]), row[5], row[6], extras)


@dataclass(frozen=True, slots=True)
class ObjectFields:
    code: str
    names: tuple[str, ...]
    fields: tuple[ObjectField, ...]


def object_field_indexes(
    rows: tuple[tuple[str, ...], ...],
    categories: Iterable[str],
    clean: Callable[[str], str],
) -> dict[str, dict[str, ObjectFields]]:
    """Build qualified field indexes for all requested categories in one pass."""
    requested = frozenset(categories)
    fields: dict[tuple[str, str], dict[ObjectField, None]] = {}
    names: dict[tuple[str, str], dict[str, None]] = {}
    header = rows[0] if rows else ()
    for row in rows[1:]:
        if len(row) < 7 or row[0] not in requested or not valid_object_code(row[1]):
            continue
        identity = (row[0], row[1])
        fields.setdefault(identity, {}).setdefault(
            field_record(row, header, clean), None
        )
        if name := clean(row[2]):
            names.setdefault(identity, {}).setdefault(name, None)
    output: dict[str, dict[str, ObjectFields]] = {}
    for (category, code), records in fields.items():
        output.setdefault(category, {})[code] = ObjectFields(
            code, tuple(names.get((category, code), ())), tuple(records)
        )
    return output


def object_field_index(
    rows: tuple[tuple[str, ...], ...], category: str, clean: Callable[[str], str]
) -> dict[str, ObjectFields]:
    return object_field_indexes(rows, (category,), clean).get(category, {})
