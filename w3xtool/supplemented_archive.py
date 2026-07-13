"""Verified static evidence layered over the existing MPQ reader."""

from __future__ import annotations

import hashlib
import mmap
from collections.abc import Iterable, Sequence
from typing import Protocol

from .extraction_ledger import BlockSource
from .mpq_layout import _Block
from .supplemental_evidence import SupplementalEvidence, SupplementalEvidenceError


class SupplementBase(Protocol):
    """MPQ capabilities needed by the static evidence overlay."""

    path: str
    archive_offset: int
    sector_size: int
    @property
    def _data(self) -> bytes | mmap.mmap: ...

    @property
    def block_table(self) -> Sequence[_Block]: ...

    def has_file(self, name: str) -> bool: ...

    def read_file(self, name: str) -> bytes: ...

    def declared_file_size(self, name: str) -> int | None: ...

    def list_files(self) -> list[str]: ...

    def block_index_of(self, name: str) -> int | None: ...

    def iter_blocks(self) -> Iterable[tuple[int, _Block]]: ...

    def read_block_anon(self, block: _Block) -> bytes | None: ...

    def read_block_with_key(self, block_index: int, key: int) -> bytes: ...

    def recover_block_key(self, block: _Block, /) -> int | None: ...

    def peek_block(self, block: _Block, n: int = 64, /) -> bytes: ...

    def close(self) -> None: ...


