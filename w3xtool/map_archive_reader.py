"""Structural read contract shared by MPQ and verified plaintext overlays."""

from __future__ import annotations

import mmap
from typing import Protocol


class MapArchiveReader(Protocol):
    path: str
    _data: bytes | mmap.mmap

    def has_file(self, name: str) -> bool: ...

    def read_file(self, name: str) -> bytes: ...

    def list_files(self) -> list[str]: ...

    def close(self) -> None: ...
