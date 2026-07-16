"""Reconciled counters over icon evidence and physical export outcomes."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .batch_icon_models import IconExportRecord
from .icon_evidence_index import IconEvidenceIndex
from .icon_resources import IconObjectReference


@dataclass(frozen=True, slots=True)
class IconIntegrityCounts:
    """Independent evidence and publication count families."""

    valid_reference_count: int
    resolved_reference_count: int
    filtered_field_count: int
    normalized_gap_count: int
    unresolved_reference_count: int
    anonymous_payload_count: int
    anonymous_read_failure_count: int
    original_write_failure_count: int
    png_failure_count: int

    @property
    def failure_count(self) -> int:
        """Count only physical read and write failures."""
        return physical_icon_failure_count(
            self.anonymous_read_failure_count,
            self.original_write_failure_count,
            self.png_failure_count,
        )


def physical_icon_failure_count(
    anonymous_read_failure_count: int,
    original_write_failure_count: int,
    png_failure_count: int,
) -> int:
    """Sum the three disjoint physical icon failure counters."""
    return (
        anonymous_read_failure_count + original_write_failure_count + png_failure_count
    )


def icon_integrity_counts(
    index: IconEvidenceIndex,
    exports: Iterable[IconExportRecord],
) -> IconIntegrityCounts:
    """Reconcile immutable evidence rows with attempted physical writes."""
    records = tuple(exports)
    return IconIntegrityCounts(
        valid_reference_count=len(index.resolved) + len(index.unresolved),
        resolved_reference_count=len(index.resolved),
        filtered_field_count=len(index.filtered),
        normalized_gap_count=normalized_icon_gap_count(index),
        unresolved_reference_count=len(index.unresolved),
        anonymous_payload_count=len(index.anonymous),
        anonymous_read_failure_count=index.anonymous_read_failure_count,
        original_write_failure_count=sum(not item.original_written for item in records),
        png_failure_count=sum(
            item.original_written and not item.png_written for item in records
        ),
    )


def normalized_icon_gap_count(index: IconEvidenceIndex) -> int:
    """Count one identity per logical map and normalized unresolved path."""
    return len({icon_gap_identity(row.reference) for row in index.unresolved})


def icon_gap_identity(reference: IconObjectReference) -> tuple[str, str, str]:
    """Return the logical-map and normalized-path identity of one gap."""
    return (
        reference.map_path.casefold(),
        reference.map_sha256,
        reference.normalized_path.casefold(),
    )
