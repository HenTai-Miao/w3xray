"""Load and format manifest-bound trusted base-object description evidence."""

from __future__ import annotations

import csv
from collections.abc import Sequence
from io import StringIO
from pathlib import Path

from .batch_tsv import decode_tsv_cell, format_tsv_rows
from .description_cache_batch import build_description_cache_from_batch
from .description_cache_models import (
    EMPTY_DESCRIPTION_CACHE,
    DescriptionCache,
    DescriptionCacheEntry,
)
from .description_cache_schema import (
    CACHE_HEADER,
    is_digest,
    is_placeholder,
    parse_level,
)


def load_description_cache(path: str | None) -> DescriptionCache:
    """Load one explicit standalone cache without following symlinks."""
    if path is None:
        return EMPTY_DESCRIPTION_CACHE
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        return DescriptionCache.build((), (f"缓存文件无效：{source}",))
    try:
        with source.open("r", encoding="utf-8", newline="") as handle:
            text = handle.read()
    except (OSError, UnicodeError) as exc:
        return DescriptionCache.build(
            (),
            (f"缓存文件不可读：{source}：{type(exc).__name__}",),
        )
    return load_description_cache_text(text, str(source))


def load_description_cache_text(text: str, source: str) -> DescriptionCache:
    """Parse strict cache text already protected by an outer trust boundary."""
    try:
        with StringIO(text, newline="") as handle:
            rows = tuple(
                tuple(decode_tsv_cell(cell) for cell in row)
                for row in csv.reader(handle, delimiter="\t")
            )
    except csv.Error as exc:
        return DescriptionCache.build(
            (),
            (f"缓存文件不可读：{source}：{type(exc).__name__}",),
        )
    if not rows or tuple(rows[0]) != CACHE_HEADER:
        return DescriptionCache.build((), (f"缓存 schema 不匹配：{source}",))
    source_path = Path(source)
    entries = tuple(
        entry
        for row in rows[1:]
        if (entry := _standalone_entry(row, source_path)) is not None
    )
    return DescriptionCache.build(entries)


def format_description_cache_tsv(cache: DescriptionCache) -> str:
    """Serialize cache entries without truncating or normalizing source text."""
    rows = (
        CACHE_HEADER,
        *(
            (
                entry.category,
                entry.base_id,
                entry.role,
                "" if entry.level is None else str(entry.level),
                entry.raw_value,
                entry.readable_value,
                entry.source_map_sha256,
                entry.source_manifest_sha256,
                entry.source_path,
            )
            for entry in cache.entries
        ),
    )
    return format_tsv_rows(rows)


def _standalone_entry(
    row: Sequence[str],
    source: Path,
) -> DescriptionCacheEntry | None:
    if len(row) != len(CACHE_HEADER) or not row[0] or not row[1] or not row[2]:
        return None
    source_digest = row[6].strip()
    manifest_digest = row[7].strip()
    if (
        not is_digest(source_digest)
        or not is_digest(manifest_digest)
        or is_placeholder(row[4])
    ):
        return None
    return DescriptionCacheEntry(
        row[0],
        row[1],
        row[2],
        parse_level(row[3]),
        row[4],
        row[5],
        source_digest,
        manifest_digest,
        row[8] or str(source),
    )


__all__ = (
    "EMPTY_DESCRIPTION_CACHE",
    "DescriptionCache",
    "DescriptionCacheEntry",
    "build_description_cache_from_batch",
    "format_description_cache_tsv",
    "load_description_cache",
    "load_description_cache_text",
)
