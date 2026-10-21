"""Two-round retained description-cache integrity inspection."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Final

from .description_cache_publication_models import RetainedCacheRole
from .description_cache_retained_binding import BoundActiveCache, bind_active_cache
from .description_cache_retained_integrity_models import (
    CacheArtifactKind,
    DescriptionCacheRetentionError,
    DescriptionCacheRetentionReport,
    MalformedDescriptionCacheArtifact,
    RetainedArtifactValidation,
    RetainedDescriptionCacheArtifact,
    RetentionArtifactReason,
    SiblingState,
    TransientDescriptionCacheArtifact,
)
from .description_cache_retained_report import (
    format_description_cache_retention_report,
    parse_description_cache_retention_report,
)
from .description_cache_retained_set_scan import scan_artifact_set
from .description_cache_retained_siblings import capture_relevant_siblings
from .description_cache_retained_tree_snapshot import RetainedScanBounds


MAX_RETAINED_FILE_BYTES: Final = 64 * 1024 * 1024
MAX_RETAINED_TREE_BYTES: Final = 512 * 1024 * 1024
MAX_RETAINED_FILE_COUNT: Final = 100_000
MAX_RETAINED_ENTRY_COUNT: Final = 125_000
MAX_RETAINED_DEPTH: Final = 64


@dataclass(frozen=True, slots=True)
class StableRetentionInspection:
    """One report plus its exact publication-relevant sibling namespace."""

    report: DescriptionCacheRetentionReport
    siblings: tuple[SiblingState, ...]

    def require_current(self, bound: BoundActiveCache) -> None:
        """Re-prove active binding and exact relevant siblings."""
        bound.require_current()
        if (
            capture_relevant_siblings(bound.parent_descriptor, bound.root.name)
            != self.siblings
        ):
            raise DescriptionCacheRetentionError(
                "publication-relevant sibling namespace changed after inspection"
            )


def inspect_retained_description_caches(
    active_root: Path,
) -> DescriptionCacheRetentionReport:
    """Inspect relevant siblings twice while holding parent and active fds."""
    with bind_active_cache(active_root) as bound:
        return inspect_bound_retained_description_caches(bound).report


def inspect_bound_retained_description_caches(
    bound: BoundActiveCache,
) -> StableRetentionInspection:
    """Inspect twice through a caller-held active-cache binding."""
    first = scan_artifact_set(bound, _bounds())
    bound.require_current()
    second = scan_artifact_set(bound, _bounds())
    bound.require_current()
    if first.siblings != second.siblings:
        raise DescriptionCacheRetentionError(
            "publication-relevant sibling namespace changed between rounds"
        )
    if first.report == second.report:
        report = first.report
    else:
        report = _unstable_round_report(first.report, second.report)
    return StableRetentionInspection(report, second.siblings)


def _unstable_round_report(
    first: DescriptionCacheRetentionReport,
    second: DescriptionCacheRetentionReport,
) -> DescriptionCacheRetentionReport:
    second_by_path = {item.path: item for item in second.retained}
    retained = tuple(
        item
        if second_by_path.get(item.path) == item
        else replace(
            item,
            validation=RetainedArtifactValidation.UNSTABLE,
            size=None,
            file_count=None,
            entry_count=None,
            sha256=None,
        )
        for item in first.retained
    )
    return replace(first, retained=retained)


def _bounds() -> RetainedScanBounds:
    return RetainedScanBounds(
        MAX_RETAINED_FILE_BYTES,
        MAX_RETAINED_TREE_BYTES,
        MAX_RETAINED_FILE_COUNT,
        MAX_RETAINED_ENTRY_COUNT,
        MAX_RETAINED_DEPTH,
    )


__all__ = (
    "MAX_RETAINED_DEPTH",
    "MAX_RETAINED_ENTRY_COUNT",
    "MAX_RETAINED_FILE_BYTES",
    "MAX_RETAINED_FILE_COUNT",
    "MAX_RETAINED_TREE_BYTES",
    "CacheArtifactKind",
    "DescriptionCacheRetentionError",
    "DescriptionCacheRetentionReport",
    "MalformedDescriptionCacheArtifact",
    "RetainedArtifactValidation",
    "RetainedCacheRole",
    "RetainedDescriptionCacheArtifact",
    "RetentionArtifactReason",
    "TransientDescriptionCacheArtifact",
    "StableRetentionInspection",
    "format_description_cache_retention_report",
    "inspect_retained_description_caches",
    "inspect_bound_retained_description_caches",
    "parse_description_cache_retention_report",
)
