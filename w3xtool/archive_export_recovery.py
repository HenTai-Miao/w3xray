"""Recover archive file names from embedded resource references."""

from __future__ import annotations

import os
import re
from typing import Protocol

from .archive_export_paths import _safe_export_path
from .mpq import HASH_NAME_A, HASH_NAME_B, _hash, guess_extension

_RESOURCE_NAME_RE = re.compile(
    rb"(?i)([A-Za-z0-9_ .()\\/\-]{1,240}\."
    rb"(?:blp|mdx|mdl|wav|mp3|ogg|tga|dds|txt|slk|ttf|j|lua|doo|wtg|wct|"
    rb"w3u|w3t|w3a|w3q|w3b|w3d|w3h|w3r|w3c|w3s|wgc))"
)


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
    for _idx, block in archive.iter_blocks():
        data = archive.read_block_anon(block)
        if data:
            candidates.update(_resource_name_candidates(data))
    by_hash: dict[tuple[int, int], list[str]] = {}
    for name in candidates:
        by_hash.setdefault((_hash(name, HASH_NAME_A), _hash(name, HASH_NAME_B)), []).append(name)
    manifest: list[str] = []
    count = 0
    for name_a, name_b, _locale, _platform, block_index in getattr(archive, "hash_table", []):
        if block_index in (0xFFFFFFFF, 0xFFFFFFFE) or block_index >= len(archive.block_table):
            continue
        if block_index in exported_blocks:
            continue
        hits = by_hash.get((name_a, name_b))
        if hits:
            count += _try_export_recovered_hit(archive, out_dir, exported_blocks, manifest, block_index, hits)
    if manifest:
        rec_dir = os.path.join(out_dir, "RecoveredNames")
        os.makedirs(rec_dir, exist_ok=True)
        with open(os.path.join(rec_dir, "manifest.tsv"), "w", encoding="utf-8") as handle:
            handle.write("\n".join(manifest) + "\n")
    return count


def _resource_name_variants(name: str) -> set[str]:
    name = name.replace("\x00", "").strip().strip("\"'")
    if not name or len(name) > 260:
        return set()
    name = name.replace("/", "\\").lstrip("\\")
    parts = [part for part in name.split("\\") if part and part != "."]
    if not parts or any(part == ".." for part in parts):
        return set()
    normalized = "\\".join(parts)
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
) -> int:
    ordered = sorted(set(hits), key=lambda item: (item.lower().startswith("war3mapimported\\"), len(item), item.lower()))
    for name in ordered:
        try:
            data = archive.read_file(name)
        except (KeyError, OSError, ValueError):
            continue
        dest = _safe_export_path(out_dir, name)
        if dest is None:
            manifest.append(f"UNSAFE\tblock={block_index}\tname={name}")
            return 0
        os.makedirs(os.path.dirname(dest) or out_dir, exist_ok=True)
        with open(dest, "wb") as handle:
            handle.write(data)
        exported_blocks.add(block_index)
        manifest.append(
            f"OK\tblock={block_index}\tname={name}\tsize={len(data)}\t"
            f"type={guess_extension(data)}\thits={len(ordered)}"
        )
        return 1
    manifest.append(f"FAIL\tblock={block_index}\tname={ordered[0]}\thits={len(ordered)}")
    return 0
