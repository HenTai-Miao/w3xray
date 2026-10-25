"""Lossless nested dropped-item tables used by DOO placement records."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class DropReader(Protocol):
    """Binary reader operations required by a dropped-item table."""

    p: int

    @property
    def remaining(self) -> int: ...

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


def read_drop_sets(reader: DropReader, *, tail_bytes: int = 0) -> tuple[DropSet, ...]:
    """Read groups without a heuristic cap, reserving the record's required tail."""
    group_count = read_count(reader, "掉落集合数", 4, tail_bytes=tail_bytes)
    groups: list[DropSet] = []
    for group_index in range(group_count):
        # Later groups need at least their own entry-count headers, even empty ones.
        reserved = tail_bytes + 4 * (group_count - group_index - 1)
        entry_count = read_count(reader, "掉落物品数", 8, tail_bytes=reserved)
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
        (entry.item_id, entry.chance) for group in drop_sets for entry in group.entries
    ]


def read_count(
    reader: DropReader, kind: str, minimum_size: int, *, tail_bytes: int = 0
) -> int:
    """Bound work by available bytes, never by an empirical record count.

    A count may use only bytes beyond the mandatory suffix and must fit even
    when every entry has its shortest legal encoding. Validate before looping,
    so negative or inflated signed counts cannot allocate or consume a tail.
    """
    if minimum_size <= 0 or tail_bytes < 0:
        raise ValueError("Invalid count layout")
    count = reader.i32()
    available = reader.remaining - tail_bytes
    if count < 0 or available < 0 or count > available // minimum_size:
        raise DropCountError(kind, count)
    return count
