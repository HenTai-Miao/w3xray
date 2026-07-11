"""Anonymous MPQ block exports for knowledge packs."""

from __future__ import annotations

import os
import struct
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Final, Protocol

from .campaign_sources import open_map_source
from .knowledge_io import record_safe_write, write_bytes, write_text
from .mpq import guess_extension
from .safe_output import SafeWriteStatus
from .safe_output_models import SafeWriteResult

if TYPE_CHECKING:
    from .api import MapData

_MAX_UNKNOWN_EXPORT_BYTES: Final = 512 * 1024 * 1024
_MAX_UNKNOWN_MANIFEST_ROWS: Final = 100_000


class UnknownBlock(Protocol):
    file_pos: int
    comp_size: int
    file_size: int
    flags: int


class UnknownArchive(Protocol):
    path: str
    archive_offset: int
    _data: bytes

    def list_files(self) -> Sequence[str]: ...

    def block_index_of(self, name: str) -> int | None: ...

    def iter_blocks(self) -> Iterable[tuple[int, UnknownBlock]]: ...

    def read_block_anon(self, block: UnknownBlock) -> bytes | None: ...


def write_unknown_files(md: "MapData", out_dir: str, known_names: Sequence[str] = ()) -> int:
    """Write anonymous blocks from a readable MPQ source into ``out_dir``."""
    try:
        with open_map_source(md) as archive:
            return write_unknown_files_from_archive(
                archive,
                out_dir,
                tuple(getattr(md, "all_files", ()) or ()) + tuple(known_names),
            )
    except (OSError, ValueError, struct.error) as exc:
        if md.archive_source is not None or os.path.exists(md.path):
            record_safe_write(
                out_dir,
                "Unknown_manifest.tsv",
                SafeWriteResult(
                    SafeWriteStatus.FAILED,
                    "",
                    0,
                    f"{type(exc).__name__}: unknown-file extraction failed",
                ),
            )
        return 0


def write_unknown_files_from_archive(
    archive: UnknownArchive,
    out_dir: str,
    known_names: Sequence[str] = (),
) -> int:
    """Export anonymous blocks as Unknown/ or UnknownRaw/ plus one manifest."""
    named_blocks = _named_block_indexes(archive, known_names)
    rows = [
        "block_index\tkind\trelative_path\tbytes\tflags\tfile_size\tcomp_size\tstatus",
    ]
    count = 0
    consumed_bytes = 0
    for index, block in archive.iter_blocks():
        if len(rows) > _MAX_UNKNOWN_MANIFEST_ROWS:
            break
        if index in named_blocks:
            continue
        remaining_bytes = _MAX_UNKNOWN_EXPORT_BYTES - consumed_bytes
        if remaining_bytes <= 0:
            break
        declared_size = max(1, block.file_size)
        if declared_size > remaining_bytes:
            rows.append(_manifest_row(index, "Skipped", "", 0, block, "累计大小超过导出上限"))
            continue
        data = archive.read_block_anon(block)
        if data is None:
            raw = _block_raw_payload(archive, block)
            consumed_bytes += max(declared_size, len(raw))
            if len(raw) > remaining_bytes:
                rows.append(_manifest_row(index, "Skipped", "", 0, block, "累计大小超过导出上限"))
                continue
            relative_path, size, written = _write_raw_block(out_dir, index, raw)
            kind = "UnknownRaw"
            status = "原始负载兜底" if written else "写入被拒绝"
        else:
            consumed_bytes += max(declared_size, len(data))
            if len(data) > remaining_bytes:
                rows.append(_manifest_row(index, "Skipped", "", 0, block, "累计大小超过导出上限"))
                continue
            relative_path, size, written = _write_unknown_block(out_dir, index, data)
            kind = "Unknown"
            status = "已解包" if written else "写入被拒绝"
        rows.append(_manifest_row(index, kind, relative_path, size, block, status))
        count += int(written)
    return count + write_text(out_dir, "Unknown_manifest.tsv", "\n".join(rows) + "\n")


def _named_block_indexes(
    archive: UnknownArchive,
    known_names: Sequence[str],
) -> set[int]:
    names = tuple(archive.list_files()) + tuple(known_names)
    indexes: set[int] = set()
    for name in names:
        block_index = archive.block_index_of(name)
        if block_index is not None:
            indexes.add(block_index)
    return indexes


def _write_unknown_block(out_dir: str, index: int, data: bytes) -> tuple[str, int, bool]:
    ext = guess_extension(data)
    relative_path = f"Unknown/block_{index:06d}.{ext}"
    result = write_bytes(out_dir, relative_path, data)
    written = result.status is SafeWriteStatus.WRITTEN
    return relative_path, result.size, written


def _write_raw_block(
    out_dir: str,
    index: int,
    data: bytes,
) -> tuple[str, int, bool]:
    relative_path = f"UnknownRaw/block_{index:06d}.raw"
    result = write_bytes(out_dir, relative_path, data)
    written = result.status is SafeWriteStatus.WRITTEN
    return relative_path, result.size, written


def _block_raw_payload(archive: UnknownArchive, block: UnknownBlock) -> bytes:
    start = archive.archive_offset + block.file_pos
    if start < 0 or start > len(archive._data):
        return b""
    end = min(start + block.comp_size, len(archive._data))
    return bytes(archive._data[start:end])


def _manifest_row(
    index: int,
    kind: str,
    relative_path: str,
    size: int,
    block: UnknownBlock,
    status: str,
) -> str:
    return "\t".join((
        str(index),
        kind,
        relative_path,
        str(size),
        f"0x{block.flags:08X}",
        str(block.file_size),
        str(block.comp_size),
        status,
    ))
