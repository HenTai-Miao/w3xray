"""Byte-bounded W3I reads with exact field offsets and recoverable diagnostics."""

from __future__ import annotations

import math
import struct
from collections.abc import Collection, Mapping
from dataclasses import dataclass

from .war3_encoding import decode_warcraft_string, default_legacy_codecs
from .w3i_models import FieldValue, W3iDiagnostic, W3iDiagnosticCode, W3iField, W3iInfo
from .wts import resolve


class W3iReadError(Exception):
    """The next field cannot be read without inventing bytes or a layout."""


@dataclass(slots=True)  # MUTABLE_OK: byte cursor and diagnostic accumulator.
class W3iReader:
    data: bytes
    info: W3iInfo
    strings: Mapping[int, str]
    position: int = 0

    @property
    def remaining(self) -> int:
        return len(self.data) - self.position

    def problem(
        self,
        code: W3iDiagnosticCode,
        name: str,
        message: str,
        *,
        offset: int | None = None,
    ) -> None:
        self.info.diagnostics.append(
            W3iDiagnostic(
                code, name, self.position if offset is None else offset, message
            )
        )

    def _bytes(self, name: str, size: int) -> bytes:
        if size > self.remaining:
            self.problem(
                W3iDiagnosticCode.TRUNCATED,
                name,
                f"field needs {size} bytes; only {self.remaining} remain",
            )
            raise W3iReadError
        return self.data[self.position : self.position + size]

    def _record(self, name: str, raw: bytes, value: FieldValue) -> None:
        self.info.fields.append(W3iField(name, self.position, value, raw))
        self.position += len(raw)

    def i32(self, name: str) -> int:
        raw = self._bytes(name, 4)
        value = int.from_bytes(raw, "little", signed=True)
        self._record(name, raw, value)
        return value

    def u32(self, name: str) -> int:
        raw = self._bytes(name, 4)
        value = int.from_bytes(raw, "little")
        self._record(name, raw, value)
        return value

    def enum(self, name: str, known: Collection[int]) -> int:
        offset = self.position
        value = self.i32(name)
        if value not in known:
            self.problem(
                W3iDiagnosticCode.UNKNOWN_VALUE,
                name,
                f"unknown encoded value {value}; no fallback selected",
                offset=offset,
            )
        return value

    def flags(self, name: str, known_mask: int) -> int:
        offset = self.position
        value = self.u32(name)
        unknown = value & ~known_mask
        if unknown:
            self.problem(
                W3iDiagnosticCode.UNKNOWN_VALUE,
                name,
                f"unknown flag bits 0x{unknown:08x}; original flags retained",
                offset=offset,
            )
        return value

    def f32(self, name: str) -> float | None:
        raw = self._bytes(name, 4)
        value = float(struct.unpack("<f", raw)[0])
        offset = self.position
        self._record(name, raw, value)
        if not math.isfinite(value):
            self.problem(
                W3iDiagnosticCode.INVALID_VALUE,
                name,
                "non-finite float retained as raw evidence, not a usable value",
                offset=offset,
            )
            return None
        return value

    def floats(self, name: str, count: int) -> tuple[float, ...]:
        raw = self._bytes(name, 4 * count)
        values = tuple(float(value) for value in struct.unpack(f"<{count}f", raw))
        offset = self.position
        self._record(name, raw, values)
        if any(not math.isfinite(value) for value in values):
            self.problem(
                W3iDiagnosticCode.INVALID_VALUE,
                name,
                "non-finite geometry retained as raw evidence, not usable bounds",
                offset=offset,
            )
            return ()
        return values

    def ints(self, name: str, count: int) -> tuple[int, ...]:
        raw = self._bytes(name, 4 * count)
        values = tuple(int(value) for value in struct.unpack(f"<{count}i", raw))
        self._record(name, raw, values)
        return values

    def octets(self, name: str, count: int) -> tuple[int, ...]:
        raw = self._bytes(name, count)
        value = tuple(raw)
        self._record(name, raw, value)
        return value

    def code(self, name: str, count: int = 4) -> str:
        raw = self._bytes(name, count)
        value = raw.decode("latin-1")
        self._record(name, raw, value)
        return value

    def text(self, name: str, *, display: bool = True) -> str:
        end = self.data.find(b"\x00", self.position)
        if end < 0:
            self.problem(W3iDiagnosticCode.TRUNCATED, name, "unterminated W3I string")
            raise W3iReadError
        raw = self.data[self.position : end + 1]
        offset = self.position
        value, lossy = _decode_string(raw[:-1])
        self._record(name, raw, value)
        if lossy:
            self.problem(
                W3iDiagnosticCode.LOSSY_STRING,
                name,
                "no supported codec decodes the complete string strictly; "
                "replacement text is display-only and original bytes are retained",
                offset=offset,
            )
        return str(resolve(value, self.strings)) if display else value

    def count(self, name: str, minimum_entry_bytes: int) -> int:
        offset = self.position
        value = self.i32(name)
        if value < 0 or value > self.remaining // minimum_entry_bytes:
            self.problem(
                W3iDiagnosticCode.INVALID_COUNT,
                name,
                f"count {value} cannot fit {self.remaining} remaining bytes "
                f"at a minimum of {minimum_entry_bytes} bytes per record",
                offset=offset,
            )
            if value < 0:
                raise W3iReadError
        # range() does not allocate from this count. A positive oversized count
        # retains each confirmed prefix record before the bounded read stops it.
        return value


def _decode_string(raw: bytes) -> tuple[str, bool]:
    """Use the shared codec order while distinguishing replacement fallback."""
    try:
        return raw.decode("utf-8"), False
    except UnicodeDecodeError:
        pass
    candidates = default_legacy_codecs()
    for encoding in candidates:
        try:
            return raw.decode(encoding), False
        except LookupError, UnicodeDecodeError:
            continue
    return decode_warcraft_string(raw, legacy_codecs=candidates), True
