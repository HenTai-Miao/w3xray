"""Shared full-field CSV reads without leaking process-global parser settings."""

from __future__ import annotations

import csv
import sys
from threading import RLock
from types import TracebackType


_FIELD_LIMIT_LOCK = RLock()


class _FullCsvFields:
    def __init__(self) -> None:
        self._previous: int = 0

    def __enter__(self) -> None:
        _FIELD_LIMIT_LOCK.acquire()
        try:
            self._previous = csv.field_size_limit()
            csv.field_size_limit(sys.maxsize)
        except BaseException:
            _FIELD_LIMIT_LOCK.release()
            raise

    def __exit__(
        self,
        _error_type: type[BaseException] | None,
        _error: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        try:
            csv.field_size_limit(self._previous)
        finally:
            _FIELD_LIMIT_LOCK.release()


def full_csv_fields() -> _FullCsvFields:
    """Serialize temporary field-limit changes, including frozen exception exits."""
    return _FullCsvFields()
