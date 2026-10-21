"""Strict UTF-8 parsing for integrity labels and filesystem paths."""

from __future__ import annotations

from dataclasses import dataclass
from typing import override


@dataclass(frozen=True, slots=True)
class IntegrityUtf8Error(UnicodeError):
    """External integrity text cannot be represented as strict UTF-8."""

    label: str

    @override
    def __str__(self) -> str:
        return f"{self.label} is not UTF-8"


def require_utf8_text(value: str, label: str) -> None:
    """Reject surrogateescape and unpaired-surrogate external text."""
    try:
        _ = value.encode("utf-8", errors="strict")
    except UnicodeError as exc:
        raise IntegrityUtf8Error(label) from exc


__all__ = ("IntegrityUtf8Error", "require_utf8_text")
