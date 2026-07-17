"""Ordinary exception coverage for creation and transaction boundaries."""

from __future__ import annotations

from collections.abc import Callable, Sequence
import os
from pathlib import Path
from typing import Literal, Never, assert_never

import pytest

from tests.description_cache_publication_fixture import (
    assert_live_retained_records,
    rename_in_parent,
    transient_publication_paths,
)
from w3xtool import description_cache_publication as publication
from w3xtool import description_cache_publication_stage as publication_stage
from w3xtool import description_cache_publication_stage_finalization as finalization
from w3xtool.description_cache_migration_models import (
    DescriptionCacheRejection,
    ProvenDescriptionCandidate,
)
from w3xtool.description_cache_publication_errors import (
    DescriptionCachePublicationError,
)
from w3xtool.description_cache_publication_models import (
    RetainedCacheRecord,
    RetainedCacheRole,
)
from w3xtool.description_cache_publication_private_attempt import PrivateAttempt
from w3xtool.description_cache_publication_retention_names import RetainedCacheNames
from w3xtool.description_cache_publication_stage import BoundDescriptionCacheStage
from w3xtool.trusted_description_cache_models import TrustedCacheLeafProof


type TransactionSite = Literal["build", "validation", "absent-proof"]
type FaultType = type[ValueError] | type[RuntimeError]


def _observe_private_attempts(
    monkeypatch: pytest.MonkeyPatch,
    attempts: list[str],
) -> None:
    original = finalization.attempt_private

    def observe(
        bound: BoundDescriptionCacheStage,
        path: Path,
        held_identity: tuple[int, int] | None,
        operation: Callable[[], RetainedCacheRecord | None],
    ) -> PrivateAttempt:
        attempts.append("backup" if held_identity is None else "stage")
        return original(bound, path, held_identity, operation)

    monkeypatch.setattr(finalization, "attempt_private", observe)


def _assert_fault_is_ledgered(
    error: DescriptionCachePublicationError,
    fault: Exception,
) -> None:
    assert sum(current is fault for current in error.failures) == 1
    assert error.__cause__ is not error


@pytest.mark.parametrize("fault_type", (ValueError, RuntimeError))
def test_stage_creation_ordinary_fault_is_normalized_with_exact_evidence(
    tmp_path: Path,
    fault_type: FaultType,
) -> None:
    # Given: stage creation has captured both descriptors before initial sync faults.
    stage = tmp_path / "stage"
    output = tmp_path / "trusted"
    names = RetainedCacheNames(tmp_path, "1" * 32)
    fault = fault_type("ordinary stage creation")
    sync_calls = 0

    def fail_initial_sync(descriptor: int) -> None:
        nonlocal sync_calls
        sync_calls += 1
        if sync_calls == 1:
            raise fault
        os.fsync(descriptor)

    # When: the created-stage boundary normalizes the exact held directory.
    with pytest.raises(DescriptionCachePublicationError) as raised:
        _ = publication_stage.create_stage_and_capture(
            stage,
            output,
            names,
            rename_in_parent,
            fail_initial_sync,
        )

    # Then: the ordinary object and the retained stage remain caller-observable.
    _assert_fault_is_ledgered(raised.value, fault)
    assert sync_calls >= 2
    assert len(raised.value.retained) == 1
    assert raised.value.retained[0].role is RetainedCacheRole.FAILED_STAGE
    assert_live_retained_records(raised.value.retained)


@pytest.mark.parametrize("fault_type", (ValueError, RuntimeError))
@pytest.mark.parametrize("site", ("build", "validation", "absent-proof"))
def test_transaction_ordinary_fault_still_attempts_both_private_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault_type: FaultType,
    site: TransactionSite,
) -> None:
    # Given: one real transaction boundary raises an untyped ordinary exception.
    output = tmp_path / "trusted"
    fault = fault_type(f"ordinary {site}")
    attempts: list[str] = []
    _observe_private_attempts(monkeypatch, attempts)

    match site:
        case "build":
            expected_role = RetainedCacheRole.FAILED_STAGE

            def fail_build(
                _source_root: Path,
                _stage_descriptor: int,
                _display_root: Path,
                _accepted: Sequence[ProvenDescriptionCandidate],
                _rejections: Sequence[DescriptionCacheRejection],
            ) -> Never:
                raise fault

            monkeypatch.setattr(
                publication, "build_description_cache_stage", fail_build
            )
        case "validation":
            expected_role = RetainedCacheRole.FAILED_STAGE

            def fail_validation(
                _descriptor: int,
                _display_root: Path,
                _expected_leaves: tuple[TrustedCacheLeafProof, ...],
            ) -> Never:
                raise fault

            monkeypatch.setattr(
                publication,
                "load_trusted_description_cache_from_descriptor",
                fail_validation,
            )
        case "absent-proof":
            expected_role = RetainedCacheRole.FAILED_OUTPUT
            original_validation = publication._require_valid_at
            injected = False

            def fail_output_proof(descriptor: int, path: Path):
                nonlocal injected
                if path == output and not injected:
                    injected = True
                    raise fault
                return original_validation(descriptor, path)

            monkeypatch.setattr(publication, "_require_valid_at", fail_output_proof)
        case unreachable:
            assert_never(unreachable)

    # When: the top transaction evidence boundary handles the ordinary exception.
    with pytest.raises(DescriptionCachePublicationError) as raised:
        _ = publication.publish_description_cache(tmp_path, output, (), ())

    # Then: backup and held-stage normalization both ran and exact evidence survived.
    _assert_fault_is_ledgered(raised.value, fault)
    assert attempts == ["backup", "stage"]
    assert any(record.role is expected_role for record in raised.value.retained)
    assert_live_retained_records(raised.value.retained)
    assert not output.exists()
    assert transient_publication_paths(output) == ()


__all__: tuple[str, ...] = ()
