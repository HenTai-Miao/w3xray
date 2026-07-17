"""Ordered multi-fault stage-creation normalization."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal, Never, assert_never

import pytest

from tests.description_cache_publication_fixture import (
    assert_failure_order,
    assert_live_retained_records,
    open_parent,
    rename_in_parent,
)
from w3xtool import description_cache_publication_evidence as publication_evidence
from w3xtool import description_cache_publication_stage_normalization as normalization
from w3xtool.description_cache_publication_errors import (
    PublicationCommitContextError,
)
from w3xtool.description_cache_publication_models import NamedLeafProof
from w3xtool.description_cache_publication_retention_names import RetainedCacheNames


type CreationSequence = Literal["parent", "read", "retention", "final-parent"]


def _identity(path: Path) -> tuple[int, int]:
    details = path.stat(follow_symlinks=False)
    return details.st_dev, details.st_ino


@pytest.mark.parametrize(
    "sequence",
    ("parent", "read", "retention", "final-parent"),
)
def test_creation_failure_matrix_preserves_exact_fault_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sequence: CreationSequence,
) -> None:
    # Given: one initiating fault precedes one distinct normalization fault.
    stage = tmp_path / "stage"
    output = tmp_path / "output"
    stage.mkdir()
    stage_identity = _identity(stage)
    parent_identity = _identity(tmp_path)
    names = RetainedCacheNames(tmp_path, "1" * 32)
    initiating = RuntimeError("initiating creation fault")
    later = OSError(f"{sequence} normalization fault")
    expected: tuple[Exception, ...]
    terminal_cause: Exception | None = None

    match sequence:
        case "parent":
            parent_error = PublicationCommitContextError(
                "parent normalization; NEEDS_CONTEXT",
                failures=(later,),
            )
            parent_error.__cause__ = later

            def fail_parent(
                _descriptor: int,
                _parent: Path,
                _expected: tuple[int, int],
            ) -> None:
                raise parent_error

            monkeypatch.setattr(normalization, "require_parent_identity", fail_parent)
            expected = (initiating, later, parent_error)
        case "read":

            def fail_read(_descriptor: int, _name: str) -> NamedLeafProof:
                return NamedLeafProof(False, None, later)

            monkeypatch.setattr(normalization, "read_named_leaf", fail_read)
            expected = (initiating, later)
        case "retention":
            retention_error = PublicationCommitContextError(
                "retention normalization; NEEDS_CONTEXT",
                failures=(later,),
            )
            retention_error.__cause__ = later

            def fail_retention(
                *_args: int | Path | tuple[int, int] | RetainedCacheNames,
            ) -> Never:
                raise retention_error

            monkeypatch.setattr(normalization, "retain_durably", fail_retention)
            expected = (initiating, later)
            terminal_cause = later
        case "final-parent":
            final_error = PublicationCommitContextError(
                "final evidence parent; NEEDS_CONTEXT",
                failures=(later,),
            )
            final_error.__cause__ = later
            checks = 0
            real_parent_check = publication_evidence.require_parent_identity

            def fail_second_evidence_parent(
                descriptor: int,
                parent: Path,
                expected_identity: tuple[int, int],
            ) -> None:
                nonlocal checks
                checks += 1
                if checks == 2:
                    raise final_error
                real_parent_check(descriptor, parent, expected_identity)

            monkeypatch.setattr(
                publication_evidence,
                "require_parent_identity",
                fail_second_evidence_parent,
            )
            expected = (initiating,)
            terminal_cause = later
        case unreachable:
            assert_never(unreachable)

    # When: creation normalization reaches the selected later boundary.
    with open_parent(tmp_path) as descriptor:
        with pytest.raises(PublicationCommitContextError) as raised:
            normalization.raise_normalized_stage_creation_failure(
                descriptor,
                stage,
                output,
                parent_identity,
                stage_identity,
                stage_identity,
                names,
                rename_in_parent,
                os.fsync,
                initiating,
            )

    # Then: every exact object appears once in operation order.
    match sequence:
        case "final-parent":
            assert len(raised.value.failures) == 3
            assert raised.value.failures[0] is initiating
            assert type(raised.value.failures[1]) is PublicationCommitContextError
            assert raised.value.failures[2] is later
        case "parent" | "read" | "retention":
            assert_failure_order(raised.value, expected)
        case unreachable:
            assert_never(unreachable)
    assert raised.value.__cause__ is terminal_cause
    assert_live_retained_records(raised.value.retained)


__all__: tuple[str, ...] = ()
