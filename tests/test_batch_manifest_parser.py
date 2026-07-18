"""Wire and semantic parser contracts for immutable map manifests."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pytest

from tests.batch_manifest_fixture import (
    MANIFEST_TRANSACTION_ID,
    write_empty_manifest_stage,
)
from w3xtool.batch_manifest_io import format_map_manifest, parse_map_manifest
from w3xtool.batch_manifest_models import (
    BatchManifestFormatError,
    CONTENT_MANIFEST_NAME,
    OWNERSHIP_MARKER_NAME,
)
from w3xtool.batch_manifest_validation import build_map_manifest
from w3xtool.batch_models import MapBatchState
from w3xtool.batch_status import (
    ArchiveIntegrity,
    KnowledgeEvidence,
    KnowledgeGapReason,
    PublicationResult,
)


__test__ = False


def test_manifest_round_trip_binds_every_regular_artifact(tmp_path: Path) -> None:
    # Given: a complete stage with reports plus one physical PNG.
    result = write_empty_manifest_stage(tmp_path)
    icon = tmp_path / "图标" / "PNG" / "匿名" / "x.png"
    icon.parent.mkdir(parents=True)
    icon.write_bytes(b"\x89PNG\r\n\x1a\n")

    # When: the deterministic content manifest is built and parsed.
    manifest = build_map_manifest(tmp_path, result, MANIFEST_TRANSACTION_ID)
    parsed = parse_map_manifest(format_map_manifest(manifest))

    # Then: every artifact is bound by stable path, size, and SHA-256.
    assert parsed == manifest
    paths = {item.relative_path for item in parsed.artifacts}
    assert "地图摘要.txt" in paths
    assert "图标未解析.tsv" in paths
    assert "图标/PNG/匿名/x.png" in paths
    assert CONTENT_MANIFEST_NAME not in paths
    assert OWNERSHIP_MARKER_NAME not in paths
    assert parsed.total_size == sum(item.size for item in parsed.artifacts)
    assert parsed.result.publication_result is PublicationResult.PUBLISHED
    assert parsed.result.archive_integrity is ArchiveIntegrity.COMPLETE
    assert parsed.result.knowledge_evidence is KnowledgeEvidence.COMPLETE
    assert parsed.result.raw_block_count == 0
    assert parsed.result.damaged_block_count == 0


def test_manifest_round_trip_retains_every_split_icon_counter(tmp_path: Path) -> None:
    # Given
    result = replace(
        write_empty_manifest_stage(tmp_path),
        valid_icon_reference_count=9,
        resolved_icon_reference_count=4,
        filtered_icon_field_count=3,
        unresolved_icon_count=2,
        unresolved_icon_reference_count=5,
        icon_failure_count=6,
        anonymous_read_failure_count=1,
        original_write_failure_count=2,
        png_failure_count=3,
        state=MapBatchState.PARTIAL,
        knowledge_evidence=KnowledgeEvidence.PARTIAL,
        knowledge_gap_reasons=(KnowledgeGapReason.ICON_UNBOUND,),
    )

    # When
    parsed = parse_map_manifest(
        format_map_manifest(
            build_map_manifest(tmp_path, result, MANIFEST_TRANSACTION_ID)
        )
    )

    # Then
    assert parsed.result.valid_icon_reference_count == 9
    assert parsed.result.resolved_icon_reference_count == 4
    assert parsed.result.filtered_icon_field_count == 3
    assert parsed.result.unresolved_icon_count == 2
    assert parsed.result.unresolved_icon_reference_count == 5
    assert parsed.result.icon_failure_count == 6
    assert parsed.result.anonymous_read_failure_count == 1
    assert parsed.result.original_write_failure_count == 2
    assert parsed.result.png_failure_count == 3


def test_manifest_parser_rejects_legacy_state_that_disagrees_with_axes(
    tmp_path: Path,
) -> None:
    # Given: a complete three-axis result whose legacy compatibility field drifts.
    manifest = build_map_manifest(
        tmp_path, write_empty_manifest_stage(tmp_path), MANIFEST_TRANSACTION_ID
    )
    payload = json.loads(format_map_manifest(manifest))
    payload["result"]["state"] = MapBatchState.PARTIAL.value

    # When / Then: the immutable manifest rejects contradictory state metadata.
    with pytest.raises(BatchManifestFormatError, match="state|axes"):
        parse_map_manifest(json.dumps(payload))


def test_manifest_parser_rejects_icon_gap_claimed_as_complete_knowledge(
    tmp_path: Path,
) -> None:
    # Given: the manifest stores an unresolved normalized icon path.
    manifest = build_map_manifest(
        tmp_path, write_empty_manifest_stage(tmp_path), MANIFEST_TRANSACTION_ID
    )
    payload = json.loads(format_map_manifest(manifest))
    payload["result"].update(
        {
            "unresolved_icon_count": 1,
            "unresolved_icon_reference_count": 1,
            "valid_icon_reference_count": 1,
        }
    )

    # When / Then: complete knowledge cannot discard the derived icon reason.
    with pytest.raises(
        BatchManifestFormatError,
        match="knowledge.*reason|reason.*knowledge",
    ):
        parse_map_manifest(json.dumps(payload))


@pytest.mark.parametrize(
    ("updates", "detail"),
    (
        (
            {
                "client_unavailable_icon_count": 1,
                "state": MapBatchState.PARTIAL.value,
                "knowledge_evidence": KnowledgeEvidence.PARTIAL.value,
                "knowledge_gap_reasons": [KnowledgeGapReason.CLIENT_MISSING.value],
            },
            "client unavailable icon",
        ),
        (
            {
                "relation_partial_count": 1,
                "state": MapBatchState.PARTIAL.value,
                "knowledge_evidence": KnowledgeEvidence.PARTIAL.value,
                "knowledge_gap_reasons": [KnowledgeGapReason.RELATION_PARTIAL.value],
            },
            "relation evidence counts",
        ),
        (
            {
                "current_source_conflict_count": 1,
                "state": MapBatchState.PARTIAL.value,
                "knowledge_evidence": KnowledgeEvidence.PARTIAL.value,
                "knowledge_gap_reasons": [
                    KnowledgeGapReason.TRUE_SOURCE_CONFLICT.value
                ],
            },
            "current text evidence",
        ),
        (
            {
                "unresolved_icon_count": 1,
                "state": MapBatchState.PARTIAL.value,
                "knowledge_evidence": KnowledgeEvidence.PARTIAL.value,
                "knowledge_gap_reasons": [KnowledgeGapReason.ICON_UNBOUND.value],
            },
            "unresolved icon count",
        ),
    ),
)
def test_manifest_parser_rejects_impossible_persisted_evidence_counts(
    tmp_path: Path,
    updates: dict[str, str | int | list[str]],
    detail: str,
) -> None:
    # Given: one immutable publication summary contains impossible evidence.
    manifest = build_map_manifest(
        tmp_path, write_empty_manifest_stage(tmp_path), MANIFEST_TRANSACTION_ID
    )
    payload = json.loads(format_map_manifest(manifest))
    payload["result"].update(updates)

    # When / Then: manifest parsing rejects it before reuse validation.
    with pytest.raises(BatchManifestFormatError, match=detail):
        parse_map_manifest(json.dumps(payload))
