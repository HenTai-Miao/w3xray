"""Anonymous MPQ block exports for knowledge packs."""

from __future__ import annotations

import os
import struct
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Protocol

from .knowledge_io import write_text
from .mpq import MPQArchive, guess_extension

if TYPE_CHECKING:
    from .api import MapData


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
    if not getattr(md, "path", "") or not os.path.isfile(md.path):
        return 0
    try:
        archive = MPQArchive(md.path)
    except (OSError, ValueError, struct.error):
        return 0
    try:
        return write_unknown_files_from_archive(
            archive,
            out_dir,
            tuple(getattr(md, "all_files", ()) or ()) + tuple(known_names),
        )
    finally:
        archive.close()


def write_unknown_files_from_archive(
    archive: UnknownArchive,
    out_dir: str,
    known_names: Sequence[str] = (),
) -> int:
    """Export anonymous blocks as Unknown/ or UnknownRaw/ plus one manifest."""
    os.makedirs(out_dir, exist_ok=True)
    named_blocks = _named_block_indexes(archive, known_names)
    rows = [
        "block_index\tkind\trelative_path\tbytes\tflags\tfile_size\tcomp_size\tstatus",
    ]
    count = 0
    for index, block in archive.iter_blocks():
        if index in named_blocks:
            continue
        data = archive.read_block_anon(block)
        if data is None:
            relative_path, size = _write_raw_block(archive, out_dir, index, block)
            kind = "UnknownRaw"
            status = "原始负载兜底"
        else:
            relative_path, size = _write_unknown_block(out_dir, index, data)
            kind = "Unknown"
            status = "已解包"
        rows.append(_manifest_row(index, kind, relative_path, size, block, status))
        count += 1
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


def _write_unknown_block(out_dir: str, index: int, data: bytes) -> tuple[str, int]:
    ext = guess_extension(data)
    relative_path = f"Unknown/block_{index:06d}.{ext}"
    path = os.path.join(out_dir, *relative_path.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)
    return relative_path, len(data)


def _write_raw_block(
    archive: UnknownArchive,
    out_dir: str,
    index: int,
    block: UnknownBlock,
) -> tuple[str, int]:
    data = _block_raw_payload(archive, block)
    relative_path = f"UnknownRaw/block_{index:06d}.raw"
    path = os.path.join(out_dir, *relative_path.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)
    return relative_path, len(data)


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
