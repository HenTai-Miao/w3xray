"""Small manifest-valid batch publication fixture shared by resume tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import assert_never

from w3xtool.batch_tsv import format_tsv_rows
from w3xtool.batch_manifest_models import CONTENT_MANIFEST_NAME, OWNERSHIP_MARKER_NAME
from w3xtool.batch_map_manifest import finalize_map_manifest
from w3xtool.batch_models import MapBatchResult, MapBatchState, SourceFingerprint
from w3xtool.batch_reports import (
    format_description_completeness,
    format_description_tsv,
    format_icon_index_tsv,
    format_map_summary,
)
from w3xtool.batch_status import PublicationResult, derive_batch_axes
from w3xtool.icon_evidence_exports import (
    format_icon_integrity,
    format_unresolved_icon_tsv,
)
from w3xtool.icon_evidence_index import empty_icon_evidence_index
from w3xtool.item_relation_exports import (
    format_equipment_skills_tsv,
    format_item_acquisition_tsv,
    format_relation_completeness,
)
from w3xtool.item_relation_models import ItemRelationIndex
from w3xtool.object_text_exports import format_object_text_tsv
from w3xtool.object_text_exports import OBJECT_TEXT_REPORT_HEADER
from w3xtool.object_text_models import ObjectTextIndex
from w3xtool.object_text_roles import semantic_field_for_role


type PublishedTextValue = tuple[str, str] | tuple[str, str, str]


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
        ("图标未解析.tsv", format_unresolved_icon_tsv(empty_icon_evidence_index())),
        ("对象描述.tsv", format_description_tsv(())),
        (
            "图标完整性.txt",
            format_icon_integrity(empty_icon_evidence_index(), ()),
        ),
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
    axes = derive_batch_axes(
        PublicationResult.PUBLISHED,
        raw_blocks=0,
        damaged_blocks=0,
        restricted_blocks=0,
        icon_gaps=0,
        current_text_states=(),
        relation_partial_count=0,
        unresolved_endpoint_count=0,
    )
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
        publication_result=axes.publication,
        archive_integrity=axes.archive,
        knowledge_evidence=axes.knowledge,
        knowledge_gap_reasons=axes.knowledge_reasons,
        raw_block_count=0,
        damaged_block_count=0,
        valid_icon_reference_count=0,
        resolved_icon_reference_count=0,
        filtered_icon_field_count=0,
        unresolved_icon_count=0,
        unresolved_icon_reference_count=0,
        anonymous_read_failure_count=0,
        original_write_failure_count=0,
        png_failure_count=0,
        dependency_fingerprint=fingerprint.sha256,
    )


def publish_client_fill_result(
    index: int,
    fingerprint: SourceFingerprint,
    output_root: str,
    *,
    values: tuple[PublishedTextValue, ...] = (("扩展提示", "完整说明"),),
    category: str = "物品",
    base_id: str = "ratf",
    object_name: str = "戒指",
) -> MapBatchResult:
    """Publish a manifest-valid fixture containing trusted complete-text rows."""
    relative = f"地图/{index:03d}_{fingerprint.sha256[:8]}"
    destination = Path(output_root, relative)
    destination.mkdir(parents=True, exist_ok=True)
    result = empty_result(fingerprint, relative)
    transaction_id = f"{index:032x}"
    _ = write_empty_publication(destination, result, transaction_id)
    (destination / CONTENT_MANIFEST_NAME).unlink()
    (destination / OWNERSHIP_MARKER_NAME).unlink()
    rows: list[tuple[str, ...]] = [OBJECT_TEXT_REPORT_HEADER]
    for evidence_index, value in enumerate(values, start=1):
        match value:
            case (role, raw_value):
                semantic_field = semantic_field_for_role(role)
            case (role, semantic_field, raw_value):
                pass
            case unreachable:
                assert_never(unreachable)
        rows.append(
            (
                category,
                base_id,
                base_id,
                object_name,
                "否",
                role,
                semantic_field,
                semantic_field,
                "提示文本",
                "",
                raw_value,
                raw_value,
                "客户端",
                "Units\\ItemStrings.txt",
                "200",
                "客户端补全",
                "否",
                "",
                "是",
                "最高优先级唯一值",
                str(evidence_index),
            )
        )
    (destination / "对象完整描述.tsv").write_text(
        format_tsv_rows(rows),
        encoding="utf-8",
        newline="",
    )
    finalized = replace(
        result,
        description_counts=(("客户端补全", len(values)),),
    )
    return finalize_map_manifest(destination, finalized, transaction_id)
