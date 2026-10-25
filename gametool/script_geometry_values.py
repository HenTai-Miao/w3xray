"""Finite typed Location/Rect terms; no source bindings or execution."""

from __future__ import annotations

import math

from .script_value_models import StaticValue, StaticValues, split_value_expressions
from .static_numbers import format_number, static_number

GEOMETRY_CONSTRUCTORS = {"Location": ("location", 2), "Rect": ("rect", 4)}
GEOMETRY_READERS = {
    "GetLocationX": ("location", 0),
    "GetLocationY": ("location", 1),
    "GetRectMinX": ("rect", 0),
    "GetRectMinY": ("rect", 1),
    "GetRectMaxX": ("rect", 2),
    "GetRectMaxY": ("rect", 3),
    "GetRectCenterX": ("rect", 4),
    "GetRectCenterY": ("rect", 5),
    "GetRectCenter": ("rect", 6),
}
GEOMETRY_MUTATORS = frozenset(
    {
        "MoveLocation",
        "RemoveLocation",
        "SetRect",
        "SetRectFromLoc",
        "MoveRectTo",
        "MoveRectToLoc",
        "RemoveRect",
    }
)
GEOMETRY_BUILTINS = frozenset(
    (*GEOMETRY_CONSTRUCTORS, *GEOMETRY_READERS, *GEOMETRY_MUTATORS)
)


def geometry_coordinates(value: StaticValue) -> tuple[float, ...] | None:
    if value.kind not in {"location", "rect"} or value.value is None:
        return None
    call = value.value.partition("(")
    spec = GEOMETRY_CONSTRUCTORS.get(call[0])
    if spec is None or not value.value.endswith(")"):
        return None
    parts = split_value_expressions(call[2][:-1], lua=True)
    if parts is None or len(parts) != spec[1]:
        return None
    numbers = tuple(static_number(part, lua=True) for part in parts)
    return (
        tuple(number for number in numbers if number is not None)
        if all(number is not None for number in numbers)
        else None
    )


def computed_geometry(text: str) -> StaticValue | None:
    name = text.partition("(")[0]
    if name not in GEOMETRY_CONSTRUCTORS:
        return None
    result = StaticValue(text, GEOMETRY_CONSTRUCTORS[name][0])
    return result if geometry_coordinates(result) is not None else None


def geometry_constructor(name: str, actual: StaticValues) -> StaticValue:
    kind, count = GEOMETRY_CONSTRUCTORS[name]
    values = actual.values
    if len(values) != count or actual.tail is not None:
        return StaticValue(None, diagnostic=f"{name} 几何参数数量未确定")
    numbers = tuple(
        static_number(value.value, lua=True)
        if value.kind == "number" and value.value is not None
        else None
        for value in values
    )
    if any(number is None for number in numbers):
        notes = "; ".join(
            dict.fromkeys(value.diagnostic for value in values if value.diagnostic)
        )
        return StaticValue(
            None,
            diagnostic=f"{name} 含动态、缺失或非有限坐标"
            + ("; " + notes if notes else ""),
        )
    return StaticValue(
        name
        + "("
        + ",".join(format_number(number) for number in numbers if number is not None)
        + ")",
        kind,
    )


def geometry_center(coordinates: tuple[float, ...]) -> tuple[float, float]:
    def midpoint(left: float, right: float) -> float:
        total = left + right
        return total / 2 if math.isfinite(total) else left / 2 + right / 2

    return midpoint(coordinates[0], coordinates[2]), midpoint(
        coordinates[1], coordinates[3]
    )
