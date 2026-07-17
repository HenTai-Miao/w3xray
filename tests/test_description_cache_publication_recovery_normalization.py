"""Ordered faults while normalizing a partial rollback."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pytest

from tests.description_cache_publication_fixture import (
    assert_failure_order,
    exchange_in_parent,
    open_parent,
    rename_in_parent,
)
from tests.trusted_description_cache_fixture import published_cache
from w3xtool import description_cache_publication_evidence as publication_evidence
from w3xtool import description_cache_publication_recovery as recovery
from w3xtool import description_cache_publication_recovery_state as recovery_state
from w3xtool.description_cache_publication_errors import (
    DescriptionCachePublicationError,
    PublicationCommitContextError,
)
from w3xtool.description_cache_publication_models import (
    RetainedCacheRecord,
    RetainedCacheRole,
)
from w3xtool.description_cache_publication_retention_names import RetainedCacheNames
from w3xtool.trusted_description_cache import (
    VerifiedDescriptionCache,
    load_trusted_description_cache,
)


@dataclass(frozen=True, slots=True)
class _NormalizationCase:
    label: str
    retention: bool = False
    sync: bool = False
    evidence: bool = False
    parent: bool = False


_CASES: Final = (
    _NormalizationCase("retention", retention=True),
    _NormalizationCase("sync", sync=True),
    _NormalizationCase("evidence", evidence=True),
    _NormalizationCase("parent", parent=True),
)


def _identity(path: Path) -> tuple[int, int]:
    details = path.stat(follow_symlinks=False)
    return details.st_dev, details.st_ino


@pytest.mark.parametrize("case", _CASES, ids=lambda item: item.label)
def test_recovery_normalization_keeps_original_then_normalization_fault(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: _NormalizationCase,
) -> None:
    # Given: reverse exchange completes before a typed rollback error escapes.
    old_source = published_cache(tmp_path / "old-source", raw="first")
    new_source = published_cache(tmp_path / "new-source", raw="second")
    output = new_source.rename(tmp_path / "trusted")
    names = RetainedCacheNames(tmp_path, "1" * 32)
    recovery_path = old_source.rename(names.path(RetainedCacheRole.RECOVERY))
    stage = tmp_path / ".w3xray-description-cache-stage-1"
    old_identity = _identity(recovery_path)
    new_identity = _identity(output)
    seed_fault = OSError("existing primary ledger")
    primary_error = DescriptionCachePublicationError(
        "rollback fault",
        failures=(seed_fault,),
    )
    normalization_fault = OSError(f"{case.label} normalization")
    normalization_error = PublicationCommitContextError(
        f"{case.label} normalization; NEEDS_CONTEXT",
        failures=(normalization_fault,),
    )
    normalization_error.__cause__ = normalization_fault

    def exchange_then_raise(descriptor: int, source: str, target: str) -> None:
        exchange_in_parent(descriptor, source, target)
        raise primary_error

    def validate(path: Path) -> VerifiedDescriptionCache:
        return load_trusted_description_cache(path)

    parent_checks = 0
    original_parent_check = publication_evidence.require_parent_identity

    def parent_check(
        descriptor: int,
        parent: Path,
        expected: tuple[int, int],
    ) -> None:
        nonlocal parent_checks
        parent_checks += 1
        if case.parent and parent_checks == 1:
            raise normalization_error
        original_parent_check(descriptor, parent, expected)

    monkeypatch.setattr(
        publication_evidence,
        "require_parent_identity",
        parent_check,
    )
    if case.evidence:

        def fail_evidence(
            descriptor: int,
            parent: Path,
            parent_identity: tuple[int, int],
            records: tuple[RetainedCacheRecord, ...],
        ) -> tuple[RetainedCacheRecord, ...]:
            del descriptor, parent, parent_identity, records
            raise normalization_error

        monkeypatch.setattr(
            recovery_state,
            "require_live_retained_evidence",
            fail_evidence,
        )

    # When: retention, sync, evidence, or parent proof faults during normalization.
    with open_parent(tmp_path) as descriptor:

        def retain(
            path: Path,
            current: tuple[int, int],
            role: RetainedCacheRole,
        ) -> RetainedCacheRecord:
            if case.retention:
                raise normalization_error
            target = names.path(role)
            rename_in_parent(descriptor, path.name, target.name)
            return RetainedCacheRecord(target, role, *current)

        def sync(_descriptor: int) -> None:
            if case.sync:
                raise normalization_fault

        with pytest.raises(PublicationCommitContextError) as raised:
            _ = recovery.restore_previous_generation(
                descriptor,
                _identity(tmp_path),
                output,
                new_identity,
                recovery_path,
                old_identity,
                stage,
                names,
                exchange_then_raise,
                rename_in_parent,
                validate,
                retain,
                sync,
                (),
                (),
                "ordered normalization audit",
            )

    # Then: existing primary evidence precedes the exact normalization object.
    assert_failure_order(
        raised.value,
        (seed_fault, primary_error, normalization_fault),
    )
    if case.sync:
        assert raised.value.__cause__ is None
        assert raised.value.__context__ is normalization_fault
    else:
        assert raised.value.__cause__ is normalization_fault


__all__: tuple[str, ...] = ()
