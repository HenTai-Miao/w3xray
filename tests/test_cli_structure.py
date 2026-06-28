"""CLI map-structure summary rendering."""

from unittest.mock import patch

from main import iter_cli_summary_lines
from w3xtool.api import MapData
from w3xtool.mapmeta import MapStructureReport, PathingSummary, ShadowSummary


def test_cli_summary_includes_shadow_map_block():
    # Given: a map structure report with a parsed shadow map.
    md = MapData(path="x.w3x", name="阴影图")
    report = MapStructureReport(
        pathing=PathingSummary(width=8, height=9, cells=72),
        shadow=ShadowSummary(width=8, height=9, cells=72, shadowed=18, unshadowed=53, unknown=1),
    )

    # When: CLI summary lines are rendered.
    with patch("w3xtool.mapmeta.map_structure_report_from_map_path", return_value=report):
        lines = list(iter_cli_summary_lines(md))

    # Then: shadow map coverage is visible in the map-structure section.
    assert any("阴影图: 8×9" in line and "阴影格: 18" in line for line in lines)
    assert any("透明格: 53" in line and "未知值: 1" in line for line in lines)