class SupplementedArchive:
    """Prefer explicit plaintext while retaining MPQ block capabilities."""

    def __init__(
        self,
        source_path: str,
        base: SupplementBase | None,
        evidence: SupplementalEvidence | None,
    ) -> None:
        if base is None and (evidence is None or not evidence.files):
            raise SupplementalEvidenceError(
                "unreadable container has no verified plaintext files",
            )
        self.path = source_path
        self._base = base
        self._evidence = evidence
        self._data: bytes | mmap.mmap = b"" if base is None else base._data
        self.archive_offset = 0 if base is None else base.archive_offset
        self.sector_size = 4096 if base is None else base.sector_size
        self.block_table: Sequence[_Block] = () if base is None else base.block_table
        self._key_payloads = self._validate_keys()
        self.warnings = self._override_warnings()

    @property
    def author_bundle_files(self) -> tuple[str, ...]:
        """Keep the legacy author-file list available to map loading."""
        if self._evidence is None:
            return ()
        return tuple(
            item.name
            for item in self._evidence.files
            if item.source is BlockSource.AUTHOR_PLAINTEXT
        )

    def has_file(self, name: str) -> bool:
        if self._supplemental_file(name) is not None:
            return True
        return self._base is not None and self._base.has_file(name)

    def read_file(self, name: str) -> bytes:
        supplemental = self._supplemental_file(name)
        if supplemental is not None:
            return supplemental.read()
        if self._base is None:
            raise FileNotFoundError(name)
        try:
            return self._base.read_file(name)
        except (KeyError, OSError, ValueError):
            block_index = self._base.block_index_of(name)
            if block_index is None or block_index not in self._key_payloads:
                raise
            return self._key_payloads[block_index]

    def declared_file_size(self, name: str) -> int | None:
        supplemental = self._supplemental_file(name)
        if supplemental is not None:
            return supplemental.size
        if self._base is None:
            return None
        return self._base.declared_file_size(name)

    def list_files(self) -> list[str]:
        names = [] if self._base is None else list(self._base.list_files())
        seen = {_name_key(name) for name in names}
        if self._evidence is None:
            return names
        candidates = tuple(item.name for item in self._evidence.files) + tuple(
            name
            for name in self._evidence.names
            if self._base is not None and self._base.has_file(name)
        )
        for name in candidates:
            key = _name_key(name)
            if key not in seen:
                names.append(name)
                seen.add(key)
        return names

    def block_index_of(self, name: str) -> int | None:
        if self._base is None:
            return None
        return self._base.block_index_of(name)

    def iter_blocks(self) -> Iterable[tuple[int, _Block]]:
        if self._base is not None:
            yield from self._base.iter_blocks()

    def read_block_anon(self, block: _Block) -> bytes | None:
        block_index = _block_index(self.block_table, block)
        if block_index is None:
            return None
        payload, _source = self.read_block_anon_with_source(block_index, block)
        return payload

    def read_block_anon_with_source(
        self,
        block_index: int,
        block: _Block,
    ) -> tuple[bytes | None, BlockSource]:
        """Decode by automatic recovery before using a verified explicit key."""
        if self._base is None:
            return None, BlockSource.RAW_PAYLOAD
        payload = self._base.read_block_anon(block)
        if payload is not None:
            return payload, BlockSource.ARCHIVE_RECOVERED
        keyed = self._key_payloads.get(block_index)
        if keyed is not None:
            return keyed, BlockSource.COMPAT_KEY
        return None, BlockSource.RAW_PAYLOAD

    def read_block_with_key(self, block_index: int, key: int) -> bytes:
        if self._base is None:
            raise KeyError(f"block index out of range: {block_index}")
        return self._base.read_block_with_key(block_index, key)

    def recover_block_key(self, block: _Block) -> int | None:
        if self._base is None:
            return None
        return self._base.recover_block_key(block)

    def peek_block(self, block: _Block, size: int = 64) -> bytes:
        if self._base is None:
            return b""
        return self._base.peek_block(block, size)

    def file_source(self, name: str) -> BlockSource:
        """Report which evidence source will satisfy a named read."""
        supplemental = self._supplemental_file(name)
        if supplemental is not None:
            return supplemental.source
        if self._base is not None:
            block_index = self._base.block_index_of(name)
            if block_index is not None and block_index in self._key_payloads:
                try:
                    _ = self._base.read_file(name)
                except (KeyError, OSError, ValueError):
                    return BlockSource.COMPAT_KEY
        return BlockSource.ARCHIVE_NAMED

    def close(self) -> None:
        if self._base is not None:
            self._base.close()
        self._data = b""

    def _supplemental_file(self, name: str):
        if self._evidence is None:
            return None
        return self._evidence.file_for(name)

    def _validate_keys(self) -> dict[int, bytes]:
        if self._evidence is None or not self._evidence.keys:
            return {}
        if self._base is None:
            raise SupplementalEvidenceError("MPQ keys require a readable container")
        payloads: dict[int, bytes] = {}
        for item in self._evidence.keys:
            if item.internal_path is not None and (
                self._base.block_index_of(item.internal_path) != item.block_index
            ):
                raise SupplementalEvidenceError(
                    f"MPQ key path does not match block: {item.internal_path}",
                )
            try:
                payload = self._base.read_block_with_key(item.block_index, item.key)
            except (KeyError, OSError, ValueError) as exc:
                raise SupplementalEvidenceError(
                    f"MPQ key cannot decode block: {item.block_index}",
                ) from exc
            if hashlib.sha256(payload).hexdigest() != item.plaintext_sha256:
                raise SupplementalEvidenceError(
                    f"MPQ key plaintext SHA-256 mismatch: {item.block_index}",
                )
            payloads[item.block_index] = payload
        return payloads

    def _override_warnings(self) -> tuple[str, ...]:
        if self._base is None or self._evidence is None:
            return ()
        for item in self._evidence.files:
            if not self._base.has_file(item.name):
                continue
            try:
                archived = self._base.read_file(item.name)
            except (KeyError, OSError, ValueError):
                continue
            if hashlib.sha256(archived).hexdigest() != item.sha256:
                return ("plaintext_override_conflict",)
        return ()


def _name_key(name: str) -> str:
    return name.replace("\\", "/").casefold()


def _block_index(blocks: Sequence[_Block], selected: _Block) -> int | None:
    return next((index for index, block in enumerate(blocks) if block is selected), None)
