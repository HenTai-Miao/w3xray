"""Failure-ledger handoff at replacement rollback entry points."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from tests.trusted_description_cache_fixture import published_cache
from w3xtool import description_cache_publication_replacement as replacement
from w3xtool import description_cache_publication_rollback_handoff as rollback_handoff
from w3xtool.description_cache_publication_errors import (
    PublicationCommitContextError,
)
from w3xtool.description_cache_publication_models import (
    DescriptionCachePublicationProof,
    RetainedCacheRecord,
    RetainedCacheRole,
)
from w3xtool.description_cache_publication_retention_names import RetainedCacheNames
from w3xtool.trusted_description_cache import (
    VerifiedDescriptionCache,
    load_trusted_description_cache,
)


type Exchange = Callable[[int, str, str], None]
type Rename = Callable[[int, str, str], None]
type Sync = Callable[[int], None]
type Validate = Callable[[Path], VerifiedDescriptionCache]
type BoundRetain = Callable[
    [Path, tuple[int, int], RetainedCacheRole],
    RetainedCacheRecord,
]


def _publish_with_exchange(tmp_path: Path, exchange: Exchange) -> None:
    verified = load_trusted_description_cache(
        published_cache(tmp_path / "verified", raw="verified")
    )
    names = RetainedCacheNames(tmp_path, "1" * 32)

    def unexpected_rename(_descriptor: int, _source: str, _target: str) -> None:
        raise AssertionError("unexpected no-replace rename")

    def unexpected_validate(_path: Path) -> VerifiedDescriptionCache:
        raise AssertionError("unexpected validation")

    def unexpected_retain(
        _path: Path,
        _identity: tuple[int, int],
        _role: RetainedCacheRole,
    ) -> RetainedCacheRecord:
        raise AssertionError("unexpected retention")

    def unexpected_sync(_descriptor: int) -> None:
        raise AssertionError("unexpected parent sync")

    _: DescriptionCachePublicationProof = replacement.publish_replacement(
        0,
        (1, 1),
        tmp_path / "stage",
        (2, 2),
        verified,
        tmp_path / "output",
        (3, 3),
        verified,
        tmp_path / "backup",
        names,
        exchange,
        unexpected_rename,
        unexpected_validate,
        unexpected_retain,
        unexpected_sync,
    )


def test_rollback_failure_ledgers_initiating_failure_before_recovery_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: replacement initiation fails and typed recovery has its own cause/ledger.
    initiating_failure = OSError("initial exchange failure")
    recovery_failure = OSError("reverse exchange failure")
    normalization_failure = OSError("recovery normalization failure")
    recovery_error = PublicationCommitContextError(
        "rollback failed; NEEDS_CONTEXT",
        failures=(recovery_failure, normalization_failure),
    )
    recovery_error.__cause__ = recovery_failure

    def fail_exchange(_descriptor: int, _source: str, _target: str) -> None:
        raise initiating_failure

    def fail_restore(
        parent_descriptor: int,
        parent_identity: tuple[int, int],
        output: Path,
        staged_identity: tuple[int, int],
        recovery: Path,
        previous_identity: tuple[int, int],
        stage: Path,
        names: RetainedCacheNames,
        rename_exchange: Exchange,
        rename_noreplace: Rename,
        require_valid: Validate,
        retain: BoundRetain,
        sync_parent: Sync,
        detail: str,
    ) -> RetainedCacheRecord:
        del (
            parent_descriptor,
            parent_identity,
            output,
            staged_identity,
            recovery,
            previous_identity,
            stage,
            names,
            rename_exchange,
            rename_noreplace,
            require_valid,
            retain,
            sync_parent,
            detail,
        )
        raise recovery_error

    monkeypatch.setattr(rollback_handoff, "restore_replacement", fail_restore)

    # When: the replacement rollback handoff receives the typed recovery error.
    with pytest.raises(PublicationCommitContextError) as raised:
        _publish_with_exchange(tmp_path, fail_exchange)

    # Then: initiating, recovery, and normalization events remain exact and ordered.
    assert raised.value is recovery_error
    assert raised.value.failures == (
        initiating_failure,
        recovery_failure,
        normalization_failure,
    )
    assert raised.value.__cause__ is recovery_failure


def test_second_rollback_identity_read_ledgers_both_proof_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: the displaced-name proof and its immediate identity reread both fail.
    initiating_failure = OSError("displaced proof failure")
    reread_failure = OSError("displaced identity reread failure")
    identity_proofs = 0

    def exchange(_descriptor: int, _source: str, _target: str) -> None:
        return

    def prove_identity(
        _descriptor: int,
        _name: str,
        _expected: tuple[int, int],
    ) -> None:
        nonlocal identity_proofs
        identity_proofs += 1
        if identity_proofs == 2:
            raise initiating_failure

    def fail_reread(_descriptor: int, _name: str) -> tuple[int, int]:
        raise reread_failure

    monkeypatch.setattr(replacement, "require_replacement_identity", prove_identity)
    monkeypatch.setattr(rollback_handoff, "object_identity", fail_reread)

    # When: rollback cannot even establish the displaced identity.
    with pytest.raises(PublicationCommitContextError) as raised:
        _publish_with_exchange(tmp_path, exchange)

    # Then: the typed ledger explicitly records both observations in event order.
    assert raised.value.failures == (initiating_failure, reread_failure)
    assert raised.value.__cause__ is reread_failure


__all__: tuple[str, ...] = ()
