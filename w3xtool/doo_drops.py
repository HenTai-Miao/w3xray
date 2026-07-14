"""Lossless nested dropped-item tables used by DOO placement records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class DropReader(Protocol):
    """Binary reader operations required by a dropped-item table."""

    p: int

    def i32(self) -> int: ...

    def tag(self) -> str: ...


class DropCountError(ValueError):
    """A dropped-item table count is incompatible with the active layout."""

    def __init__(self, kind: str, count: int) -> None:
        self.kind = kind
        self.count = count
        super().__init__(str(self))

    def __str__(self) -> str:
        return f"{self.kind} {self.count} 不合理"


@dataclass(frozen=True, slots=True)
class DropEntry:
    """One item candidate within one random dropped-item set."""

    item_id: str
    chance: int
    group_index: int
    entry_index: int
    source_offset: int


@dataclass(frozen=True, slots=True)
class DropSet:
    """One ordered random dropped-item group from a placement record."""

    group_index: int
    entries: tuple[DropEntry, ...]


def read_drop_sets(reader: DropReader, *, maximum_count: int = 256) -> tuple[DropSet, ...]:
    """Read all nested item groups while retaining indexes and byte offsets."""
    group_count = reader.i32()
    _require_count("掉落集合数", group_count, maximum_count)
    groups: list[DropSet] = []
    for group_index in range(group_count):
        entry_count = reader.i32()
        _require_count("掉落物品数", entry_count, maximum_count)
        entries: list[DropEntry] = []
        for entry_index in range(entry_count):
            source_offset = reader.p
            entries.append(
                DropEntry(
                    item_id=reader.tag(),
                    chance=reader.i32(),
                    group_index=group_index,
                    entry_index=entry_index,
                    source_offset=source_offset,
                ),
            )
        groups.append(DropSet(group_index=group_index, entries=tuple(entries)))
    return tuple(groups)


def flatten_drop_sets(drop_sets: tuple[DropSet, ...]) -> list[tuple[str, int]]:
    """Return the historical flat ``(item_id, chance)`` compatibility view."""
    return [
        (entry.item_id, entry.chance)
        for group in drop_sets
        for entry in group.entries
    ]


def _require_count(kind: str, count: int, maximum_count: int) -> None:
    if count < 0 or count > maximum_count:
        raise DropCountError(kind, count)
