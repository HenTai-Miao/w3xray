"""Immutable per-map content manifest and resume validation contracts."""

from __future__ import annotations

from dataclasses import replace
import hashlib
from pathlib import Path

import pytest

from w3xtool.batch_manifest_io import (
    format_map_manifest,
    format_ownership_record,
    parse_map_manifest,
)
from w3xtool.batch_manifest_models import (
    CONTENT_MANIFEST_NAME,
    OWNERSHIP_MARKER_NAME,
    OwnershipRecord,
)
from w3xtool.batch_manifest_validation import (
    build_map_manifest,
    verify_map_publication,
)
from w3xtool.batch_models import MapBatchResult, MapBatchState, SourceFingerprint
from w3xtool.batch_reports import (
    format_description_completeness,
    format_description_tsv,
    format_icon_index_tsv,
    format_map_summary,
)
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
from w3xtool.item_relation_models import ItemRelationIndex, ItemRelationKind
from w3xtool.object_text_exports import format_object_text_tsv
from w3xtool.object_text_models import ObjectTextIndex, ObjectTextState


_TRANSACTION_ID = "1" * 32


def test_manifest_round_trip_binds_every_regular_artifact(tmp_path: Path) -> None:
    # Given: a complete stage with reports plus one physical PNG.
    result = _write_empty_stage(tmp_path)
    icon = tmp_path / "图标" / "PNG" / "匿名" / "x.png"
    icon.parent.mkdir(parents=True)
    icon.write_bytes(b"\x89PNG\r\n\x1a\n")

    # When: the deterministic content manifest is built and parsed.
    manifest = build_map_manifest(tmp_path, result, _TRANSACTION_ID)
    text = format_map_manifest(manifest)
    parsed = parse_map_manifest(text)

    # Then: every artifact is bound by stable path, size, and SHA-256.
    assert parsed == manifest
    paths = {item.relative_path for item in parsed.artifacts}
    assert "地图摘要.txt" in paths
    assert "图标未解析.tsv" in paths
    assert "图标/PNG/匿名/x.png" in paths
    assert CONTENT_MANIFEST_NAME not in paths
    assert OWNERSHIP_MARKER_NAME not in paths
    assert parsed.total_size == sum(item.size for item in parsed.artifacts)


def test_manifest_round_trip_retains_every_split_icon_counter(
    tmp_path: Path,
) -> None:
    # Given
    result = replace(
        _write_empty_stage(tmp_path),
        valid_icon_reference_count=9,
        resolved_icon_reference_count=4,
        filtered_icon_field_count=3,
        unresolved_icon_count=2,
        unresolved_icon_reference_count=5,
        anonymous_read_failure_count=1,
        original_write_failure_count=2,
        png_failure_count=3,
    )

    # When
    parsed = parse_map_manifest(
        format_map_manifest(build_map_manifest(tmp_path, result, _TRANSACTION_ID))
    )

    # Then
    assert parsed.result.valid_icon_reference_count == 9
    assert parsed.result.resolved_icon_reference_count == 4
    assert parsed.result.filtered_icon_field_count == 3
    assert parsed.result.unresolved_icon_count == 2
    assert parsed.result.unresolved_icon_reference_count == 5
    assert parsed.result.anonymous_read_failure_count == 1
    assert parsed.result.original_write_failure_count == 2
    assert parsed.result.png_failure_count == 3


def test_publication_validation_accepts_exact_manifest_fixture(tmp_path: Path) -> None:
    # Given: a manifest and ownership marker bind an untouched directory.
    result = _publish_manifest_fixture(tmp_path)

    # When: resume validation re-reads every file and report.
    validation = verify_map_publication(tmp_path, result)

    # Then: the publication is reusable and returns its proven byte total.
    assert validation.valid
    assert validation.code == "valid"
    assert validation.manifest_sha256 == result.manifest_sha256
    assert validation.published_bytes > 0


def test_publication_validation_rejects_same_size_tampering(tmp_path: Path) -> None:
    # Given: a valid publication whose report bytes are replaced at equal size.
    result = _publish_manifest_fixture(tmp_path)
    report = tmp_path / "地图摘要.txt"
    report.write_bytes(b"X" * report.stat().st_size)

    # When: validation hashes the report instead of trusting existence or size.
    validation = verify_map_publication(tmp_path, result)

    # Then: content tampering prevents reuse.
    assert not validation.valid
    assert validation.code == "artifact_hash_mismatch"
    assert validation.relative_path == "地图摘要.txt"


