"""Validate and load reusable base-object description evidence."""

from __future__ import annotations

import csv
import re
from collections.abc import Sequence
from io import StringIO
from pathlib import Path
from typing import Final

from .description_cache_models import (
    EMPTY_DESCRIPTION_CACHE,
    DescriptionCache,
    DescriptionCacheEntry,
)


__all__ = (
    "EMPTY_DESCRIPTION_CACHE",
    "DescriptionCache",
    "DescriptionCacheEntry",
    "build_description_cache_from_batch",
    "format_description_cache_tsv",
    "load_description_cache",
)

_OWNERSHIP_MARKER: Final = ".w3xray-batch-owned"
_DESCRIPTION_REPORT: Final = "对象描述.tsv"
_DIGEST: Final = re.compile(r"[0-9a-fA-F]{64}")
_PLACEHOLDERS: Final = frozenset({"", "-", "_", ",", '""', "''"})
_LEGACY_HEADER: Final = (
    "分类",
    "对象ID",
    "基础ID",
    "名称",
    "自定义",
    "等级",
    "原始提示",
    "可读提示",
    "提示来源",
    "原始说明",
    "可读说明",
    "说明来源",
    "完整性状态",
)
_COMPLETE_HEADER: Final = (
    "分类",
    "对象ID",
    "基础ID",
    "名称",
    "自定义",
    "文本角色",
    "字段键",
    "字段标签",
    "等级/变体",
    "原始全文",
    "可读全文",
    "来源类型",
    "来源路径",
    "状态",
    "占位",
    "冲突组",
    "证据序号",
)
_CACHE_HEADER: Final = (
    "分类",
    "基础ID",
    "文本角色",
    "等级/变体",
    "原始全文",
    "可读全文",
    "来源地图SHA256",
    "来源路径",
)


def build_description_cache_from_batch(
    root: Path,
    seed: DescriptionCache = EMPTY_DESCRIPTION_CACHE,
) -> DescriptionCache:
    """Discover regular owned map reports below one batch output root."""
    entries = list(seed.entries)
    diagnostics = list(seed.diagnostics)
    if not root.is_dir() or root.is_symlink():
        return seed
    for report in sorted(
        root.rglob(_DESCRIPTION_REPORT), key=lambda path: str(path).casefold()
    ):
        digest = _owned_report_digest(report)
        if digest is None:
            continue
        try:
            with report.open("r", encoding="utf-8", newline="") as handle:
                rows = tuple(csv.reader(handle, delimiter="\t"))
        except (OSError, UnicodeError, csv.Error) as exc:
            diagnostics.append(f"缓存文件不可读：{report}：{type(exc).__name__}")
            continue
        parsed, issue = _parse_owned_report(rows, digest, report)
        entries.extend(parsed)
        if issue:
            diagnostics.append(issue)
    return DescriptionCache.build(entries, diagnostics)


def load_description_cache(path: str | None) -> DescriptionCache:
    """Load one standalone tool-generated cache without following symlinks."""
    if path is None:
        return EMPTY_DESCRIPTION_CACHE
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        return DescriptionCache.build((), (f"缓存文件无效：{source}",))
    try:
        with source.open("r", encoding="utf-8", newline="") as handle:
            rows = tuple(csv.reader(handle, delimiter="\t"))
    except (OSError, UnicodeError, csv.Error) as exc:
        return DescriptionCache.build(
            (), (f"缓存文件不可读：{source}：{type(exc).__name__}",)
        )
    if not rows or tuple(rows[0]) != _CACHE_HEADER:
        return DescriptionCache.build((), (f"缓存 schema 不匹配：{source}",))
    entries = tuple(
        entry
        for row in rows[1:]
        if (entry := _standalone_entry(row, source)) is not None
    )
    return DescriptionCache.build(entries)


def format_description_cache_tsv(cache: DescriptionCache) -> str:
    """Serialize the standalone cache with lossless standard TSV quoting."""
    with StringIO(newline="") as output:
        writer = csv.writer(output, delimiter="\t", lineterminator="\n")
        writer.writerow(_CACHE_HEADER)
        for entry in cache.entries:
            writer.writerow(
                (
                    entry.category,
                    entry.base_id,
                    entry.role,
                    "" if entry.level is None else str(entry.level),
                    entry.raw_value,
                    entry.readable_value,
                    entry.source_map_sha256,
                    entry.source_path,
                ),
            )
        return output.getvalue()


