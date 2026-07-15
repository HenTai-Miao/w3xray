"""Build immutable per-map result summaries from extracted evidence."""

from __future__ import annotations

from .batch_descriptions import DescriptionRecord, DescriptionState
from .batch_icon_export import IconExportRecord, IconExportState, IconKind
from .batch_item_reports import BatchItemReports
from .batch_models import MapBatchResult, MapBatchState, SourceFingerprint


def build_map_result(
    fingerprint: SourceFingerprint,
    display_name: str,
    relative: str,
    state: MapBatchState,
    descriptions: tuple[DescriptionRecord, ...],
    icons: tuple[IconExportRecord, ...],
    unresolved: int,
    anonymous_failures: int,
    restricted: int,
    elapsed_ms: int,
    item_reports: BatchItemReports,
    dependency_fingerprint: str,
) -> MapBatchResult:
    """Reconcile counters and the first stable diagnostic into one result."""
    first_error = next((item.error for item in icons if item.error), "")
    if not first_error and unresolved:
        first_error = f"unresolved named icons: {unresolved}"
    if not first_error and anonymous_failures:
        first_error = f"anonymous BLP read failures: {anonymous_failures}"
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
        anonymous_icon_count=sum(item.kind is IconKind.ANONYMOUS for item in icons),
        original_written_count=sum(item.original_written for item in icons),
        png_written_count=sum(item.png_written for item in icons),
        icon_failure_count=(
            unresolved
            + anonymous_failures
            + sum(item.state is not IconExportState.COMPLETE for item in icons)
        ),
        restricted_block_count=restricted,
        elapsed_ms=elapsed_ms,
        relation_counts=item_reports.relation_counts,
        relation_incomplete_count=item_reports.relation_incomplete_count,
        dependency_fingerprint=dependency_fingerprint,
    )