def test_publication_validation_rejects_unlisted_regular_file(tmp_path: Path) -> None:
    # Given: a valid publication gains an uncommitted regular file.
    result = _publish_manifest_fixture(tmp_path)
    (tmp_path / "not-listed.bin").write_bytes(b"extra")

    # When / Then: the exact file set no longer matches the manifest.
    validation = verify_map_publication(tmp_path, result)
    assert not validation.valid
    assert validation.code == "artifact_set_mismatch"


def test_publication_validation_rejects_symlink_artifact(
    tmp_path: Path,
) -> None:
    # Given: a listed report is replaced by a symlink after publication.
    result = _publish_manifest_fixture(tmp_path)
    report = tmp_path / "地图摘要.txt"
    target = tmp_path.parent / "outside-summary.txt"
    target.write_bytes(report.read_bytes())
    report.unlink()
    report.symlink_to(target)

    # When / Then: validation never follows the link.
    validation = verify_map_publication(tmp_path, result)
    assert not validation.valid
    assert validation.code == "unsafe_artifact"


def test_publication_validation_rejects_report_count_drift(tmp_path: Path) -> None:
    # Given: a manifest is internally consistent but its expected result lies.
    result = _publish_manifest_fixture(tmp_path)
    mismatched = replace(result, original_written_count=1)

    # When / Then: report schema/count reconciliation rejects the state.
    validation = verify_map_publication(tmp_path, mismatched)
    assert not validation.valid
    assert validation.code == "result_summary_mismatch"


def test_manifest_builder_rejects_duplicate_casefolded_paths(tmp_path: Path) -> None:
    # Given: a POSIX backslash filename aliases a nested Windows path.
    result = _write_empty_stage(tmp_path)
    nested = tmp_path / "nested" / "value.txt"
    nested.parent.mkdir()
    nested.write_text("a", encoding="utf-8")
    (tmp_path / "nested\\value.txt").write_text("b", encoding="utf-8")

    # When / Then: a Windows-unsafe manifest is never emitted.
    with pytest.raises(ValueError, match="unsafe|duplicate"):
        build_map_manifest(tmp_path, result, _TRANSACTION_ID)


def _publish_manifest_fixture(root: Path) -> MapBatchResult:
    result = _write_empty_stage(root)
    manifest = build_map_manifest(root, result, _TRANSACTION_ID)
    manifest_text = format_map_manifest(manifest)
    (root / CONTENT_MANIFEST_NAME).write_text(manifest_text, encoding="utf-8")
    manifest_digest = hashlib.sha256(manifest_text.encode()).hexdigest()
    ownership = OwnershipRecord(
        schema_version=1,
        source_sha256=result.source.sha256,
        manifest_sha256=manifest_digest,
        transaction_id=_TRANSACTION_ID,
    )
    (root / OWNERSHIP_MARKER_NAME).write_text(
        format_ownership_record(ownership), encoding="utf-8"
    )
    return replace(
        result,
        manifest_sha256=manifest_digest,
        published_bytes=manifest.total_size,
    )


def _write_empty_stage(root: Path) -> MapBatchResult:
    result = _result()
    empty_text = ObjectTextIndex.build(())
    empty_relations = ItemRelationIndex.build(())
    artifacts = (
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
    for name, text in artifacts:
        (root / name).write_text(text, encoding="utf-8")
    return result


def _result() -> MapBatchResult:
    return MapBatchResult(
        source=SourceFingerprint("/maps/sample.w3x", 3, 4, "a" * 64),
        display_name="sample",
        output_directory="地图/001_sample_aaaaaaaa",
        stage="published",
        state=MapBatchState.COMPLETE,
        first_error="",
        object_count=0,
        description_counts=tuple((state.value, 0) for state in ObjectTextState),
        named_icon_count=0,
        anonymous_icon_count=0,
        original_written_count=0,
        png_written_count=0,
        icon_failure_count=0,
        restricted_block_count=0,
        elapsed_ms=1,
        relation_counts=tuple((kind.value, 0) for kind in ItemRelationKind),
        relation_incomplete_count=0,
        dependency_fingerprint="b" * 64,
        manifest_sha256="",
        published_bytes=0,
        peak_rss_bytes=0,
    )
