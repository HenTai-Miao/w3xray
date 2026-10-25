"""Unambiguous coordinate selection shared by GUI query entry points."""

from __future__ import annotations

from collections.abc import Iterable
import math
import re

from .query_coordinate_json import JsonObject, coordinate_json


_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_TEMPLATE = re.compile(
    rf"\bnear\s+({_NUMBER})\s+({_NUMBER})(?![\w.])(?:[ \t]+({_NUMBER})(?![\w.]))?"
)
_POSITION = re.compile(rf"@\s*\(\s*({_NUMBER})\s*,\s*({_NUMBER})\s*\)")
_RADIUS = re.compile(rf'(?:"radius"\s*:\s*|半径\s*)({_NUMBER})(?![\w.])')


def _point(payload: object) -> tuple[str, str] | None:
    if not isinstance(payload, JsonObject):
        return None
    xs, ys = payload.fields.get("x", []), payload.fields.get("y", [])
    if not xs or not ys or any(not isinstance(value, str) for value in (*xs, *ys)):
        return None
    x, y = str(xs[0]), str(ys[0])
    return _unique(
        (*((str(value), y) for value in xs), *((x, str(value)) for value in ys))
    )


def _unique(pairs: Iterable[tuple[str, str]]) -> tuple[str, str] | None:
    points: dict[tuple[float, float], tuple[str, str]] = {}
    for x, y in pairs:
        try:
            point = (float(x), float(y))
        except ValueError, OverflowError:
            return None
        if not all(math.isfinite(value) for value in point):
            return None
        points.setdefault(point, (x, y))
        if len(points) > 1:
            return None
    return next(iter(points.values()), None)


def _plain_numbers(text: str) -> list[str]:
    raw = text.strip()
    if raw.startswith(("(", "[")):
        if not raw.endswith(")" if raw[0] == "(" else "]"):
            return []
        raw = raw[1:-1]
    numbers: list[str] = []
    cursor = 0
    for index, match in enumerate(re.finditer(_NUMBER, raw)):
        separator = raw[cursor : match.start()]
        if separator.strip(" \t\r\n,;") or index and not separator:
            return []
        cursor = match.end()
        numbers.append(match.group())
    if raw[cursor:].strip(" \t\r\n,;"):
        return []
    return numbers


def coordinates_from_text(text: str) -> tuple[str, str] | None:
    """Prefer selected JSON, explicit templates and annotated coordinate pairs.

    Nested inventory objects are decoded structurally. Multiple different points
    are refused; object IDs, owners and group counts cannot become coordinates.
    """
    numbers = _plain_numbers(text)
    if len(numbers) in (2, 3):
        return _unique(((numbers[0], numbers[1]),))
    evidence = coordinate_json(text)
    if evidence.invalid:
        return None
    selected = [
        value
        for root in evidence.objects
        for key in ("selected", "selected_unit")
        for value in root.fields.get(key, ())
    ]
    if selected:
        pairs = []
        for payload in selected:
            pair = _point(payload)
            if pair is None:
                return None
            pairs.append(pair)
        return _unique(pairs)
    pairs = []
    for root in evidence.objects:
        if "x" not in root.fields and "y" not in root.fields:
            continue
        point = _point(root)
        if point is None:
            return None
        pairs.append(point)
    pairs.extend((x, y) for x, y, _radius in _TEMPLATE.findall(evidence.outside))
    pairs.extend(_POSITION.findall(evidence.outside))
    if pairs:
        return _unique(pairs)
    if evidence.present:
        return None
    return None


def radius_from_text(text: str) -> str | None:
    numbers = _plain_numbers(text)
    if len(numbers) == 3:
        return _unique_radius(numbers[2:])
    evidence = coordinate_json(text)
    if evidence.invalid:
        return None
    objects = [*evidence.objects]
    objects.extend(
        value
        for root in evidence.objects
        for key in ("selected", "selected_unit")
        for value in root.fields.get(key, ())
        if isinstance(value, JsonObject)
    )
    raw = [value for root in objects for value in root.fields.get("radius", ())]
    if any(not isinstance(value, str) for value in raw):
        return None
    values = [str(value) for value in raw]
    values.extend(_RADIUS.findall(evidence.outside))
    values.extend(
        radius for _x, _y, radius in _TEMPLATE.findall(evidence.outside) if radius
    )
    return _unique_radius(values)


def _unique_radius(values: list[str]) -> str | None:
    if not values:
        return None
    try:
        radii = {float(value) for value in values}
    except ValueError, OverflowError:
        return None
    return (
        values[0]
        if len(radii) == 1
        and all(math.isfinite(value) and value >= 0 for value in radii)
        else None
    )
