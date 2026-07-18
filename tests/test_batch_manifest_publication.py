"""Publication-integrity and report-evidence reuse contracts for map manifests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from tests.batch_manifest_fixture import (
    MANIFEST_TRANSACTION_ID,
    publish_manifest_fixture,
    write_empty_manifest_stage,
)
from tests.batch_schema_five_evidence_fixture import (
    EvidenceKind,
    schema_five_evidence_result,
    write_schema_five_evidence_reports,
)
from w3xtool.batch_manifest_validation import build_map_manifest, verify_map_publication


__test__ = False


def test_publication_validation_accepts_exact_manifest_fixture(tmp_path: Path) -> None:
    # Given: a manifest and ownership marker bind an untouched directory.
    result = publish_manifest_fixture(tmp_path)

    # When: resume validation re-reads every file and report.
    validation = verify_map_publication(tmp_path, result)

    # Then: the publication is reusable and returns its proven byte total.
    assert validation.valid
    assert validation.code == "valid"
    assert validation.manifest_sha256 == result.manifest_sha256
    assert validation.published_bytes > 0
    assert validation.reports.payloads == ()


def test_publication_validation_returns_only_requested_verified_reports(
    tmp_path: Path,
) -> None:
    # Given
    result = publish_manifest_fixture(tmp_path)

    # When
    validation = verify_map_publication(
        tmp_path,
        result,
        requested_reports=frozenset(("图标索引.tsv",)),
    )

    # Then
    assert validation.valid
    assert tuple(item.relative_path for item in validation.reports.payloads) == (
        "图标索引.tsv",
    )
    assert (
        validation.reports.content("图标索引.tsv")
        == (tmp_path / "图标索引.tsv").read_bytes()
    )


def test_publication_validation_rejects_same_size_tampering(tmp_path: Path) -> None:
    # Given: a valid publication whose report bytes are replaced at equal size.
    result = publish_manifest_fixture(tmp_path)
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
    result = publish_manifest_fixture(tmp_path)
    (tmp_path / "not-listed.bin").write_bytes(b"extra")

    # When / Then: the exact file set no longer matches the manifest.
    validation = verify_map_publication(tmp_path, result)
    assert not validation.valid
    assert validation.code == "artifact_set_mismatch"


def test_publication_validation_rejects_symlink_artifact(tmp_path: Path) -> None:
    # Given: a listed report is replaced by a symlink after publication.
    result = publish_manifest_fixture(tmp_path)
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
    result = publish_manifest_fixture(tmp_path)
    mismatched = replace(result, original_written_count=1)

    # When / Then: report schema/count reconciliation rejects the state.
    validation = verify_map_publication(tmp_path, mismatched)
    assert not validation.valid
    assert validation.code == "result_summary_mismatch"


@pytest.mark.parametrize(
    ("kind", "expected_detail"),
    (
        ("current_text", "current_source_unavailable_count"),
        ("relation", "relation_partial_count"),
        ("icon_diagnostic", "client_unavailable_icon_count"),
    ),
)
def test_publication_validation_rejects_schema_five_evidence_report_drift(
    tmp_path: Path,
    kind: EvidenceKind,
    expected_detail: str,
) -> None:
    # Given: aggregate reports agree but one current/evidence dimension drifts.
    result = schema_five_evidence_result(write_empty_manifest_stage(tmp_path), kind)
    write_schema_five_evidence_reports(tmp_path, kind)
    published = publish_manifest_fixture(tmp_path, result)

    # When: reuse validation reconciles the manifest with required reports.
    validation = verify_map_publication(tmp_path, published)

    # Then: metadata hash validity cannot make report drift reusable.
    assert not validation.valid
    assert validation.code == "result_summary_mismatch"
    assert validation.detail == expected_detail


def test_manifest_builder_rejects_duplicate_casefolded_paths(tmp_path: Path) -> None:
    # Given: a POSIX backslash filename aliases a nested Windows path.
    result = write_empty_manifest_stage(tmp_path)
    nested = tmp_path / "nested" / "value.txt"
    nested.parent.mkdir()
    nested.write_text("a", encoding="utf-8")
    (tmp_path / "nested\\value.txt").write_text("b", encoding="utf-8")

    # When / Then: a Windows-unsafe manifest is never emitted.
    with pytest.raises(ValueError, match="unsafe|duplicate"):
        build_map_manifest(tmp_path, result, MANIFEST_TRANSACTION_ID)
