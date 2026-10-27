"""Parent-bound validation and retention contract evidence."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.description_cache_publication_fixture import (
    assert_failure_order,
)
from gametool.description_cache_publication_errors import (
    PublicationCommitContextError,
)
from gametool.description_cache_publication_models import (
    RetainedCacheRecord,
    RetainedCacheRole,
)
from gametool.description_cache_publication_parent import ParentBoundValidator
from gametool.trusted_description_cache import (
    VerifiedDescriptionCache,
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
        "gametool.description_cache_publication_parent.require_parent_identity",
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


__all__: tuple[str, ...] = ()