def _owned_report_digest(report: Path) -> str | None:
    if report.is_symlink() or not report.is_file():
        return None
    marker = report.parent / _OWNERSHIP_MARKER
    if marker.is_symlink() or not marker.is_file():
        return None
    try:
        digest = marker.read_text(encoding="ascii").strip()
    except OSError, UnicodeError:
        return None
    return digest.lower() if _DIGEST.fullmatch(digest) else None


def _parse_owned_report(
    rows: Sequence[Sequence[str]],
    digest: str,
    report: Path,
) -> tuple[tuple[DescriptionCacheEntry, ...], str]:
    if not rows:
        return (), f"缓存文件为空：{report}"
    header = tuple(rows[0])
    if header == _LEGACY_HEADER:
        return _legacy_entries(rows[1:], digest, report), ""
    if header == _COMPLETE_HEADER:
        return _complete_entries(rows[1:], digest, report), ""
    return (), f"缓存 schema 不匹配：{report}"


def _legacy_entries(
    rows: Sequence[Sequence[str]],
    digest: str,
    report: Path,
) -> tuple[DescriptionCacheEntry, ...]:
    entries: list[DescriptionCacheEntry] = []
    for row in rows:
        if len(row) != len(_LEGACY_HEADER) or not _eligible_base_identity(
            row[1], row[2], row[4]
        ):
            continue
        level = _parse_level(row[5])
        for role, raw_index, readable_index, source_index in (
            ("基础提示", 6, 7, 8),
            ("扩展提示", 9, 10, 11),
        ):
            raw_value = row[raw_index]
            if (
                _is_placeholder(raw_value)
                or row[source_index].casefold() != f"base:{row[2]}".casefold()
                or (role == "扩展提示" and row[12] != "客户端补全")
            ):
                continue
            entries.append(
                DescriptionCacheEntry(
                    row[0],
                    row[2],
                    role,
                    level,
                    raw_value,
                    row[readable_index],
                    digest,
                    f"{report}#{row[source_index]}",
                ),
            )
    return tuple(entries)


def _complete_entries(
    rows: Sequence[Sequence[str]],
    digest: str,
    report: Path,
) -> tuple[DescriptionCacheEntry, ...]:
    entries: list[DescriptionCacheEntry] = []
    for row in rows:
        if (
            len(row) != len(_COMPLETE_HEADER)
            or not _eligible_base_identity(row[1], row[2], row[4])
            or row[13] != "客户端补全"
            or _yes(row[14])
            or _is_placeholder(row[9])
            or "客户端" not in row[11]
        ):
            continue
        entries.append(
            DescriptionCacheEntry(
                row[0],
                row[2],
                row[5],
                _parse_level(row[8]),
                row[9],
                row[10],
                digest,
                f"{report}#{row[12]}",
            ),
        )
    return tuple(entries)


def _eligible_base_identity(object_id: str, base_id: str, custom: str) -> bool:
    return bool(base_id) and object_id == base_id and not _yes(custom)


def _standalone_entry(row: Sequence[str], source: Path) -> DescriptionCacheEntry | None:
    if len(row) != len(_CACHE_HEADER) or not row[0] or not row[1] or not row[2]:
        return None
    digest = row[6].strip()
    if not _DIGEST.fullmatch(digest) or _is_placeholder(row[4]):
        return None
    return DescriptionCacheEntry(
        row[0],
        row[1],
        row[2],
        _parse_level(row[3]),
        row[4],
        row[5],
        digest.lower(),
        row[7] or str(source),
    )


def _parse_level(value: str) -> int | None:
    stripped = value.strip()
    return int(stripped) if stripped.isdecimal() else None


def _yes(value: str) -> bool:
    return value.strip().casefold() in {"是", "true", "1", "yes"}


def _is_placeholder(value: str) -> bool:
    return value.strip() in _PLACEHOLDERS
