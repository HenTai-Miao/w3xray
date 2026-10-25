"""Scalar and complete Lua value lists, including unknown-length tails."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from .save_call_context import extract_call_args
from .script_lexing import script_views


@dataclass(frozen=True, slots=True)
class StaticValue:
    value: str | None
    kind: str = "unknown"
    diagnostic: str = ""
    proof: int = -1


NIL_VALUE = StaticValue("nil", "nil")


@dataclass(frozen=True, slots=True)
class StaticValues:
    values: tuple[StaticValue, ...] = ()
    tail: StaticValue | None = None
    variable_width: bool = False

    def at(self, index: int) -> StaticValue:
        return (
            self.values[index] if index < len(self.values) else self.tail or NIL_VALUE
        )

    def scalar(self) -> StaticValues:
        return StaticValues((self.at(0),))


def unknown_values(note: str, *, multi: bool) -> StaticValues:
    value = StaticValue(None, diagnostic=note)
    return StaticValues(tail=value) if multi else StaticValues((value,))


@lru_cache(maxsize=8)
def split_value_expressions(text: str, *, lua: bool | None) -> tuple[str, ...] | None:
    if not text.strip():
        return ()
    wrapped = "(" + text + ")"
    return extract_call_args(script_views(wrapped, lua=lua), 1) or None


def flatten_values(parts: tuple[StaticValues, ...]) -> StaticValues:
    values = tuple(value for part in parts for value in part.values)
    tail = parts[-1].tail if parts else None
    return StaticValues(values, tail, any(part.variable_width for part in parts))
