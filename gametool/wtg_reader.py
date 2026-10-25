"""Binary reader for Warcraft III WTG files."""

from __future__ import annotations

import struct

from .war3_encoding import decode_warcraft_string
from .wtg_diagnostics import WtgReadError


class WtgReader:
    """Little-endian bounded reader with byte offsets for diagnostics."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0

    @property
    def offset(self) -> int:
        return self._pos

    @property
    def remaining(self) -> int:
        return len(self._data) - self._pos

    def raw(self, size: int) -> bytes:
        if size < 0 or self._pos + size > len(self._data):
            raise WtgReadError(self._pos, f"expected {size} bytes")
        value = self._data[self._pos : self._pos + size]
        self._pos += size
        return value

    def i32(self) -> int:
        return struct.unpack("<i", self.raw(4))[0]

    def u32(self) -> int:
        return struct.unpack("<I", self.raw(4))[0]

    def cstr(self) -> str:
        end = self._data.find(b"\x00", self._pos)
        if end < 0:
            raise WtgReadError(self._pos, "missing string terminator")
        raw = self._data[self._pos : end]
        self._pos = end + 1
        return decode_warcraft_string(raw, allow_latin1=True)

    def bounded_count(self, label: str, *, minimum_size: int = 1) -> int:
        """Validate counts against encoded bytes, with no empirical ceiling.

        ``minimum_size=0`` is for descriptive totals rather than an upcoming
        sequence. Iterated records always have a positive minimum size.
        """
        if minimum_size < 0:
            raise ValueError("minimum_size must be nonnegative")
        value = self.i32()
        if value < 0 or (minimum_size and value > self.remaining // minimum_size):
            raise WtgReadError(self._pos - 4, f"invalid {label} count: {value}")
        return value
