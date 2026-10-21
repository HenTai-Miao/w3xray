"""Immutable object-candidate evidence models shared by collection channels."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class ObjectSourceKind(IntEnum):
    BASE = 10
    TEXT_ANONYMOUS = 15
    SLK = 20
    TEXT_FUNC = 30
    BINARY = 40
    TEXT_STRINGS = 50


@dataclass(frozen=True, slots=True)
class ObjectFieldValue:
    key: str
    label: str
    value: str
    source: str
    source_kind: ObjectSourceKind
    value_source: str = ""
    value_type: str = ""
    raw_value: str | None = None


@dataclass(frozen=True, slots=True)
class ObjectCandidate:
    category: str
    obj_id: str
    base_id: str
    is_custom: bool
    ext: str
    fields: tuple[ObjectFieldValue, ...]
    refs: tuple[tuple[str, tuple[str, ...]], ...]
