"""CLI terrain summary rendering."""

from unittest.mock import patch

from main import iter_cli_summary_lines
from w3xtool.api import MapData
from w3xtool.doo import Doodad, Unit
from w3xtool.terrain import TerrainBounds, TerrainInfo, TerrainPointSummary


def test_cli_summary_includes_terrain_point_statistics():
    # Given: terrain metadata with decoded tilepoint statistics.
    md = MapData(path="x.w3x", name="地形图")
    md.units = [Unit(type_id="hfoo", variation=0, x=256.0, y=0.0, z=0.0, angle=0.0)]
    md.doodads = [Doodad(type_id="LOth", variation=0, x=64.0, y=64.0, z=0.0, angle=0.0)]
    info = TerrainInfo(
        version=11,
        base_tileset="L",
        custom_tilesets=False,
        ground_tiles=("Ldrt",),
        cliff_tiles=(),
        width=2,
        height=2,
        bounds=TerrainBounds(left=-128.0, bottom=-128.0, right=0.0, top=0.0),
        point_summary=TerrainPointSummary(
            cells=4,
            min_height=-1.0,
            max_height=2.0,
            min_water_height=0.0,
            max_water_height=2.0,
            ramp=1,
            blighted=1,
            water=1,
            boundary=1,
            edge=1,
            texture_counts=((0, 3), (1, 1)),
            cliff_texture_counts=((0, 2), (1, 2)),
            cliff_level_counts=((0, 3), (2, 1)),
        ),
    )

    # When: CLI summary lines are rendered.
    with patch("w3xtool.terrain.terrain_info_from_map_path", return_value=info):
        lines = list(iter_cli_summary_lines(md))

    # Then: terrain point statistics are visible.
    assert any("坐标范围" in line and "X -128~0" in line and "Y -128~0" in line for line in lines)
    assert any("高度: -1~2" in line and "水位: 0~2" in line for line in lines)
    assert any("水域: 1" in line and "坡道: 1" in line and "边界: 1" in line for line in lines)
    assert any("边缘: 1" in line for line in lines)
    assert any("地表使用" in line and "Ldrt:3" in line and "#1:1" in line for line in lines)
    assert any("悬崖纹理" in line and "#1:2" in line for line in lines)
    assert any("悬崖层级" in line and "2:1" in line for line in lines)
    assert any("场景边界" in line and "越界单位 1/1" in line for line in lines)
    assert any("越界单位: hfoo" in line for line in lines)
    assert any("越界装饰物: LOth" in line for line in lines)
