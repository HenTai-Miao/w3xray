"""Fix contracts for terminal authority and typed evidence acceptance errors."""

from __future__ import annotations

from pathlib import Path

import pytest

import w3xtool.acceptance_batch as acceptance_batch
from tests.batch_global_evidence_fixture import (
    publish_nonempty_icon_result,
    terminal_result_with_evidence,
)
from tests.batch_publication_fixture import publish_empty_result
from w3xtool.batch_global_evidence_models import GlobalEvidenceError
from w3xtool.batch_global_publication import publish_global_generation
from w3xtool.batch_models import BATCH_SCHEMA_VERSION, BatchState, SourceFingerprint
from w3xtool.description_cache import format_description_cache_tsv
from w3xtool.description_cache_models import EMPTY_DESCRIPTION_CACHE


def test_terminal_result_is_axis_only_and_authority_remains_loadable(
    tmp_path: Path,
) -> None:
    # Given: one published evidence map and one failed map with non-zero gap counters.
    published = publish_nonempty_icon_result(
        1,
        SourceFingerprint("/maps/published.w3x", 3, 4, "a" * 64),
        str(tmp_path),
    )
    terminal = terminal_result_with_evidence(
        SourceFingerprint("/maps/terminal.w3x", 3, 4, "f" * 64)
    )
    state = BatchState(BATCH_SCHEMA_VERSION, (published, terminal))

    # When
    generation = publish_global_generation(tmp_path, state, _cache_text(), "")
    authority = acceptance_batch.require_authoritative_batch(tmp_path, state)

    # Then: terminal evidence is diagnostic-only and no map directory is required.
    assert authority.generation == generation
    assert tuple(result for result, _directory in authority.publications) == (
        published,
    )
    axes = (tmp_path / "三轴状态汇总.tsv").read_text(encoding="utf-8")
    gaps = (tmp_path / "图标缺口汇总.tsv").read_text(encoding="utf-8")
    candidates = (tmp_path / "图标候选绑定.tsv").read_text(encoding="utf-8")
    assert terminal.source.path in axes
    assert terminal.source.path not in gaps
    assert terminal.source.sha256 not in candidates
    assert len(generation.evidence.gaps) == published.unresolved_icon_count


@pytest.mark.parametrize("error", (GlobalEvidenceError("evidence"), OSError("disk")))
def test_acceptance_translates_fresh_collection_errors_with_chaining(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
) -> None:
    # Given
    result = publish_empty_result(
        1,
        SourceFingerprint("/maps/a.w3x", 3, 4, "a" * 64),
        str(tmp_path),
    )
    state = BatchState(BATCH_SCHEMA_VERSION, (result,))
    _ = publish_global_generation(tmp_path, state, _cache_text(), "")

    def fail_collection(*_args, **_kwargs):
        raise error

    monkeypatch.setattr(acceptance_batch, "collect_global_evidence", fail_collection)

    # When / Then
    with pytest.raises(acceptance_batch.BatchAcceptanceError) as captured:
        acceptance_batch.require_authoritative_batch(tmp_path, state)
    assert captured.value.__cause__ is error


def _cache_text() -> str:
    return format_description_cache_tsv(EMPTY_DESCRIPTION_CACHE)
