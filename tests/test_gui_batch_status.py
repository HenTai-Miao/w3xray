"""Validated batch status projections."""

from dataclasses import replace
from pathlib import Path

import pytest

from tests.batch_publication_fixture import empty_result, publish_empty_result
from w3xtool.batch_global_publication import publish_global_generation
from w3xtool.batch_models import BATCH_SCHEMA_VERSION, BatchState, SourceFingerprint
from w3xtool.batch_status import (
    ArchiveIntegrity,
    KnowledgeEvidence,
    KnowledgeGapReason,
    PublicationResult,
)
from w3xtool.description_cache import format_description_cache_tsv
from w3xtool.description_cache_models import EMPTY_DESCRIPTION_CACHE
from w3xtool.gui_batch_status import (
    BatchStatusLoadError,
    batch_status_rows,
    load_batch_status,
)


def test_batch_status_rows_expose_three_independent_axes() -> None:
    # Given
    source = SourceFingerprint("/maps/a.w3x", 1, 1, "a" * 64)
    result = replace(
        empty_result(source, "地图/001_a"),
        publication_result=PublicationResult.PUBLISHED,
        archive_integrity=ArchiveIntegrity.COMPLETE,
        knowledge_evidence=KnowledgeEvidence.PARTIAL,
        knowledge_gap_reasons=(KnowledgeGapReason.ICON_UNBOUND,),
        unresolved_icon_count=1,
        unresolved_icon_reference_count=1,
        valid_icon_reference_count=1,
    )
    # When
    rows = batch_status_rows(BatchState(BATCH_SCHEMA_VERSION, (result,)))
    # Then
    assert rows[0].publication == "已发布"
    assert rows[0].archive == "完整"
    assert rows[0].knowledge == "部分"
    assert rows[0].knowledge_reasons == ("图标未绑定",)


def test_batch_status_loader_uses_a_validated_generation(tmp_path: Path) -> None:
    # Given
    source = SourceFingerprint("/maps/a.w3x", 1, 1, "a" * 64)
    result = publish_empty_result(1, source, str(tmp_path))
    state = BatchState(BATCH_SCHEMA_VERSION, (result,))
    generation = publish_global_generation(
        tmp_path, state, format_description_cache_tsv(EMPTY_DESCRIPTION_CACHE), ""
    )
    # When
    snapshot = load_batch_status(tmp_path)
    # Then
    assert snapshot.generation.generation_id == generation.generation_id
    assert snapshot.rows[0].publication == "已发布"


def test_batch_status_loader_rejects_an_invalid_current_pointer(tmp_path: Path) -> None:
    # Given
    (tmp_path / ".w3xray-global").mkdir()
    # When / Then
    with pytest.raises(BatchStatusLoadError, match="validated generation"):
        load_batch_status(tmp_path)
