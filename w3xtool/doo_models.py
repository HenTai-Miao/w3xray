"""Compatibility placement records produced by Warcraft DOO parsers."""

from __future__ import annotations

from dataclasses import dataclass, field

from .doo_drops import DropSet, flatten_drop_sets


@dataclass(slots=True)  # noqa: RUF012  # noqa: MUTABLE_OK
class Doodad:
    """One mutable legacy doodad view with lossless nested drop evidence."""

    type_id: str
    variation: int
    x: float
    y: float
    z: float
    angle: float
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)
    flags: int = 0
    life: int = 100
    drops: list[tuple[str, int]] = field(default_factory=list)
    serial: int = 0
    drop_sets: tuple[DropSet, ...] = ()
    source_offset: int = 0


@dataclass(slots=True)  # noqa: RUF012  # noqa: MUTABLE_OK
class Unit:
    """One mutable legacy unit view with placement, inventory, and drop data."""

    type_id: str
    variation: int
    x: float
    y: float
    z: float
    angle: float
    player: int = 0
    hp: int = -1
    mana: int = -1
    gold: int = 0
    hero_level: int = 1
    items: list[tuple[int, str]] = field(default_factory=list)
    abilities: list[tuple[str, int, int]] = field(default_factory=list)
    serial: int = 0
    drop_sets: tuple[DropSet, ...] = ()
    source_offset: int = 0

    @property
    def drops(self) -> list[tuple[str, int]]:
        """Return the historical flat dropped-item compatibility view."""
        return flatten_drop_sets(self.drop_sets)
