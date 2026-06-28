"""Preplaced widget checks against W3E terrain bounds."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from .terrain import TerrainBounds, TerrainInfo, terrain_info_from_map_path

if TYPE_CHECKING:
    from .api import MapData

WidgetKind = Literal["单位", "装饰物"]


@dataclass(frozen=True, slots=True)
class BoundsIssue:
    kind: WidgetKind
    type_id: str
    x: float
    y: float


@dataclass(frozen=True, slots=True)
class SceneBoundsReport:
    bounds: TerrainBounds
    unit_count: int
    doodad_count: int
    issues: tuple[BoundsIssue, ...]

    @property
    def unit_issue_count(self) -> int:
        return sum(1 for issue in self.issues if issue.kind == "单位")

    @property
    def doodad_issue_count(self) -> int:
        return sum(1 for issue in self.issues if issue.kind == "装饰物")


def build_scene_bounds_report(
    md: "MapData",
    terrain_info: TerrainInfo | None = None,
) -> SceneBoundsReport | None:
    """Check preplaced units and doodads against terrain coordinate bounds."""
    info = terrain_info if terrain_info is not None else terrain_info_from_map_path(md.path)
    if info is None or info.bounds is None:
        return None
    issues = []
    for unit in md.units:
        if not _inside_bounds(unit.x, unit.y, info.bounds):
            issues.append(BoundsIssue("单位", unit.type_id, unit.x, unit.y))
    for doodad in md.doodads:
        if not _inside_bounds(doodad.x, doodad.y, info.bounds):
            issues.append(BoundsIssue("装饰物", doodad.type_id, doodad.x, doodad.y))
    return SceneBoundsReport(
        bounds=info.bounds,
        unit_count=len(md.units),
        doodad_count=len(md.doodads),
        issues=tuple(issues),
    )


def _inside_bounds(x: float, y: float, bounds: TerrainBounds) -> bool:
    return bounds.left <= x <= bounds.right and bounds.bottom <= y <= bounds.top
