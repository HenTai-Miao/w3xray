"""Preplaced widget bounds checks."""

from w3xtool.api import MapData
from w3xtool.doo import Doodad, Unit
from w3xtool.scene_bounds import BoundsIssue, build_scene_bounds_report
from w3xtool.terrain import TerrainBounds, TerrainInfo


def test_build_scene_bounds_report_finds_out_of_bounds_widgets():
    # Given: terrain bounds and preplaced widgets on both sides of the boundary.
    md = MapData(path="x.w3x", name="边界图")
    md.units = [
        Unit(type_id="hfoo", variation=0, x=0.0, y=0.0, z=0.0, angle=0.0),
        Unit(type_id="hbar", variation=0, x=256.0, y=0.0, z=0.0, angle=0.0),
    ]
    md.doodads = [
        Doodad(type_id="LTlt", variation=0, x=-64.0, y=-64.0, z=0.0, angle=0.0),
        Doodad(type_id="LOth", variation=0, x=64.0, y=64.0, z=0.0, angle=0.0),
    ]
    info = TerrainInfo(
        version=11,
        base_tileset="L",
        custom_tilesets=False,
        ground_tiles=(),
        cliff_tiles=(),
        width=2,
        height=2,
        bounds=TerrainBounds(left=-128.0, bottom=-128.0, right=0.0, top=0.0),
    )

    # When: scene bounds are checked.
    report = build_scene_bounds_report(md, info)

    # Then: only the placements outside the terrain range are reported.
    assert report is not None
    assert report.unit_issue_count == 1
    assert report.doodad_issue_count == 1
    assert report.issues == (
        BoundsIssue("单位", "hbar", 256.0, 0.0),
        BoundsIssue("装饰物", "LOth", 64.0, 64.0),
    )
