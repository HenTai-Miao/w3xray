"""Exact finite object-field numbers, without binary float or integer coercion."""

from decimal import Decimal, DecimalException, localcontext
import re

_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")


def numeric_text(value: str) -> str:
    # Table readers have already removed exactly one declared TSV envelope.
    # An ordinary quote is literal source evidence, not a numeric escape.
    return value.strip()


def decimal_value(value: str) -> Decimal | None:
    raw = numeric_text(value)
    if _NUMBER.fullmatch(raw) is None:
        return None
    try:
        with localcontext():
            result = Decimal(raw)
            return result if result.is_finite() else None
    except DecimalException:
        return None


def decimal_text(value: Decimal) -> str:
    return (
        str(value.to_integral_value())
        if value == value.to_integral_value()
        else str(value)
    )
