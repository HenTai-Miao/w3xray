"""Full CASC root inventory export without hiding nameless entries."""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from typing import Final, override

from .casclib_enumeration import CascEntry, CascNameType
from .game_data_inventory import GameDataInventorySource
from .safe_output import write_chunks_safely
from .safe_output_models import SafeWriteStatus


_CHUNK_BYTES: Final = 64 * 1024
_HEADER: Final = (
    "名称\t名称类型\tFileDataID\tCKey\tEKey\t大小\t本地可用\tLocaleFlags\tContentFlags\n"
).encode()


@dataclass(frozen=True, slots=True)
class CascInventorySummary:
    total: int
    resolved_paths: int
    unknown_paths: int
    local_files: int
    was_limited: bool
    output_path: Path


@dataclass(frozen=True, slots=True)
class CascInventoryWriteError(OSError):
    path: Path
    reason: str

    @override
    def __str__(self) -> str:
        return f"cannot write CASC inventory {self.path}: {self.reason}"


@dataclass(slots=True)  # noqa: MUTABLE_OK - streaming counters are updated per emitted row.
class _InventoryState:
    """Mutable counters accumulated while chunks are streamed to disk."""

    total: int = 0
    resolved: int = 0
    local: int = 0
    was_limited: bool = False


def write_casc_inventory(
    source: GameDataInventorySource,
    output_path: Path,
    *,
    mask: str = "*",
    listfile: str | None = None,
    limit: int | None = None,
) -> CascInventorySummary:
    """Enumerate root entries to TSV, including FileDataID/CKey/EKey names."""
    if limit is not None and limit < 1:
        raise CascInventoryWriteError(output_path, "limit must be positive")
    state = _InventoryState()
    chunks = _inventory_chunks(source, state, mask, listfile, limit)
    try:
        result = write_chunks_safely(
            str(output_path.parent),
            output_path.name,
            chunks,
        )
    finally:
        chunks.close()
    if result.status is not SafeWriteStatus.WRITTEN:
        raise CascInventoryWriteError(output_path, result.error or result.status.value)
    return CascInventorySummary(
        total=state.total,
        resolved_paths=state.resolved,
        unknown_paths=state.total - state.resolved,
        local_files=state.local,
        was_limited=state.was_limited,
        output_path=Path(result.path),
    )


def _inventory_chunks(
    source: GameDataInventorySource,
    state: _InventoryState,
    mask: str,
    listfile: str | None,
    limit: int | None,
) -> Generator[bytes, None, None]:
    yield _HEADER
    entries = source.iter_entries(mask, listfile)
    buffered = bytearray()
    try:
        for entry in entries:
            if limit is not None and state.total >= limit:
                state.was_limited = True
                break
            buffered.extend((_entry_tsv(entry) + "\n").encode())
            state.total += 1
            state.resolved += int(entry.name_type is CascNameType.FULL)
            state.local += int(entry.is_local)
            if len(buffered) >= _CHUNK_BYTES:
                yield bytes(buffered)
                buffered.clear()
        if buffered:
            yield bytes(buffered)
    finally:
        entries.close()


def _entry_tsv(entry: CascEntry) -> str:
    values = (
        entry.name,
        entry.name_type.name.lower(),
        "" if entry.file_data_id is None else str(entry.file_data_id),
        entry.ckey,
        entry.ekey,
        "" if entry.size is None else str(entry.size),
        "是" if entry.is_local else "否",
        "" if entry.locale_flags is None else str(entry.locale_flags),
        "" if entry.content_flags is None else str(entry.content_flags),
    )
    return "\t".join(_tsv(value) for value in values)


def _tsv(value: str) -> str:
    return value.replace("\t", " ").replace("\r", " ").replace("\n", " ")
