"""Ordered faults entering the terminal held-stage locator."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Never, assert_never

import pytest

from tests.description_cache_publication_fixture import (
    assert_failure_order,
    bound_stage,
    rename_in_parent,
)
from w3xtool import description_cache_publication_stage_location as stage_location
from w3xtool import description_cache_publication_stage_retention as stage_retention
from w3xtool.description_cache_publication_errors import (
    PublicationCommitContextError,
)
from w3xtool.description_cache_publication_models import RetainedCacheRole
from w3xtool.description_cache_publication_retention_names import RetainedCacheNames


type RetentionLocation = Literal["foreign", "failed-stage"]


def test_location_parent_fault_follows_prior_failure_without_replacing_cause(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a stable held output and one already-known exact failure.
    stage = tmp_path / "stage"
    output = tmp_path / "trusted"
    stage.mkdir()
    names = RetainedCacheNames(tmp_path, "1" * 32)
    primary = RuntimeError("prior location failure")
    parent_fault = OSError("terminal parent proof")
    parent_error = PublicationCommitContextError(
        "terminal parent proof; NEEDS_CONTEXT",
        failures=(primary, parent_fault),
    )
    parent_error.__cause__ = parent_fault

    def fail_parent(
        _descriptor: int,
        _parent: Path,
        _expected: tuple[int, int],
    ) -> None:
        raise parent_error

    monkeypatch.setattr(stage_retention, "require_parent_identity", fail_parent)

    # When: the caller's final parent proof funnels the fault through the locator.
    with bound_stage(stage) as bound:
        with pytest.raises(PublicationCommitContextError) as raised:
            _ = stage_retention.retain_stage(
                bound,
                output,
                names,
                rename_in_parent,
                lambda _descriptor: None,
                (),
                (),
            )

    # Then: prior, syscall, and typed parent objects remain in exact order.
    assert_failure_order(raised.value, (primary, parent_fault, parent_error))
    assert raised.value.__cause__ is None
    assert parent_error.__cause__ is parent_fault


def test_location_stage_read_failures_pass_through_in_existing_order(
    tmp_path: Path,
) -> None:
    # Given: the stage-read boundary already has an initiating and read fault.
    stage = tmp_path / "stage"
    output = tmp_path / "trusted"
    stage.mkdir()
    names = RetainedCacheNames(tmp_path, "2" * 32)
    primary = RuntimeError("prior location failure")
    read_fault = OSError("stage named read")

    # When: the forced locator performs both scans after that stage-read boundary.
    with bound_stage(stage) as bound:
        _ = stage.rename(output)
        with pytest.raises(PublicationCommitContextError) as raised:
            _ = stage_location.locate_consumed_stage(
                bound,
                output,
                names,
                prior_failures=(primary, read_fault),
                detail="stage read failed",
            )

    # Then: the locator appends no synthetic substitute to the exact pair.
    assert_failure_order(raised.value, (primary, read_fault))


@pytest.mark.parametrize("location", ("foreign", "failed-stage"))
def test_location_retention_faults_follow_existing_failure_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    location: RetentionLocation,
) -> None:
    # Given: foreign or held-stage retention returns one typed ordered failure.
    stage = tmp_path / "stage"
    output = tmp_path / "trusted"
    displaced = tmp_path / "displaced-held"
    stage.mkdir()
    names = RetainedCacheNames(tmp_path, "3" * 32)
    primary = RuntimeError("prior retention failure")
    retention_fault = OSError(f"{location} retention")
    retention_error = PublicationCommitContextError(
        "retention fault; NEEDS_CONTEXT",
        failures=(primary, retention_fault),
    )
    retention_error.__cause__ = retention_fault

    def fail_retention(
        *_args: int | Path | tuple[int, int] | RetainedCacheNames | RetainedCacheRole,
    ) -> Never:
        raise retention_error

    monkeypatch.setattr(stage_retention, "retain_durably", fail_retention)

    # When: retain_stage funnels the typed outcome through the full locator.
    with bound_stage(stage) as bound:
        match location:
            case "foreign":
                _ = stage.rename(displaced)
                stage.mkdir()
            case "failed-stage":
                pass
            case unreachable:
                assert_never(unreachable)
        with pytest.raises(PublicationCommitContextError) as raised:
            _ = stage_retention.retain_stage(
                bound,
                output,
                names,
                rename_in_parent,
                lambda _descriptor: None,
                (),
                (),
            )

    # Then: both exact faults precede the authoritative typed retention error.
    assert_failure_order(
        raised.value,
        (primary, retention_fault, retention_error),
    )
    assert retention_error.__cause__ is retention_fault


__all__: tuple[str, ...] = ()
