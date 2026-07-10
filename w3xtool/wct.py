"""Parse readable custom-script blocks from binary ``war3map.wct`` data."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from .war3_encoding import decode_warcraft_string

_CLASSIC_VERSION: Final = 1
_REFORGED_MARKER: Final = 0x80000004


class WctDiagnostic(StrEnum):
    """Recoverable reason a WCT result is incomplete or unsupported."""

    TRUNCATED = "truncated"
    UNSUPPORTED_VERSION = "unsupported_version"


@dataclass  # noqa: MUTABLE_OK  # noqa: SLOTS_OK - preserve the legacy mutable result contract.
class WctScript:
    """Mutable legacy WCT result with an optional partial-parse diagnostic."""

    custom_comment: str = ""
    custom_code: str = ""
    triggers: list[str] = field(default_factory=list)
    diagnostic: WctDiagnostic | None = None


class _TruncatedWct(Exception):
    """Internal control flow for a read beyond confirmed WCT bytes."""


@dataclass(slots=True)  # noqa: MUTABLE_OK - this object is an explicit byte cursor.
class _Reader:
    """Mutable cursor that rejects unterminated and out-of-bounds fields."""

    data: bytes
    offset: int = 0

    @property
    def at_end(self) -> bool:
        return self.offset == len(self.data)

    def u32(self) -> int:
        return int.from_bytes(self.raw(4), "little", signed=False)

    def i32(self) -> int:
        return int.from_bytes(self.raw(4), "little", signed=True)

    def cstr(self) -> str:
        end = self.data.find(b"\x00", self.offset)
        if end < 0:
            raise _TruncatedWct
        value = decode_warcraft_string(self.data[self.offset:end])
        self.offset = end + 1
        return value

    def raw(self, size: int) -> bytes:
        end = self.offset + size
        if size < 0 or end > len(self.data):
            raise _TruncatedWct
        value = self.data[self.offset:end]
        self.offset = end
        return value


def parse_wct(data: bytes) -> WctScript:
    """Return every confirmed WCT block and diagnose unsupported/truncated tails."""
    reader = _Reader(data)
    try:
        version = reader.u32()
    except _TruncatedWct:
        return WctScript(diagnostic=WctDiagnostic.TRUNCATED)

    reforged = version == _REFORGED_MARKER
    if reforged:
        try:
            version = reader.u32()
        except _TruncatedWct:
            return WctScript(diagnostic=WctDiagnostic.TRUNCATED)
    if version != _CLASSIC_VERSION:
        return WctScript(diagnostic=WctDiagnostic.UNSUPPORTED_VERSION)

    try:
        comment = reader.cstr()
    except _TruncatedWct:
        return WctScript(diagnostic=WctDiagnostic.TRUNCATED)
    try:
        custom_code = _read_global_code(reader)
    except _TruncatedWct:
        return WctScript(
            custom_comment=comment,
            diagnostic=WctDiagnostic.TRUNCATED,
        )

    try:
        count = None if reforged else reader.i32()
        if count is not None and count < 0:
            raise _TruncatedWct
    except _TruncatedWct:
        return WctScript(
            custom_comment=comment,
            custom_code=custom_code,
            diagnostic=WctDiagnostic.TRUNCATED,
        )

    triggers: list[str] = []
    try:
        if count is None:
            while not reader.at_end:
                triggers.append(_read_trigger(reader))
        else:
            for _index in range(count):
                triggers.append(_read_trigger(reader))
    except _TruncatedWct:
        return WctScript(
            custom_comment=comment,
            custom_code=custom_code,
            triggers=triggers,
            diagnostic=WctDiagnostic.TRUNCATED,
        )
    return WctScript(comment, custom_code, triggers)


def _read_global_code(reader: _Reader) -> str:
    size = reader.i32()
    if size == 0:
        return ""
    if size < 0:
        raise _TruncatedWct
    return reader.cstr()


def _read_trigger(reader: _Reader) -> str:
    size = reader.u32()
    if size == 0:
        return ""
    return _decode_sized_cstr(reader.raw(size))


def _decode_sized_cstr(raw: bytes) -> str:
    if not raw or raw[-1] != 0:
        raise _TruncatedWct
    return decode_warcraft_string(raw[:-1])
