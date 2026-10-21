"""Result models for contained output writes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SafeWriteStatus(StrEnum):
    WRITTEN = "written"
    UNSAFE = "unsafe"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class SafeWriteResult:
    status: SafeWriteStatus
    path: str
    size: int
    error: str = ""
