"""Complete containing-region records, keeping context bounds and source provenance."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypedDict

from .script_rectangle_analysis import analyze_script_rectangles
from .script_sources import AnalysisScriptSource


class NearRegion(TypedDict):
    name: str
    source: str
    language: str
    line: int
    offset: int
    end_line: int
    end_offset: int
    bounds: tuple[float, float, float, float]
    source_bounds: tuple[float, float, float, float]
    expression: str
    evidence: tuple[str, ...]


def containing_regions(
    contexts: Sequence[AnalysisScriptSource], x: float, y: float
) -> tuple[NearRegion, ...]:
    """Keep source order and every distinct assignment/context, including same names."""
    regions: list[NearRegion] = []
    for source, text, lua in contexts:
        for row in analyze_script_rectangles(text, lua=lua).rectangles:
            left, bottom, right, top = row.bounds
            bounds = (
                min(left, right),
                min(bottom, top),
                max(left, right),
                max(bottom, top),
            )
            if bounds[0] <= x <= bounds[2] and bounds[1] <= y <= bounds[3]:
                regions.append(
                    NearRegion(
                        name=row.name,
                        source=source,
                        language="Lua"
                        if lua is True
                        else "JASS"
                        if lua is False
                        else "unknown",
                        line=row.line,
                        offset=row.offset,
                        end_line=row.line + row.expression.count("\n"),
                        end_offset=row.offset + len(row.expression),
                        bounds=bounds,
                        source_bounds=row.bounds,
                        expression=row.expression,
                        evidence=row.evidence,
                    )
                )
    return tuple(regions)
