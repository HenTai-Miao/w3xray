"""Structural capabilities consumed by archive inventory."""

from __future__ import annotations

import mmap
from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from .extraction_ledger import BlockSource
from .mpq_layout import _Block


@runtime_checkable
class InventoryArchive(Protocol):
    archive_offset: int

    @property
    def path(self) -> str: ...

    @property
    def _data(self) -> bytes | mmap.mmap: ...

    def list_files(self) -> list[str]: ...

    def block_index_of(self, name: str, /) -> int | None: ...

    def read_file(self, name: str, /) -> bytes: ...

    def iter_blocks(self) -> Iterable[tuple[int, _Block]]: ...

    def read_block_anon(self, block: _Block, /) -> bytes | None: ...


@runtime_checkable
class InventoryMetadata(Protocol):
    container_readable: bool
    warnings: tuple[str, ...]


@runtime_checkable
class FileProvenance(Protocol):
    def file_source(self, name: str, /) -> BlockSource: ...


@runtime_checkable
class AnonymousProvenance(Protocol):
    def read_block_anon_with_source(
        self,
        block_index: int,
        block: _Block,
        /,
    ) -> tuple[bytes | None, BlockSource]: ...
