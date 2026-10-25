"""Unambiguous coordinate selection shared by GUI query entry points."""

from __future__ import annotations

from collections.abc import Iterable
import json
import math
import re

from .static_numbers import format_number


_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_SELECTED = re.compile(r'"(?:selected|selected_unit)"\s*:\s*')
_TEMPLATE = re.compile(rf"\bnear\s+({_NUMBER})\s+({_NUMBER})(?![\w.])")
_POSITION = re.compile(rf"@\s*\(\s*({_NUMBER})\s*,\s*({_NUMBER})\s*\)")
_X = re.compile(rf'"x"\s*:\s*({_NUMBER})(?=\s*[,}}]|\s*$)')
_Y = re.compile(rf'"y"\s*:\s*({_NUMBER})(?=\s*[,}}]|\s*$)')
_RADIUS = re.compile(rf'(?:"radius"\s*:\s*|半径\s*)({_NUMBER})(?![\w.])')


def _point(payload: object) -> tuple[str, str] | None:
    if not isinstance(payload, dict):
        return None
    x, y = payload.get("x"), payload.get("y")
    if (
        isinstance(x, bool)
        or isinstance(y, bool)
        or not isinstance(x, (float, int))
        or not isinstance(y, (float, int))
    ):
        return None
    return _unique(((format_number(x), format_number(y)),))


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
    leftover = re.sub(_NUMBER, "", text)
    if leftover.strip(" \t\r\n,;()[]"):
        return []
    return re.findall(_NUMBER, text)


def coordinates_from_text(text: str) -> tuple[str, str] | None:
    """Prefer selected JSON, explicit templates and annotated coordinate pairs.

    Nested inventory objects are decoded structurally. Multiple different points
    are refused; object IDs, owners and group counts cannot become coordinates.
    """
    decoder = json.JSONDecoder()
    selected = tuple(_SELECTED.finditer(text))
    if selected:
        pairs = []
        for match in selected:
            try:
                payload, _ = decoder.raw_decode(text, match.end())
            except ValueError:
                return None
            pair = _point(payload)
            if pair is None:
                return None
            pairs.append(pair)
        return _unique(pairs)
    start = text.find("{")
    if start >= 0:
        try:
            payload, _ = decoder.raw_decode(text, start)
        except ValueError:
            pass
        else:
            return _point(payload)
    templates = _TEMPLATE.findall(text)
    if templates:
        return _unique(templates)
    positions = _POSITION.findall(text)
    if positions:
        return _unique(positions)
    xs, ys = _X.findall(text), _Y.findall(text)
    if xs or ys:
        return _unique(zip(xs, ys, strict=True)) if len(xs) == len(ys) else None
    numbers = _plain_numbers(text)
    return _unique(((numbers[0], numbers[1]),)) if len(numbers) in (2, 3) else None


def radius_from_text(text: str) -> str | None:
    values = _RADIUS.findall(text)
    if not values:
        numbers = _plain_numbers(text)
        values = numbers[2:] if len(numbers) == 3 else []
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
