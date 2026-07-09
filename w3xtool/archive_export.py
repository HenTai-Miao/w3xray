"""Full archive extraction helpers."""

from __future__ import annotations

from collections.abc import Sequence
import os
import shutil
import tempfile
from typing import Protocol

from .archive_export_paths import _safe_export_path
from .archive_export_recovery import _export_recovered_named_files
from .external_listfile import read_external_listfile
from .mpq import MPQArchive, guess_extension

KNOWN_EXPORT_FILES = [
    "war3map.w3u", "war3map.w3t", "war3map.w3a", "war3map.w3q",
    "war3map.w3b", "war3map.w3d", "war3map.w3h", "war3map.j",
    "war3map.lua", "war3map.wts", "war3map.wtg", "war3map.wct",
    "war3map.w3i", "war3map.w3e",
    "war3map.w3r", "war3map.w3c", "war3map.w3s", "war3map.wgc",
    "war3mapUnits.doo", "war3map.doo", "war3map.shd", "war3map.mmp",
    "war3mapMap.blp", "war3map.wpm", "testconfig.wgc", "(listfile)",
]


class ExportArchive(Protocol):
    path: str
    archive_offset: int
    _data: bytes
    block_table: list
    hash_table: list

    def list_files(self) -> list[str]: ...

    def has_file(self, name: str) -> bool: ...

    def read_file(self, name: str) -> bytes: ...

    def block_index_of(self, name: str) -> int | None: ...

    def iter_blocks(self): ...

    def read_block_anon(self, block) -> bytes | None: ...


def _imported_names(archive: ExportArchive) -> list[str]:
    """Return import-table candidate paths for export fallback."""
    from .mpq_files import import_candidate_names

    return list(import_candidate_names(archive))


def tmp_extract_dir(name: str, *sub: str, clean: bool = False) -> str:
    """Return the temporary extraction directory for a map name."""
    safe_name = "".join(char if char not in '\\/:*?"<>|' else "_" for char in (name or "map")).strip() or "map"
    root = os.path.join(tempfile.gettempdir(), "w3xtool提取", safe_name, *sub)
    if clean and os.path.isdir(root):
        shutil.rmtree(root, ignore_errors=True)
    os.makedirs(root, exist_ok=True)
    return root


def export_all_files(
    path: str,
    out_dir: str | None = None,
    _depth: int = 0,
    *,
    external_listfile_path: str | None = None,
    external_names: Sequence[str] = (),
) -> str:
    """Extract every discoverable archive file to ``out_dir``."""
    archive = MPQArchive(path)
    try:
        names = tuple(external_names) + read_external_listfile(external_listfile_path)
        return _export_all_impl(archive, out_dir, _depth, external_names=names)
    finally:
        archive.close()


def _export_all_impl(
    archive: ExportArchive,
    out_dir: str | None,
    _depth: int,
    *,
    external_names: Sequence[str] = (),
) -> str:
    if out_dir is None:
        out_dir = tmp_extract_dir(_archive_name(archive), clean=True)
    os.makedirs(out_dir, exist_ok=True)
    names = set(archive.list_files())
    names.update(KNOWN_EXPORT_FILES)
    names.update(_imported_names(archive))
    names.update(external_names)
    sub_maps: list[str] = []
    exported_blocks: set[int] = set()
    raw_manifest: list[str] = []
    for name in sorted(names):
        _export_named_file(archive, out_dir, name, exported_blocks, sub_maps)
    _export_recovered_named_files(archive, out_dir, exported_blocks)
    _export_unknown_blocks(archive, out_dir, exported_blocks, raw_manifest, sub_maps)
    if raw_manifest:
        raw_dir = os.path.join(out_dir, "UnknownRaw")
        with open(os.path.join(raw_dir, "manifest.tsv"), "w", encoding="utf-8") as handle:
            handle.write("\n".join(raw_manifest) + "\n")
    if _depth == 0:
        _export_sub_maps(out_dir, sub_maps, external_names)
    return out_dir


def _block_raw_payload(archive: ExportArchive, block) -> bytes:
    start = archive.archive_offset + block.file_pos
    if start < 0 or start > len(archive._data):
        return b""
    end = min(start + block.comp_size, len(archive._data))
    return bytes(archive._data[start:end])


def _export_named_file(
    archive: ExportArchive,
    out_dir: str,
    name: str,
    exported_blocks: set[int],
    sub_maps: list[str],
) -> None:
    if not archive.has_file(name):
        return
    dest = _safe_export_path(out_dir, name)
    if dest is None:
        return
    try:
        data = archive.read_file(name)
    except (KeyError, OSError, ValueError):
        return
    os.makedirs(os.path.dirname(dest) or out_dir, exist_ok=True)
    with open(dest, "wb") as handle:
        handle.write(data)
    block_index = archive.block_index_of(name)
    if block_index is not None:
        exported_blocks.add(block_index)
    if name.lower().endswith((".w3x", ".w3m")):
        sub_maps.append(name)


def _export_unknown_blocks(
    archive: ExportArchive,
    out_dir: str,
    exported_blocks: set[int],
    raw_manifest: list[str],
    sub_maps: list[str],
) -> None:
    unknown_dir = os.path.join(out_dir, "Unknown")
    for index, block in archive.iter_blocks():
        if index in exported_blocks:
            continue
        data = archive.read_block_anon(block)
        if data is None:
            _export_raw_block(archive, out_dir, index, block, raw_manifest)
            continue
        ext = guess_extension(data)
        os.makedirs(unknown_dir, exist_ok=True)
        filename = "File%06d.%s" % (index, ext)
        with open(os.path.join(unknown_dir, filename), "wb") as handle:
            handle.write(data)
        if ext in ("w3m", "w3x"):
            sub_maps.append(os.path.join("Unknown", filename))


def _export_raw_block(
    archive: ExportArchive,
    out_dir: str,
    index: int,
    block,
    manifest: list[str],
) -> None:
    raw_dir = os.path.join(out_dir, "UnknownRaw")
    os.makedirs(raw_dir, exist_ok=True)
    filename = "File%06d.mpqraw" % index
    raw = _block_raw_payload(archive, block)
    with open(os.path.join(raw_dir, filename), "wb") as handle:
        handle.write(raw)
    manifest.append(
        f"{filename}\tblock={index}\tcomp_size={block.comp_size}\t"
        f"file_size={block.file_size}\tflags=0x{block.flags:08X}\t"
        f"raw_size={len(raw)}\treason=anonymous-block-unrecoverable"
    )


def _export_sub_maps(out_dir: str, sub_maps: list[str], external_names: Sequence[str]) -> None:
    for name in sub_maps:
        inner_dir = _safe_export_path(out_dir, os.path.splitext(name)[0])
        if inner_dir is None:
            continue
        blob = os.path.join(out_dir, name.replace("\\", os.sep).replace("/", os.sep))
        if not os.path.exists(blob):
            continue
        try:
            export_all_files(blob, inner_dir, 1, external_names=external_names)
        except (OSError, ValueError):
            continue


def _archive_name(archive: ExportArchive) -> str:
    try:
        data = archive._data
        if data[:4] == b"HM3W":
            end = data.index(b"\x00", 8)
            return data[8:end].decode("utf-8", "replace")
    except (AttributeError, ValueError, IndexError, UnicodeDecodeError):
        pass
    return os.path.basename(getattr(archive, "path", "map"))
