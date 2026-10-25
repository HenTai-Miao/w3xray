"""Static unit, item and destructable coordinates shared by spatial queries."""

from __future__ import annotations

from .script_placement_analysis import analyze_script_placements
from .script_rectangle_analysis import analyze_script_rectangles


def script_placements(
    script: str, *, lua: bool | None = False
) -> list[tuple[str, float, float, str]]:
    """Keep every confirmed source-call/point pair, including helper contexts."""
    return [row.row() for row in analyze_script_placements(script, lua=lua).placements]


def script_rectangles(
    script: str, *, lua: bool | None = False
) -> list[tuple[str, float, float, float, float]]:
    """Keep complete getter/parameter bounds; uncertain handles stay diagnostic."""
    return [row.row() for row in analyze_script_rectangles(script, lua=lua).rectangles]
