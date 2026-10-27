"""Exact script string-reference IDs, independent of integer text quotas."""

from decimal import Decimal


def trigstr_reference_id(digits: str) -> int:
    """Normalize decimal digits and leading zeros without changing global limits.

    Callers supply a complete regex-validated decimal digit group. Decimal's
    exact constructor accepts every encoded digit and produces the real WTS
    integer key, including Unicode decimal digits and long leading-zero runs.
    """
    return int(Decimal(digits))
