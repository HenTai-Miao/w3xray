"""Structural read contract shared by MPQ and verified plaintext overlays."""

from __future__ import annotations

import mmap
from collections.abc import Iterable
from typing import Protocol, runtime_checkable


class MapArchiveReader(Protocol):
    path: str
    _data: bytes | mmap.mmap

    def has_file(self, name: str) -> bool: ...

    def read_file(self, name: str) -> bytes: ...

    def list_files(self) -> list[str]: ...

    def close(self) -> None: ...


class TextObjectBlock(Protocol):
    """Block metadata needed to bound anonymous text-object reads."""

    file_size: int


@runtime_checkable
class AnonymousTextObjectArchive(Protocol):
    """Optional block-level capability used for anonymous text-object recovery."""

    def iter_blocks(self) -> Iterable[tuple[int, TextObjectBlock]]: ...

    def peek_block(self, block: TextObjectBlock, n: int = 64) -> bytes: ...

    def read_block_anon(self, block: TextObjectBlock) -> bytes | None: ...
