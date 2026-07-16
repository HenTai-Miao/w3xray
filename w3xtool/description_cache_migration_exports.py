"""Deterministic TSV payloads for trusted cache migration."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence

from .batch_tsv import format_tsv_rows
from .description_cache import format_description_cache_tsv
from .description_cache_migration_models import (
    DescriptionCacheRejection,
    ProvenDescriptionCandidate,
)
from .description_cache_models import DescriptionCache, DescriptionCacheEntry
from .description_cache_schema import (
    DESCRIPTION_CACHE_REJECTION_HEADER,
    DESCRIPTION_CACHE_SOURCE_HEADER,
)


def format_migration_payloads(
    accepted: Sequence[ProvenDescriptionCandidate],
    rejections: Sequence[DescriptionCacheRejection],
) -> Mapping[str, str]:
    """Build the exact cache, source, and rejection payload set."""
    source_text = _format_sources(accepted)
    source_digest = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    cache = DescriptionCache.build(
        DescriptionCacheEntry(
            item.candidate.category,
            item.candidate.base_id,
            item.candidate.role,
            item.level,
            item.candidate.raw_value,
            item.candidate.readable_value,
            item.candidate.source_map_sha256,
            source_digest,
            item.candidate.source_path,
        )
        for item in accepted
    )
    return {
        "可信描述缓存.tsv": format_description_cache_tsv(cache),
        "来源清单.tsv": source_text,
        "可信缓存迁移拒绝.tsv": _format_rejections(rejections),
    }


def _format_sources(accepted: Sequence[ProvenDescriptionCandidate]) -> str:
    ordered = sorted(
        accepted,
        key=lambda item: (
            item.candidate.category.casefold(),
            item.candidate.base_id,
            item.candidate.role.casefold(),
            item.candidate.level_text,
            item.candidate.source_map_sha256,
            str(item.report_path).casefold(),
        ),
    )
    rows = (
        DESCRIPTION_CACHE_SOURCE_HEADER,
        *(
            (
                item.candidate.category,
                item.candidate.base_id,
                item.candidate.role,
                item.candidate.level_text,
                item.candidate.source_map_sha256,
                str(item.report_path),
                item.report_sha256,
                str(item.report_row_number),
                item.report_row_sha256,
                item.source_label,
            )
            for item in ordered
        ),
    )
    return format_tsv_rows(rows)


def _format_rejections(rejections: Sequence[DescriptionCacheRejection]) -> str:
    rows = (
        DESCRIPTION_CACHE_REJECTION_HEADER,
        *(
            (
                row.category,
                row.base_id,
                row.role,
                row.level_text,
                row.raw_value,
                row.readable_value,
                row.source_map_sha256,
                row.source_path,
                row.reason.value,
                row.detail,
                str(row.row_number),
            )
            for row in rejections
        ),
    )
    return format_tsv_rows(rows)


__all__ = ("format_migration_payloads",)
