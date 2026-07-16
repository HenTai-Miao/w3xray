"""Build immutable per-map result summaries from extracted evidence."""

from __future__ import annotations

from .batch_descriptions import DescriptionRecord, DescriptionState
from .batch_icon_export import IconExportRecord, IconKind
from .batch_item_reports import BatchItemReports
from .batch_models import MapBatchResult, MapBatchState, SourceFingerprint
from .icon_evidence_counts import icon_integrity_counts
from .icon_evidence_index import IconEvidenceIndex


def build_map_result(
    fingerprint: SourceFingerprint,
    display_name: str,
    relative: str,
    state: MapBatchState,
    descriptions: tuple[DescriptionRecord, ...],
    icons: tuple[IconExportRecord, ...],
    icon_index: IconEvidenceIndex,
    restricted: int,
    elapsed_ms: int,
    item_reports: BatchItemReports,
    dependency_fingerprint: str,
) -> MapBatchResult:
    """Reconcile counters and the first stable diagnostic into one result."""
    icon_counts = icon_integrity_counts(icon_index, icons)
    first_error = next((item.error for item in icons if item.error), "")
    if not first_error and icon_counts.normalized_gap_count:
        first_error = f"unresolved named icons: {icon_counts.normalized_gap_count}"
    if not first_error and icon_counts.anonymous_read_failure_count:
        first_error = (
            f"anonymous BLP read failures: {icon_counts.anonymous_read_failure_count}"
        )
    missing = sum(
        item.state is DescriptionState.SOURCE_MISSING for item in descriptions
    )
    if not first_error and missing:
        first_error = f"missing descriptions: {missing}"
    return MapBatchResult(
        source=fingerprint,
        display_name=display_name,
        output_directory=relative,
        stage="published",
        state=state,
        first_error=first_error,
        object_count=len({(item.category, item.object_id) for item in descriptions}),
        description_counts=item_reports.description_counts,
        named_icon_count=sum(item.kind is IconKind.NAMED for item in icons),
        anonymous_icon_count=icon_counts.anonymous_payload_count,
        original_written_count=sum(item.original_written for item in icons),
        png_written_count=sum(item.png_written for item in icons),
        icon_failure_count=icon_counts.failure_count,
        restricted_block_count=restricted,
        elapsed_ms=elapsed_ms,
        relation_counts=item_reports.relation_counts,
        relation_incomplete_count=item_reports.relation_incomplete_count,
        dependency_fingerprint=dependency_fingerprint,
        valid_icon_reference_count=icon_counts.valid_reference_count,
        resolved_icon_reference_count=icon_counts.resolved_reference_count,
        filtered_icon_field_count=icon_counts.filtered_field_count,
        unresolved_icon_count=icon_counts.normalized_gap_count,
        unresolved_icon_reference_count=icon_counts.unresolved_reference_count,
        anonymous_read_failure_count=icon_counts.anonymous_read_failure_count,
        original_write_failure_count=icon_counts.original_write_failure_count,
        png_failure_count=icon_counts.png_failure_count,
    )
