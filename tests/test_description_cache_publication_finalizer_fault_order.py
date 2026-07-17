"""Three-fault ordering through shared publication evidence finalization."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Never, assert_never

import pytest

from tests.description_cache_publication_fixture import bound_stage, open_parent
from w3xtool import (
    description_cache_publication_backup_finalization as backup_finalization,
)
from w3xtool import description_cache_publication_evidence as publication_evidence
from w3xtool import description_cache_publication_named_leaf as named_leaf
from w3xtool import description_cache_publication_recovery_state as recovery_state
from w3xtool import description_cache_publication_stage as publication_stage
from w3xtool import description_cache_publication_stage_normalization as normalization
from w3xtool.description_cache_publication_errors import PublicationCommitContextError
from w3xtool.description_cache_publication_models import (
    NamedLeafProof,
    RetainedCacheRecord,
    RetainedCacheRole,
)
from w3xtool.description_cache_publication_retention_durability import retain_durably
from w3xtool.description_cache_publication_retention_names import RetainedCacheNames


type FinalizerSite = Literal[
    "durable-sync",
    "recovery-sync",
    "stage-collision-evidence",
    "backup-evidence",
]


def _identity(path: Path) -> tuple[int, int]:
    details = path.stat(follow_symlinks=False)
    return details.st_dev, details.st_ino


@pytest.mark.parametrize(
    "site",
    (
        "durable-sync",
        "recovery-sync",
        "stage-collision-evidence",
        "backup-evidence",
    ),
)
def test_shared_finalizer_preserves_three_faults_in_observation_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    site: FinalizerSite,
) -> None:
    # Given: a real boundary records primary and secondary faults before final proof.
    source = tmp_path / "source"
    stage = tmp_path / "stage"
    output = tmp_path / "output"
    source.mkdir()
    names = RetainedCacheNames(tmp_path, "1" * 32)
    match site:
        case "stage-collision-evidence":
            primary_fault: Exception = FileExistsError("stage collision")
        case "durable-sync" | "recovery-sync" | "backup-evidence":
            primary_fault = OSError(f"{site} primary")
        case unreachable:
            assert_never(unreachable)
    secondary_fault = OSError(f"{site} secondary")
    finalizer_fault = OSError(f"{site} final parent")
    finalizer_error = PublicationCommitContextError(
        "terminal evidence parent proof; NEEDS_CONTEXT",
        failures=(finalizer_fault,),
    )
    finalizer_error.__cause__ = finalizer_fault
    events: list[str] = []

    def fail_final_parent(
        _descriptor: int,
        _parent: Path,
        _expected: tuple[int, int],
    ) -> Never:
        events.append("finalizer")
        raise finalizer_error

    monkeypatch.setattr(
        publication_evidence,
        "require_parent_identity",
        fail_final_parent,
    )

    # When: the selected boundary reaches the shared terminal finalizer.
    with pytest.raises(PublicationCommitContextError) as raised:
        match site:
            case "durable-sync":

                def fail_move(_descriptor: int, _source: str, _target: str) -> Never:
                    events.append("primary")
                    raise primary_fault

                def fail_sync(_descriptor: int) -> Never:
                    events.append("secondary")
                    raise secondary_fault

                with open_parent(tmp_path) as descriptor:
                    _ = retain_durably(
                        descriptor,
                        tmp_path,
                        _identity(tmp_path),
                        source,
                        _identity(source),
                        names,
                        RetainedCacheRole.RECOVERY,
                        fail_move,
                        fail_sync,
                    )
            case "recovery-sync":

                def fail_sync(_descriptor: int) -> Never:
                    events.append("secondary")
                    raise secondary_fault

                def unused_retain(
                    _path: Path,
                    _expected: tuple[int, int],
                    _role: RetainedCacheRole,
                ) -> RetainedCacheRecord:
                    raise AssertionError("empty candidate set must not retain")

                events.append("primary")
                with open_parent(tmp_path) as descriptor:
                    _ = recovery_state.normalize_recovery_failure(
                        descriptor,
                        tmp_path,
                        _identity(tmp_path),
                        (),
                        _identity(source),
                        (),
                        (),
                        (primary_fault,),
                        names,
                        unused_retain,
                        fail_sync,
                    )
            case "stage-collision-evidence":

                def fail_mkdir(
                    _name: str,
                    mode: int,
                    *,
                    dir_fd: int,
                ) -> Never:
                    del mode, dir_fd
                    events.append("primary")
                    raise primary_fault

                def fail_stage_read(_descriptor: int, _name: str) -> NamedLeafProof:
                    events.append("secondary")
                    return NamedLeafProof(False, None, secondary_fault)

                monkeypatch.setattr(publication_stage.os, "mkdir", fail_mkdir)
                monkeypatch.setattr(normalization, "read_named_leaf", fail_stage_read)
                _ = publication_stage.create_stage_and_capture(
                    stage,
                    output,
                    names,
                    lambda _descriptor, _source, _target: None,
                    lambda _descriptor: None,
                )
            case "backup-evidence":

                def fail_backup_read(_descriptor: int, _name: str) -> NamedLeafProof:
                    events.append("primary")
                    return NamedLeafProof(False, None, primary_fault)

                def fail_evidence_read(_descriptor: int, _name: str) -> NamedLeafProof:
                    events.append("secondary")
                    return NamedLeafProof(False, None, secondary_fault)

                stage.mkdir()
                monkeypatch.setattr(
                    backup_finalization,
                    "read_named_leaf",
                    fail_backup_read,
                )
                monkeypatch.setattr(named_leaf, "read_named_leaf", fail_evidence_read)
                with bound_stage(stage) as bound:
                    _ = backup_finalization.retain_backup(
                        bound,
                        tmp_path / "backup",
                        names,
                        lambda _descriptor, _source, _target: None,
                        lambda _descriptor: None,
                    )
            case unreachable:
                assert_never(unreachable)

    # Then: wrapper objects may remain, but the three exact faults never reorder.
    observed = tuple(
        failure
        for failure in raised.value.failures
        if any(
            failure is wanted
            for wanted in (primary_fault, secondary_fault, finalizer_fault)
        )
    )
    assert len(observed) == 3
    assert all(
        actual is wanted
        for actual, wanted in zip(
            observed,
            (primary_fault, secondary_fault, finalizer_fault),
            strict=True,
        )
    )
    assert raised.value is finalizer_error
    assert finalizer_error.__cause__ is finalizer_fault
    assert events == ["primary", "secondary", "finalizer"]


__all__: tuple[str, ...] = ()
