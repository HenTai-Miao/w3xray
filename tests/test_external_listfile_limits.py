"""Resource-boundary tests for user-provided MPQ listfiles."""

from __future__ import annotations

from types import TracebackType
from typing import Self, override
from unittest.mock import patch

from w3xtool.external_listfile import read_external_listfile


class _RecordingReader:
    def __init__(self, payload: bytes) -> None:
        self.payload: bytes = payload
        self.requested_sizes: list[int] = []

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        self.requested_sizes.append(size)
        return self.payload


class _OversizedReader(_RecordingReader):
    @override
    def read(self, size: int = -1) -> bytes:
        self.requested_sizes.append(size)
        if size <= 0:
            return b"truncated-name.blp"
        return b"x" * (size + 1)


def test_external_listfile_uses_a_bounded_read() -> None:
    # Given: a file boundary that records the requested byte count.
    reader = _RecordingReader(b"war3map.j\n")

    # When: the external listfile is parsed.
    with patch("builtins.open", return_value=reader):
        names = read_external_listfile("virtual-listfile.txt")

    # Then: the parser never requests the entire unbounded stream.
    assert names == ("war3map.j",)
    assert len(reader.requested_sizes) == 1
    assert reader.requested_sizes[0] > 0


def test_external_listfile_rejects_payload_above_the_read_limit() -> None:
    # Given: a file that contains one byte beyond any requested limit.
    reader = _OversizedReader(b"")

    # When: the external listfile is parsed.
    with patch("builtins.open", return_value=reader):
        names = read_external_listfile("oversized-listfile.txt")

    # Then: no truncated prefix is accepted as a complete listfile.
    assert names == ()


def test_external_listfile_rejects_a_line_above_4096_characters() -> None:
    # Given: one path-like line whose length exceeds the parser boundary.
    reader = _RecordingReader((b"x" * 4097) + b"\n")

    # When: the external listfile is parsed.
    with patch("builtins.open", return_value=reader):
        names = read_external_listfile("overlong-line.txt")

    # Then: the oversized line is not retained or partially parsed.
    assert names == ()


def test_external_listfile_rejects_more_than_100000_entries() -> None:
    # Given: a bounded-size file containing too many retained entries.
    reader = _RecordingReader(b"x\n" * 100_001)

    # When: the external listfile is parsed.
    with patch("builtins.open", return_value=reader):
        names = read_external_listfile("too-many-entries.txt")

    # Then: the parser does not retain an unbounded tuple.
    assert names == ()
