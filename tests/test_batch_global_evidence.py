"""Verified global icon aggregation and canonical payload reconciliation."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.batch_publication_fixture import publish_empty_result
from w3xtool.batch_global_evidence import GlobalEvidenceError, collect_global_evidence
from w3xtool.batch_models import BATCH_SCHEMA_VERSION, BatchState, MapBatchResult
from w3xtool.batch_models import SourceFingerprint
from w3xtool.description_cache import format_description_cache_tsv
from w3xtool.description_cache_models import EMPTY_DESCRIPTION_CACHE


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
