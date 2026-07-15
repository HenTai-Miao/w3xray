"""Resolve and retain values while collecting object candidates."""

from __future__ import annotations

from collections.abc import Mapping
from typing import assert_never

from .base_names import BASE_NAMES
from .object_text_roles import classify_text_field
from .textobj import _sub_westring
from .wts import resolve


def resolved_source_value(value: int | float | str, wts: Mapping[int, str]) -> str:
    """Resolve a WTS container while retaining the original WESTRING token."""
    resolved = resolve(value, wts)
    match resolved:
        case float() as number:
            formatted = str(int(number)) if number.is_integer() else f"{number:.9g}"
        case int() as number:
            formatted = str(number)
        case str() as text:
            formatted = text
        case unreachable:
            assert_never(unreachable)
    return formatted


def resolved_value(value: int | float | str, wts: Mapping[int, str]) -> str:
    """Resolve WTS/WESTRING references without shortening numeric precision."""
    return _sub_westring(resolved_source_value(value, wts))


def wts_value_source(
    value: int | float | str,
    wts: Mapping[int, str],
    prefix: str,
) -> str:
    """Return the exact WTS entry location when a token resolves."""
    match value:
        case str() as text:
            if not text.startswith("TRIGSTR_"):
                return ""
            suffix = text.removeprefix("TRIGSTR_")
            if not suffix.isdecimal() or int(suffix) not in wts:
                return ""
            return f"{prefix}.wts#STRING {int(suffix)}"
        case int() | float():
            return ""
        case unreachable:
            assert_never(unreachable)


def retain_field(
    category: str,
    key: str,
    label: str,
    value: str,
    value_type: str = "",
) -> bool:
    """Retain nonempty data and explicitly present empty text fields."""
    return (
        bool(value) or classify_text_field(category, key, label, value_type) is not None
    )


def expand_codes(value: str) -> str:
    """Expand known comma-separated rawcodes for the compatibility view."""
    if "," not in value:
        return value
    parts = tuple(part.strip() for part in value.split(","))
    return ", ".join(
        f"{BASE_NAMES[part]}({part})" if part in BASE_NAMES else part for part in parts
    )
