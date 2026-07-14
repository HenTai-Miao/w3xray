"""Snapshot base-object fields from a selected Warcraft client-data source."""

from __future__ import annotations

from dataclasses import dataclass
import mmap
from typing import Final, final

from .game_data_source import GameDataSource
from .object_candidates import ObjectFieldValue, collect_object_candidates
from .object_materialization import BaseObjectTable, merge_object_candidates

_RACES: Final[tuple[str, ...]] = ("Human", "Orc", "NightElf", "Undead", "Neutral", "Campaign")
_CLIENT_TEXT_NAMES: Final[tuple[str, ...]] = tuple(
    sorted(
        {
            *(f"Units\\{race}Unit{kind}.txt" for race in _RACES for kind in ("Func", "Strings")),
            *(f"Units\\{race}Ability{kind}.txt" for race in (*_RACES, "Common", "Item") for kind in ("Func", "Strings")),
            *(f"Units\\{race}Upgrade{kind}.txt" for race in _RACES for kind in ("Func", "Strings")),
            "Units\\ItemFunc.txt",
            "Units\\ItemStrings.txt",
        },
        key=lambda name: (name.casefold(), name),
    )
)


@dataclass(frozen=True, slots=True)
class ClientBaseObject:
    """Immutable client fields retained after the native source closes."""

    obj_id: str
    category: str
    fields: tuple[tuple[str, str], ...]
    evidence_fields: tuple[ObjectFieldValue, ...] = ()


@dataclass(frozen=True, slots=True)
class ClientObjectSnapshot:
    """Closed-source-safe client objects and text availability."""

    objects: tuple[ClientBaseObject, ...]
    text_available: bool


@final
class _ClientObjectArchive:
    source: GameDataSource
    path: str
    _data: bytes | mmap.mmap

    def __init__(self, source: GameDataSource) -> None:
        self.source = source
        self.path = "client-data"
        self._data = b""

    def has_file(self, name: str) -> bool:
        return self.source.has_file(name)

    def read_file(self, name: str) -> bytes:
        return self.source.read_file(name)

    def list_files(self) -> list[str]:
        return list(_CLIENT_TEXT_NAMES)

    def close(self) -> None:
        """The load-context owner closes the wrapped client source."""


def collect_client_base_objects(source: GameDataSource | None) -> tuple[ClientBaseObject, ...]:
    """Parse bounded object tables without retaining the source handle."""
    return snapshot_client_base_objects(source).objects


def snapshot_client_base_objects(source: GameDataSource | None) -> ClientObjectSnapshot:
    """Snapshot every client text candidate before its source closes."""
    if source is None:
        return ClientObjectSnapshot((), False)
    archive = _ClientObjectArchive(source)
    text_available = any(source.has_file(name) for name in _CLIENT_TEXT_NAMES)
    try:
        candidates = collect_object_candidates(archive, {})
    except (OSError, ValueError):
        return ClientObjectSnapshot((), text_available)
    objects = merge_object_candidates(candidates, {})
    evidence_by_object: dict[tuple[str, str], list[ObjectFieldValue]] = {}
    for candidate in candidates:
        evidence_by_object.setdefault((candidate.category, candidate.obj_id), []).extend(
            candidate.fields,
        )
    snapshot = tuple(
        ClientBaseObject(
            item.obj_id,
            item.category,
            tuple((label, value) for label, value in item.fields if value),
            tuple(
                sorted(
                    evidence_by_object.get((item.category, item.obj_id), ()),
                    key=_evidence_sort_key,
                ),
            ),
        )
        for item in objects
        if len(item.obj_id) == 4 and (item.fields or evidence_by_object.get((item.category, item.obj_id)))
    )
    return ClientObjectSnapshot(snapshot, text_available)


def _evidence_sort_key(field: ObjectFieldValue) -> tuple[str, str, str, int, str]:
    return (
        field.key.casefold(),
        field.source.casefold(),
        field.source,
        int(field.source_kind),
        field.value,
    )


def merge_client_base_objects(
    base_objects: BaseObjectTable,
    client_objects: tuple[ClientBaseObject, ...],
) -> dict[str, tuple[str, tuple[tuple[str, str], ...]]]:
    """Fill missing bundled base fields from the selected client snapshot."""
    merged = {
        code: (category, tuple((str(label), str(value)) for label, value in fields))
        for code, (category, fields) in base_objects.items()
    }
    for item in client_objects:
        existing = merged.get(item.obj_id)
        if existing is None:
            merged[item.obj_id] = (item.category, item.fields)
            continue
        category, fields = existing
        combined = list(fields)
        labels = {label.casefold() for label, _value in combined}
        for label, value in item.fields:
            if label.casefold() not in labels:
                combined.append((label, value))
                labels.add(label.casefold())
        merged[item.obj_id] = (category, tuple(combined))
    return merged
