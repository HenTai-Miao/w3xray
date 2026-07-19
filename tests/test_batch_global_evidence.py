"""Verified global icon aggregation and canonical payload reconciliation."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

import w3xtool.batch_global_evidence as global_evidence
from tests.batch_global_evidence_fixture import (
    GAP_PATH,
    NAMED_PATH,
    publish_nonempty_icon_result,
)
from tests.batch_publication_fixture import empty_result, publish_empty_result
from tests.real_map_text_acceptance import read_tsv_text
from w3xtool.batch_global_evidence import GlobalEvidenceError, collect_global_evidence
from w3xtool.batch_manifest_models import CONTENT_MANIFEST_NAME, OWNERSHIP_MARKER_NAME
from w3xtool.batch_map_manifest import finalize_map_manifest
from w3xtool.batch_models import BATCH_SCHEMA_VERSION, BatchState, MapBatchResult
from w3xtool.batch_models import SourceFingerprint
from w3xtool.batch_tsv import format_tsv_rows
from w3xtool.description_cache import format_description_cache_tsv
from w3xtool.description_cache_models import EMPTY_DESCRIPTION_CACHE
from w3xtool.icon_evidence_models import IconGapReason


def test_axis_status_exposes_source_coverage_gap_count() -> None:
    # Given
    source = SourceFingerprint("/maps/a.w3x", 1, 1, "a" * 64)
    result = replace(empty_result(source, "地图/001_a"), source_coverage_gap_count=2)
    state = BatchState(BATCH_SCHEMA_VERSION, (result,))

    # When
    from w3xtool.batch_global_evidence_reports import format_axis_status_tsv

    table = read_tsv_text(format_axis_status_tsv(state))

    # Then
    column = table.header.index("源覆盖缺口")
    assert table.rows[0][column] == "2"


def test_global_evidence_reads_only_verified_map_publications(
    tmp_path: Path,
) -> None:
    # Given
    state, first, second = _publish_two_empty_maps(tmp_path)

    # When
    evidence = collect_global_evidence(tmp_path, state)

    # Then
    assert len(evidence.gaps) == sum(
        result.unresolved_icon_count for result in state.results
    )
    assert {row.map_sha256 for row in evidence.gaps} <= {
        first.source.sha256,
        second.source.sha256,
    }


def test_global_evidence_rejects_a_tampered_map_publication(tmp_path: Path) -> None:
    # Given
    state, first, _second = _publish_two_empty_maps(tmp_path)
    report = tmp_path / first.output_directory / "图标未解析.tsv"
    report.write_text("tampered\n", encoding="utf-8")

    # When / Then
    with pytest.raises(GlobalEvidenceError, match="invalid map publication"):
        collect_global_evidence(tmp_path, state)


def test_global_evidence_parses_nonempty_manifest_bound_rows(tmp_path: Path) -> None:
    # Given
    result = publish_nonempty_icon_result(
        1,
        SourceFingerprint("/maps/a.w3x", 3, 4, "a" * 64),
        str(tmp_path),
    )

    # When
    evidence = collect_global_evidence(
        tmp_path, BatchState(BATCH_SCHEMA_VERSION, (result,))
    )

    # Then
    assert (len(evidence.gaps), len(evidence.resolved), len(evidence.anonymous)) == (
        1,
        1,
        1,
    )
    assert evidence.gaps[0].normalized_path == GAP_PATH
    assert evidence.gaps[0].reference_count == 1
    assert evidence.gaps[0].references[0].object_id == "A001"
    assert evidence.resolved[0].normalized_path == NAMED_PATH
    assert evidence.resolved[0].content_sha256 == "c" * 64
    assert evidence.anonymous[0].block_index == 17
    assert evidence.anonymous[0].content_sha256 == "d" * 64


def test_global_evidence_round_trips_an_invalid_reference_without_a_path(
    tmp_path: Path,
) -> None:
    # Given: the map report contains a legitimate structured invalid reference.
    result = publish_nonempty_icon_result(
        1,
        SourceFingerprint("/maps/a.w3x", 3, 4, "a" * 64),
        str(tmp_path),
        gap_path="",
        gap_reason=IconGapReason.INVALID_REFERENCE,
    )
    state = BatchState(BATCH_SCHEMA_VERSION, (result,))

    # When: verified map evidence is aggregated and serialized globally.
    from w3xtool.batch_global_evidence_reports import (
        format_global_icon_gaps_tsv,
        parse_global_icon_gaps_tsv,
    )

    evidence = collect_global_evidence(tmp_path, state)
    restored = parse_global_icon_gaps_tsv(format_global_icon_gaps_tsv(evidence))

    # Then: no path is invented and the reason/reference evidence remains exact.
    assert restored == evidence.gaps
    assert restored[0].normalized_path == ""
    assert restored[0].reason is IconGapReason.INVALID_REFERENCE


def test_global_evidence_observes_the_verified_report_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: replacement happens only after the real verification boundary returns.
    result = publish_nonempty_icon_result(
        1,
        SourceFingerprint("/maps/a.w3x", 3, 4, "a" * 64),
        str(tmp_path),
    )
    report = tmp_path / result.output_directory / "图标未解析.tsv"
    verify = global_evidence.verify_map_publication

    def replace_after_verification(*args, **kwargs):
        validation = verify(*args, **kwargs)
        if validation.valid:
            report.write_text("replacement\n", encoding="utf-8")
        return validation

    monkeypatch.setattr(
        global_evidence, "verify_map_publication", replace_after_verification
    )

    # When
    evidence = collect_global_evidence(
        tmp_path, BatchState(BATCH_SCHEMA_VERSION, (result,))
    )

    # Then: aggregation uses the original verified bytes, never the replacement.
    assert tuple(row.normalized_path for row in evidence.gaps) == (GAP_PATH,)


@pytest.mark.parametrize("kind", ("具名", "匿名"))
def test_global_evidence_rejects_duplicate_icon_identities(
    tmp_path: Path,
    kind: str,
) -> None:
    # Given: the manifest and declared counts bind two exact duplicate rows.
    result = publish_nonempty_icon_result(
        1,
        SourceFingerprint("/maps/a.w3x", 3, 4, "a" * 64),
        str(tmp_path),
    )
    result = _duplicate_icon_row(tmp_path / result.output_directory, result, kind)

    # When / Then
    with pytest.raises(GlobalEvidenceError, match="duplicate"):
        collect_global_evidence(tmp_path, BatchState(BATCH_SCHEMA_VERSION, (result,)))


@pytest.mark.parametrize("count_field", ("named_icon_count", "anonymous_icon_count"))
def test_global_evidence_enforces_exact_icon_row_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    count_field: str,
) -> None:
    # Given: verified report bytes contain one row while supplied state claims two.
    published = publish_nonempty_icon_result(
        1,
        SourceFingerprint("/maps/a.w3x", 3, 4, "a" * 64),
        str(tmp_path),
    )
    verify = global_evidence.verify_map_publication

    def verify_bound_publication(directory, _expected, **kwargs):
        return verify(directory, published, **kwargs)

    monkeypatch.setattr(
        global_evidence, "verify_map_publication", verify_bound_publication
    )
    supplied = replace(published, **{count_field: 2})

    # When / Then
    with pytest.raises(GlobalEvidenceError, match="counts"):
        collect_global_evidence(tmp_path, BatchState(BATCH_SCHEMA_VERSION, (supplied,)))


def test_global_gap_rows_reconcile_paths_references_and_axes(
    tmp_path: Path,
) -> None:
    # Given
    from w3xtool.batch_global_evidence_reports import (
        format_axis_status_tsv,
        parse_global_icon_gaps_tsv,
    )
    from w3xtool.batch_global_payloads import build_global_payloads

    state, _first, _second = _publish_two_empty_maps(tmp_path)
    cache_text = format_description_cache_tsv(EMPTY_DESCRIPTION_CACHE)

    # When
    bundle = build_global_payloads(tmp_path, state, cache_text, "")
    gaps = parse_global_icon_gaps_tsv(bundle.payloads["图标缺口汇总.tsv"])

    # Then
    assert len(gaps) == sum(result.unresolved_icon_count for result in state.results)
    assert sum(row.reference_count for row in gaps) == sum(
        result.unresolved_icon_reference_count for result in state.results
    )
    assert bundle.payloads["三轴状态汇总.tsv"] == format_axis_status_tsv(state)


def _publish_two_empty_maps(
    output_root: Path,
) -> tuple[BatchState, MapBatchResult, MapBatchResult]:
    first_source = SourceFingerprint("/maps/a.w3x", 1, 1, "a" * 64)
    second_source = SourceFingerprint("/maps/b.w3x", 1, 1, "b" * 64)
    first = publish_empty_result(1, first_source, str(output_root))
    second = publish_empty_result(2, second_source, str(output_root))
    return BatchState(BATCH_SCHEMA_VERSION, (first, second)), first, second


def _duplicate_icon_row(
    directory: Path,
    result: MapBatchResult,
    kind: str,
) -> MapBatchResult:
    table = read_tsv_text((directory / "图标索引.tsv").read_text(encoding="utf-8"))
    row = next(item for item in table.rows if item[0] == kind)
    (directory / "图标索引.tsv").write_text(
        format_tsv_rows((table.header, *table.rows, row)),
        encoding="utf-8",
        newline="",
    )
    updates = {
        "named_icon_count": result.named_icon_count + int(kind == "具名"),
        "anonymous_icon_count": result.anonymous_icon_count + int(kind == "匿名"),
        "original_written_count": result.original_written_count + 1,
        "png_written_count": result.png_written_count + 1,
    }
    if kind == "匿名":
        integrity = directory / "图标完整性.txt"
        integrity.write_text(
            integrity.read_text(encoding="utf-8").replace("匿名载荷：1", "匿名载荷：2"),
            encoding="utf-8",
        )
    (directory / CONTENT_MANIFEST_NAME).unlink()
    (directory / OWNERSHIP_MARKER_NAME).unlink()
    return finalize_map_manifest(
        directory,
        replace(result, **updates),
        "f" * 32,
    )
