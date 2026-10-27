"""Complete coordinate evidence shared by guide reports and minimap marks."""

from __future__ import annotations

from .script_sources import analysis_script_sources

from collections.abc import Iterable
from typing import TYPE_CHECKING

from .pack_query_placements import script_placements
from .placement_identity import PlacementObjectIndex

if TYPE_CHECKING:
    from .doo_models import Unit
    from .map_data import MapData

type Point = tuple[float, float]
type PositionGroups = dict[str, tuple[Point, ...]]


def _group(placements: Iterable[tuple[str, float, float]]) -> PositionGroups:
    groups: dict[str, dict[Point, None]] = {}
    for code, x, y in placements:
        if code:
            groups.setdefault(code, {})[(x, y)] = None
    return {code: tuple(points) for code, points in groups.items()}


def script_position_groups(md: MapData, kind: str = "unit") -> PositionGroups:
    """Keep every distinct literal coordinate, without guessing runtime presence."""
    return _group(
        (code, x, y)
        for source, text, lua in analysis_script_sources(md)
        for code, x, y, found_kind in script_placements(text, lua=lua)
        if found_kind == kind
    )


def unit_position_groups(
    md: MapData, extra_units: Iterable[Unit] = (), *, confirmed_only: bool = False
) -> PositionGroups:
    """Merge DOO and script evidence; mirrored coordinates appear once."""

    objects = PlacementObjectIndex(md) if confirmed_only else None

    def placements() -> Iterable[tuple[str, float, float]]:
        for units in (md.units, extra_units):
            for unit in units:
                if (
                    objects is not None
                    and objects.placement(unit.type_id, ("单位", "物品")).category
                    != "单位"
                ):
                    continue
                yield unit.type_id, unit.x, unit.y
        for code, points in script_position_groups(md).items():
            for x, y in points:
                yield code, x, y

    return _group(placements())


def doodad_position_groups(md: MapData) -> PositionGroups:
    """Include preplaced and script-created destructable coordinate evidence."""

    def placements() -> Iterable[tuple[str, float, float]]:
        for doodad in md.doodads:
            yield doodad.type_id, doodad.x, doodad.y
        for code, points in script_position_groups(md, "destructable").items():
            for x, y in points:
                yield code, x, y

    return _group(placements())
