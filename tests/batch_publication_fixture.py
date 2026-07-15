"""Small manifest-valid batch publication fixture shared by resume tests."""

from __future__ import annotations

from pathlib import Path

from w3xtool.batch_map_manifest import finalize_map_manifest
from w3xtool.batch_models import MapBatchResult, MapBatchState, SourceFingerprint
from w3xtool.batch_reports import (
    format_description_completeness,
    format_description_tsv,
    format_icon_completeness,
    format_icon_index_tsv,
    format_map_summary,
)
from w3xtool.item_relation_exports import (
    format_equipment_skills_tsv,
    format_item_acquisition_tsv,
    format_relation_completeness,
)
from w3xtool.item_relation_models import ItemRelationIndex
from w3xtool.object_text_exports import format_object_text_tsv
from w3xtool.object_text_models import ObjectTextIndex


def publish_empty_result(
    index: int,
    fingerprint: SourceFingerprint,
    output_root: str,
) -> MapBatchResult:
    """Publish one empty but schema-valid result for orchestration tests."""
    relative = f"地图/{index:03d}_{fingerprint.sha256[:8]}"
    destination = Path(output_root, relative)
    destination.mkdir(parents=True, exist_ok=True)
    result = empty_result(fingerprint, relative)
    return write_empty_publication(
        destination,
        result,
        fingerprint.sha256[:32],
    )


def write_empty_publication(
    destination: Path,
    result: MapBatchResult,
    transaction_id: str,
) -> MapBatchResult:
    """Write one manifest-valid empty publication into an existing directory."""
    empty_text = ObjectTextIndex.build(())
    empty_relations = ItemRelationIndex.build(())
    reports = (
        ("地图摘要.txt", format_map_summary(result)),
        ("图标索引.tsv", format_icon_index_tsv(())),
        ("对象描述.tsv", format_description_tsv(())),
        ("图标完整性.txt", format_icon_completeness(())),
        ("描述完整性.txt", format_description_completeness(())),
        ("对象完整描述.tsv", format_object_text_tsv(empty_text)),
        ("掉落与获取关系.tsv", format_item_acquisition_tsv(empty_relations)),
        ("装备技能关系.tsv", format_equipment_skills_tsv(empty_relations)),
        ("关系完整性.txt", format_relation_completeness(empty_relations)),
    )
    for name, text in reports:
        (destination / name).write_text(text, encoding="utf-8")
    return finalize_map_manifest(destination, result, transaction_id)


def empty_result(
    fingerprint: SourceFingerprint,
    output_directory: str,
) -> MapBatchResult:
    """Build the matching zero-count immutable result."""
    return MapBatchResult(
        source=fingerprint,
        display_name=Path(fingerprint.path).stem,
        output_directory=output_directory,
        stage="published",
        state=MapBatchState.COMPLETE,
        first_error="",
        object_count=0,
        description_counts=(),
        named_icon_count=0,
        anonymous_icon_count=0,
        original_written_count=0,
        png_written_count=0,
        icon_failure_count=0,
        restricted_block_count=0,
        elapsed_ms=1,
        dependency_fingerprint=fingerprint.sha256,
    )
