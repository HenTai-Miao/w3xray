"""Parent-bound validation and retention contract evidence."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.description_cache_publication_fixture import (
    assert_failure_order,
    assert_live_retained_records,
    open_parent,
)
from w3xtool import description_cache_publication_evidence as publication_evidence
from w3xtool.description_cache_publication_errors import (
    PublicationCommitContextError,
    RetainedObjectInstalledContextError,
)
from w3xtool.description_cache_publication_models import (
    RetainedCacheRecord,
    RetainedCacheRole,
)
from w3xtool.description_cache_publication_parent import ParentBoundValidator
from w3xtool.trusted_description_cache import (
    VerifiedDescriptionCache,
    load_trusted_description_cache,
)


def _identity(path: Path) -> tuple[int, int]:
    details = path.stat(follow_symlinks=False)
    return details.st_dev, details.st_ino


def test_parent_bound_validation_and_parent_proof_keep_both_faults(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: validation faults before the subsequent bound-parent proof faults.
    validation_fault = OSError("validation")
    parent_fault = OSError("parent proof")
    parent_error = PublicationCommitContextError(
        "parent proof; NEEDS_CONTEXT",
        failures=(parent_fault,),
    )
    parent_error.__cause__ = parent_fault
    checks = 0

    def check_parent(
        _descriptor: int, _parent: Path, _expected: tuple[int, int]
    ) -> None:
        nonlocal checks
        checks += 1
        if checks == 2:
            raise parent_error

    def reject_validation(
        _descriptor: int,
        _path: Path,
    ) -> VerifiedDescriptionCache:
        raise validation_fault

    def unused_retainer(
        _descriptor: int,
        _path: Path,
        _expected: tuple[int, int],
        _role: RetainedCacheRole,
    ) -> RetainedCacheRecord:
        raise AssertionError("validation must not retain")

    monkeypatch.setattr(
        "w3xtool.description_cache_publication_parent.require_parent_identity",
        check_parent,
    )
    binding = ParentBoundValidator(
        101,
        tmp_path,
        _identity(tmp_path),
        reject_validation,
        unused_retainer,
    )

    # When: the validator re-proves its parent after the validation failure.
    with pytest.raises(PublicationCommitContextError) as raised:
        _ = binding.require_valid(tmp_path / "trusted")

    # Then: the exact parent error and its cause survive the ordered ledger.
    assert raised.value is parent_error
    assert_failure_order(raised.value, (validation_fault, parent_fault))
    assert raised.value.__cause__ is parent_fault


def test_parent_bound_retained_install_keeps_finalized_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: retention installs a live record before two parent proofs fail.
    retained_path = tmp_path / "retained"
    retained_path.mkdir()
    retained = RetainedCacheRecord(
        retained_path,
        RetainedCacheRole.PREVIOUS,
        *_identity(retained_path),
    )
    first_fault = OSError("first parent")
    final_fault = OSError("final parent")
    first_error = PublicationCommitContextError(
        "first parent; NEEDS_CONTEXT",
        failures=(first_fault,),
    )
    first_error.__cause__ = first_fault
    final_error = PublicationCommitContextError(
        "final parent; NEEDS_CONTEXT",
        failures=(final_fault,),
    )
    final_error.__cause__ = final_fault
    checks = 0

    def bound_parent(
        _descriptor: int,
        _parent: Path,
        _expected: tuple[int, int],
    ) -> None:
        nonlocal checks
        checks += 1
        if checks == 2:
            raise first_error

    def final_parent(
        _descriptor: int,
        _parent: Path,
        _expected: tuple[int, int],
    ) -> None:
        raise final_error

    def validator(
        _descriptor: int,
        path: Path,
    ) -> VerifiedDescriptionCache:
        return load_trusted_description_cache(path)

    def install(
        _descriptor: int,
        _path: Path,
        _expected: tuple[int, int],
        _role: RetainedCacheRole,
    ) -> RetainedCacheRecord:
        return retained

    monkeypatch.setattr(
        "w3xtool.description_cache_publication_parent.require_parent_identity",
        bound_parent,
    )
    monkeypatch.setattr(publication_evidence, "require_parent_identity", final_parent)

    # When: the bound adapter finalizes evidence after its post-install proof fails.
    with open_parent(tmp_path) as descriptor:
        binding = ParentBoundValidator(
            descriptor,
            tmp_path,
            _identity(tmp_path),
            validator,
            install,
        )
        with pytest.raises(RetainedObjectInstalledContextError) as raised:
            _ = binding.retain(
                retained_path,
                retained.identity,
                RetainedCacheRole.PREVIOUS,
            )

    # Then: the finalized typed object and its original cause remain reachable.
    assert raised.value.installed is retained
    assert_failure_order(
        raised.value,
        (first_fault, first_error, final_fault, final_error),
    )
    assert final_error.__cause__ is final_fault
    assert_live_retained_records((raised.value.installed,))


__all__: tuple[str, ...] = ()
