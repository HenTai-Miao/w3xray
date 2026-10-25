"""Static unit, item and destructable coordinates shared by spatial queries."""

from __future__ import annotations

import re

from .save_call_context import extract_call_args
from .script_lexing import script_views
from .script_object_literals import literal_object_code as _object_code
from .script_tokens import is_lua_function_definition
from .static_numbers import static_number

_CALL_RE = re.compile(
    r"\b(CreateUnit|CreateUnitAtLoc|BlzCreateUnitWithSkin|CreateCorpse|CreateItem|CreateItemLoc|BlzCreateItemWithSkin|CreateDestructable|CreateDestructableZ|CreateDeadDestructable|CreateDeadDestructableZ)\s*\("
)
_RECT_ASSIGN_RE = re.compile(r"\b(gg_rct_\w+)\s*=\s*Rect\s*\(")


def script_placements(
    script: str, *, lua: bool | None = False
) -> list[tuple[str, float, float, str]]:
    """List every literal placement, ignoring comments and runtime expressions.

    Integer object IDs and Lua FourCC calls are equivalent to JASS fourccs.
    No script content is evaluated or executed.
    """
    out: list[tuple[str, float, float, str]] = []
    # The range lexer masks quoted text and Lua long comments/strings while
    # preserving offsets. Arguments come from the original call so FourCC
    # literals are retained without mistaking quoted example calls for code.
    views = script_views(script, lua=lua)
    code_text = views.syntax
    for match in _CALL_RE.finditer(code_text):
        if is_lua_function_definition(code_text, match.start()):
            continue
        args = extract_call_args(views, match.end())
        name = match.group(1)
        kind = (
            "destructable"
            if "Destructable" in name
            else "unit"
            if "Unit" in name or name == "CreateCorpse"
            else "item"
        )
        offset = 1 if kind == "unit" else 0
        location = name in ("CreateUnitAtLoc", "CreateItemLoc")
        if len(args) < offset + (2 if location else 3):
            continue
        code = _object_code(args[offset])
        if location:
            loc = re.fullmatch(r"Location\s*\((.*)\)", args[offset + 1], re.DOTALL)
            coords = (
                extract_call_args("Location(" + loc.group(1) + ")", len("Location("))
                if loc
                else ()
            )
            if len(coords) != 2:
                continue
            x, y = (_coordinate(value, lua=lua) for value in coords)
        else:
            x = _coordinate(args[offset + 1], lua=lua)
            y = _coordinate(args[offset + 2], lua=lua)
        if code and x is not None and y is not None:
            out.append((code, x, y, kind))
    return out


def script_rectangles(
    script: str, *, lua: bool | None = False
) -> list[tuple[str, float, float, float, float]]:
    """Read static assigned rectangles in either language, ignoring quoted examples."""
    views = script_views(script, lua=lua)
    code_text = views.syntax
    rectangles: list[tuple[str, float, float, float, float]] = []
    for match in _RECT_ASSIGN_RE.finditer(code_text):
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


def _coordinate(value: str, *, lua: bool | None = False) -> float | None:
    return static_number(value, lua=lua is True)
