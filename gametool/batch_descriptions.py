"""Build source-aware description audit records for extracted objects."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from .map_data import GameObject
from .textobj import clean_text


class DescriptionState(StrEnum):
    """Completeness and provenance state for one description value."""

    MAP_VALUE = "地图原值"
    CLIENT_FILL = "客户端补全"
    MAP_EXPLICIT_EMPTY = "地图明确清空"
    SOURCE_MISSING = "源数据缺失"


@dataclass(frozen=True, slots=True)
class DescriptionRecord:
    """One raw and readable description row, optionally for one level."""

    category: str
    object_id: str
    base_id: str
    object_name: str
    is_custom: bool
    level: int | None
    raw_tip: str
    readable_tip: str
    tip_source: str
    raw_description: str
    readable_description: str
    description_source: str
    state: DescriptionState


@dataclass(frozen=True, slots=True)
class _FieldSpec:
    tip_keys: tuple[str, ...]
    description_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _SelectedField:
    present: bool
    value: str = ""
    source: str = ""


_CATEGORY_FIELDS: Final[Mapping[str, _FieldSpec]] = {
    "单位": _FieldSpec(("utip",), ("utub",)),
    "物品": _FieldSpec(("utip",), ("utub", "ides")),
    "技能": _FieldSpec(("atp1",), ("aub1",)),
    "科技": _FieldSpec(("gtp1",), ("gub1",)),
    "增益": _FieldSpec(("ftip",), ("fube",)),
}
_FALLBACK_FIELDS: Final = _FieldSpec(("display:tip",), ("display:description",))
_TIP_FALLBACKS: Final = ("display:tip",)
_DESCRIPTION_FALLBACKS: Final = ("display:description",)


def audit_object_descriptions(
    objects: Iterable[GameObject],
) -> tuple[DescriptionRecord, ...]:
    """Return deterministic raw/readable description evidence for every object."""
    records = tuple(record for item in objects for record in _records_for_object(item))
    return tuple(sorted(records, key=_record_sort_key))


def _records_for_object(item: GameObject) -> tuple[DescriptionRecord, ...]:
    spec = _CATEGORY_FIELDS.get(item.category, _FALLBACK_FIELDS)
    fields = {key.casefold(): key for key in item.field_values}
    levels = _field_levels(fields, (*spec.tip_keys, *spec.description_keys))
    selected_levels: tuple[int | None, ...] = levels if levels else (None,)
    records: list[DescriptionRecord] = []
    for level in selected_levels:
        tip = _select_field(item, fields, spec.tip_keys, _TIP_FALLBACKS, level)
        description = _select_field(
            item,
            fields,
            spec.description_keys,
            _DESCRIPTION_FALLBACKS,
            level,
        )
        records.append(
            DescriptionRecord(
                category=item.category,
                object_id=item.obj_id,
                base_id=item.base_id,
                object_name=item.name,
                is_custom=item.is_custom,
                level=level,
                raw_tip=tip.value,
                readable_tip=clean_text(tip.value),
                tip_source=tip.source,
                raw_description=description.value,
                readable_description=clean_text(description.value),
                description_source=description.source,
                state=_description_state(description),
            ),
        )
    return tuple(records)


def _field_levels(fields: Mapping[str, str], keys: tuple[str, ...]) -> tuple[int, ...]:
    levels: set[int] = set()
    for key in keys:
        prefix = f"{key.casefold()}:"
        for normalized in fields:
            if normalized.startswith(prefix):
                suffix = normalized.removeprefix(prefix)
                if suffix.isdecimal():
                    levels.add(int(suffix))
    return tuple(sorted(levels))


def _select_field(
    item: GameObject,
    fields: Mapping[str, str],
    primary: tuple[str, ...],
    fallback: tuple[str, ...],
    level: int | None,
) -> _SelectedField:
    candidates = tuple(f"{key}:{level}" for key in primary) if level is not None else ()
    for candidate in (*candidates, *primary, *fallback):
        actual = fields.get(candidate.casefold())
        if actual is not None:
            return _SelectedField(
                present=True,
                value=item.field_values[actual],
                source=item.field_sources.get(actual, ""),
            )
    return _SelectedField(present=False)


def _description_state(field: _SelectedField) -> DescriptionState:
    if not field.present:
        return DescriptionState.SOURCE_MISSING
    if field.source.casefold().startswith("base:"):
        return DescriptionState.CLIENT_FILL
    if not field.value:
        return DescriptionState.MAP_EXPLICIT_EMPTY
    return DescriptionState.MAP_VALUE


def _record_sort_key(record: DescriptionRecord) -> tuple[str, str, int]:
    level = -1 if record.level is None else record.level
    return record.category.casefold(), record.object_id, level
