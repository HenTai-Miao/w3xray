"""Binary reader for Warcraft III WTG files."""

from __future__ import annotations

from typing import Final
import struct

from .war3_encoding import decode_warcraft_string
from .wtg_diagnostics import WtgReadError

MAX_COUNT: Final = 100_000


class WtgReader:
    """Little-endian bounded reader with byte offsets for diagnostics."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0

    @property
    def offset(self) -> int:
        return self._pos

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
        raw = self._data[self._pos:end]
        self._pos = end + 1
        return decode_warcraft_string(raw, allow_latin1=True)

    def bounded_count(self, label: str) -> int:
        value = self.i32()
        if value < 0 or value > MAX_COUNT:
            raise WtgReadError(self._pos - 4, f"invalid {label} count: {value}")
        return value
