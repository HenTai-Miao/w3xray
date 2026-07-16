"""Build trusted description evidence from manifest-valid map publications."""

from __future__ import annotations

import csv
from collections.abc import Sequence
from pathlib import Path

from .batch_manifest_validation import verify_map_publication
from .batch_tsv import decode_tsv_cell
from .description_cache_models import (
    EMPTY_DESCRIPTION_CACHE,
    DescriptionCache,
    DescriptionCacheEntry,
)
from .description_cache_schema import is_placeholder, is_yes, parse_level
from .object_text_exports import OBJECT_TEXT_REPORT_HEADER


_COMPLETE_REPORT = "对象完整描述.tsv"


def build_description_cache_from_batch(
    root: Path,
    seed: DescriptionCache = EMPTY_DESCRIPTION_CACHE,
) -> DescriptionCache:
    """Use client-fill rows only after validating their entire map generation."""
    entries = list(seed.entries)
    diagnostics = list(seed.diagnostics)
    maps_root = root / "地图"
    if root.is_symlink() or not root.is_dir() or not maps_root.is_dir():
        return seed
    for directory in sorted(maps_root.iterdir(), key=lambda path: path.name.casefold()):
        if directory.name.startswith(".w3xray-map-"):
            continue
        validation = verify_map_publication(directory)
        manifest = validation.manifest
        if not validation.valid or manifest is None:
            diagnostics.append(
                f"manifest_validation_failed:{directory}:{validation.code}"
            )
            continue
        report = directory / _COMPLETE_REPORT
        try:
            with report.open("r", encoding="utf-8", newline="") as handle:
                rows = tuple(
                    tuple(decode_tsv_cell(cell) for cell in row)
                    for row in csv.reader(handle, delimiter="\t")
                )
        except (OSError, UnicodeError, csv.Error) as exc:
            diagnostics.append(f"缓存文件不可读：{report}：{type(exc).__name__}")
            continue
        parsed, issue = _parse_complete_rows(
            rows,
            manifest.source.sha256,
            validation.manifest_sha256,
            report,
        )
        entries.extend(parsed)
        if issue:
            diagnostics.append(issue)
    return DescriptionCache.build(entries, diagnostics)


def _parse_complete_rows(
    rows: Sequence[Sequence[str]],
    source_digest: str,
    manifest_digest: str,
    report: Path,
) -> tuple[tuple[DescriptionCacheEntry, ...], str]:
    if not rows:
        return (), f"缓存文件为空：{report}"
    if tuple(rows[0]) != OBJECT_TEXT_REPORT_HEADER:
        return (), f"缓存 schema 不匹配：{report}"
    columns = {name: index for index, name in enumerate(OBJECT_TEXT_REPORT_HEADER)}
    entries: list[DescriptionCacheEntry] = []
    for row in rows[1:]:
        if (
            len(row) != len(OBJECT_TEXT_REPORT_HEADER)
            or not _eligible_base_identity(
                row[columns["对象ID"]],
                row[columns["基础ID"]],
                row[columns["自定义"]],
            )
            or row[columns["状态"]] != "客户端补全"
            or is_yes(row[columns["占位"]])
            or is_placeholder(row[columns["原始全文"]])
            or "客户端" not in row[columns["来源类型"]]
        ):
            continue
        entries.append(
            DescriptionCacheEntry(
                row[columns["分类"]],
                row[columns["基础ID"]],
                row[columns["文本角色"]],
                parse_level(row[columns["等级/变体"]]),
                row[columns["原始全文"]],
                row[columns["可读全文"]],
                source_digest,
                manifest_digest,
                f"{report}#{row[columns['来源路径']]}",
            )
        )
    return tuple(entries), ""


def _eligible_base_identity(object_id: str, base_id: str, custom: str) -> bool:
    return bool(base_id) and object_id == base_id and not is_yes(custom)
