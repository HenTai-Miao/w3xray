"""Recover archive file names from embedded resource references."""

from __future__ import annotations

import re
from typing import Final, Protocol

from .mpq import HASH_NAME_A, HASH_NAME_B, _hash, guess_extension
from .safe_output import (
    SafeWriteStatus,
    safe_relative_path,
    write_bytes_safely,
    write_text_safely,
)

_RESOURCE_NAME_RE = re.compile(
    rb"(?i)([A-Za-z0-9_ .()\\/\-]{1,240}\."
    rb"(?:blp|mdx|mdl|wav|mp3|ogg|tga|dds|txt|slk|ttf|j|lua|doo|wtg|wct|"
    rb"w3u|w3t|w3a|w3q|w3b|w3d|w3h|w3r|w3c|w3s|wgc))"
)
_MAX_RECOVERY_SCAN_BYTES: Final = 128 * 1024 * 1024
_MAX_RECOVERY_EXPORT_BYTES: Final = 256 * 1024 * 1024
_MAX_RECOVERY_CANDIDATES: Final = 100_000


class RecoveryArchive(Protocol):
    block_table: list
    hash_table: list

    def list_files(self) -> list[str]: ...

    def read_file(self, name: str) -> bytes: ...

    def iter_blocks(self): ...

    def read_block_anon(self, block) -> bytes | None: ...


def _export_recovered_named_files(
    archive: RecoveryArchive,
    out_dir: str,
    exported_blocks: set[int],
) -> int:
    """Recover names for anonymous blocks from paths embedded in resources."""
    candidates = set()
    for name in archive.list_files():
        candidates.update(_resource_name_variants(name))
    scanned_bytes = 0
    for _idx, block in archive.iter_blocks():
        remaining_bytes = _MAX_RECOVERY_SCAN_BYTES - scanned_bytes
        if remaining_bytes <= 0:
            break
        declared_size = max(1, block.file_size)
        if declared_size > remaining_bytes:
            continue
        data = archive.read_block_anon(block)
        scanned_bytes += max(declared_size, len(data) if data is not None else 0)
        if not data or len(data) > remaining_bytes:
            continue
        candidates.update(_resource_name_candidates(data))
        if len(candidates) >= _MAX_RECOVERY_CANDIDATES:
            break
    by_hash: dict[tuple[int, int], list[str]] = {}
    for name in candidates:
        by_hash.setdefault((_hash(name, HASH_NAME_A), _hash(name, HASH_NAME_B)), []).append(name)
    manifest: list[str] = []
    count = 0
    exported_bytes = 0
    for name_a, name_b, _locale, _platform, block_index in getattr(archive, "hash_table", []):
        remaining_bytes = _MAX_RECOVERY_EXPORT_BYTES - exported_bytes
        if remaining_bytes <= 0:
            break
        if block_index in (0xFFFFFFFF, 0xFFFFFFFE) or block_index >= len(archive.block_table):
            continue
        if block_index in exported_blocks:
            continue
        hits = by_hash.get((name_a, name_b))
        if hits:
            declared_size = max(1, archive.block_table[block_index].file_size)
            if declared_size > remaining_bytes:
                manifest.append(
                    f"SKIP\tblock={block_index}\tname={hits[0]}\treason=size-limit",
                )
                continue
            written, size = _try_export_recovered_hit(
                archive,
                out_dir,
                exported_blocks,
                manifest,
                block_index,
                hits,
                remaining_bytes,
                declared_size,
            )
            count += written
            exported_bytes += size
    if manifest:
        write_text_safely(
            out_dir,
            "RecoveredNames/manifest.tsv",
            "\n".join(manifest) + "\n",
        )
    return count


def _resource_name_variants(name: str) -> set[str]:
    name = name.replace("\x00", "").strip().strip("\"'")
    if not name or len(name) > 260:
        return set()
    relative = safe_relative_path(name)
    if relative is None:
        return set()
    normalized = "\\".join(relative.parts)
    names = {normalized}
    if not normalized.lower().startswith("war3mapimported\\"):
        names.add("war3mapImported\\" + normalized)
    return names


def _resource_name_candidates(data: bytes) -> set[str]:
    names: set[str] = set()
    for match in _RESOURCE_NAME_RE.finditer(data):
        raw = match.group(1).decode("latin-1", "ignore")
        names.update(_resource_name_variants(raw))
    return names


def _try_export_recovered_hit(
    archive: RecoveryArchive,
    out_dir: str,
    exported_blocks: set[int],
    manifest: list[str],
    block_index: int,
    hits: list[str],
    remaining_bytes: int,
    declared_size: int,
) -> tuple[int, int]:
    ordered = sorted(set(hits), key=lambda item: (item.lower().startswith("war3mapimported\\"), len(item), item.lower()))
    consumed_bytes = 0
    for name in ordered:
        available_bytes = remaining_bytes - consumed_bytes
        if declared_size > available_bytes:
            manifest.append(f"SKIP\tblock={block_index}\tname={name}\treason=size-limit")
            break
        try:
            data = archive.read_file(name)
        except (KeyError, OSError, ValueError):
            consumed_bytes += declared_size
            continue
        consumed_bytes += max(declared_size, len(data))
        if len(data) > available_bytes:
            manifest.append(f"SKIP\tblock={block_index}\tname={name}\treason=size-limit")
            return 0, consumed_bytes
        result = write_bytes_safely(out_dir, name, data)
        if result.status is SafeWriteStatus.UNSAFE:
            manifest.append(f"UNSAFE\tblock={block_index}\tname={name}")
            return 0, consumed_bytes
        if result.status is SafeWriteStatus.FAILED:
            manifest.append(f"FAIL\tblock={block_index}\tname={name}\thits={len(ordered)}")
            return 0, consumed_bytes
        exported_blocks.add(block_index)
        manifest.append(
            f"OK\tblock={block_index}\tname={name}\tsize={len(data)}\t"
            f"type={guess_extension(data)}\thits={len(ordered)}"
        )
        return 1, consumed_bytes
    manifest.append(f"FAIL\tblock={block_index}\tname={ordered[0]}\thits={len(ordered)}")
    return 0, consumed_bytes
