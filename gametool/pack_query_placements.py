"""Static unit, item and destructable coordinates shared by spatial queries."""

from __future__ import annotations

import re

from .save_call_context import extract_call_args
from .script_lexing import script_views
from .script_function_graph import script_functions
from .script_placement_analysis import analyze_script_placements
from .static_numbers import static_number

_RECT_ASSIGN_RE = re.compile(r"\b(gg_rct_\w+)\s*=\s*(?P<global>_G\s*\.\s*)?Rect\s*\(")


def script_placements(
    script: str, *, lua: bool | None = False
) -> list[tuple[str, float, float, str]]:
    """Keep every confirmed source-call/point pair, including helper contexts."""
    return [row.row() for row in analyze_script_placements(script, lua=lua).placements]


def script_rectangles(
    script: str, *, lua: bool | None = False
) -> list[tuple[str, float, float, float, float]]:
    """Read static assigned rectangles in either language, ignoring quoted examples."""
    views = script_views(script, lua=lua)
    code_text = views.syntax
    rectangles: list[tuple[str, float, float, float, float]] = []
    for match in _RECT_ASSIGN_RE.finditer(code_text):
        if match.group("global"):
            functions = script_functions(script, lua=lua)
            function = functions.structure.scopes.at(match.start())
            if functions.bound(
                "_G", function.start if function else None, match.start()
            ):
                continue
        arguments = extract_call_args(views, match.end())
        if len(arguments) != 4:
            continue
        left, bottom, right, top = (
            static_number(value, lua=lua is True) for value in arguments
        )
        if (
            left is not None
            and bottom is not None
            and right is not None
            and top is not None
        ):
            rectangles.append((match.group(1), left, bottom, right, top))
    return rectangles
