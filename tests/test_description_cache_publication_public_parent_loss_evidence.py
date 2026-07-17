"""Public result and error evidence when the publication parent is lost."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.description_cache_publication_fixture import (
    assert_failure_order,
    assert_live_retained_records,
    open_parent,
)
from tests.trusted_description_cache_fixture import published_cache
from w3xtool import description_cache_publication_evidence as publication_evidence
from w3xtool.description_cache_publication_errors import (
    DescriptionCachePublicationError,
    PublicationCommitContextError,
)
from w3xtool.description_cache_publication_models import (
    DescriptionCachePublicationProof,
    DescriptionCachePublicationResult,
    RetainedCacheExpectation,
    RetainedCacheRecord,
    RetainedCacheRole,
)
from w3xtool.description_cache_publication_named_leaf import (
    capture_named_transient,
)
from w3xtool.description_cache_publication_result_evidence import (
    require_live_result_evidence,
)
from w3xtool.trusted_description_cache import load_trusted_description_cache


def _identity(path: Path) -> tuple[int, int]:
    details = path.stat(follow_symlinks=False)
    return details.st_dev, details.st_ino


def test_result_boundary_parent_loss_reports_active_and_retained_as_transient(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: active and previous bytes are live below one held publication parent.
    parent = tmp_path / "publication"
    parent.mkdir()
    active = published_cache(tmp_path / "active-source").rename(parent / "active")
    previous = published_cache(tmp_path / "old-source", raw="first").rename(
        parent / "previous"
    )
    active_verified = load_trusted_description_cache(active)
    previous_verified = load_trusted_description_cache(previous)
    retained = RetainedCacheRecord(
        previous,
        RetainedCacheRole.PREVIOUS,
        *_identity(previous),
    )
    proof = DescriptionCachePublicationProof(
        DescriptionCachePublicationResult(active_verified, (retained,)),
        (RetainedCacheExpectation(retained, previous_verified),),
    )
    displaced = tmp_path / "held-parent"
    parent_fault = OSError("public parent lost")
    parent_error = PublicationCommitContextError(
        "public parent lost; NEEDS_CONTEXT",
        failures=(parent_fault,),
    )
    parent_error.__cause__ = parent_fault

    def lose_parent(
        _descriptor: int,
        current: Path,
        _expected: tuple[int, int],
    ) -> None:
        current.rename(displaced)
        current.mkdir()
        raise parent_error

    monkeypatch.setattr(publication_evidence, "require_parent_identity", lose_parent)

    # When: the success boundary re-proves caller-addressable evidence.
    with open_parent(parent) as descriptor:
        with pytest.raises(PublicationCommitContextError) as raised:
            _ = require_live_result_evidence(
                descriptor,
                parent,
                _identity(displaced if displaced.exists() else parent),
                active,
                _identity(active),
                proof,
                (parent / "stage", parent / "backup"),
            )

    # Then: no unaddressable retained path escapes; active is descriptor-proved.
    assert raised.value is parent_error
    assert raised.value.retained == ()
    assert_live_retained_records(raised.value.retained)
    transient = {(item.leaf_name, item.identity) for item in raised.value.transient}
    assert transient == {
        (active.name, _identity(displaced / active.name)),
        (previous.name, retained.identity),
    }
    assert tuple(parent.iterdir()) == ()


def test_error_boundary_parent_loss_reports_active_and_retained_as_transient(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a typed failure already carries a live retained record and active proof.
    parent = tmp_path / "publication"
    parent.mkdir()
    active = published_cache(tmp_path / "active-source").rename(parent / "active")
    previous = published_cache(tmp_path / "old-source", raw="first").rename(
        parent / "previous"
    )
    retained = RetainedCacheRecord(
        previous,
        RetainedCacheRole.PREVIOUS,
        *_identity(previous),
    )
    original_fault = OSError("original")
    original = DescriptionCachePublicationError(
        "original publication failure",
        (retained,),
        failures=(original_fault,),
    )
    displaced = tmp_path / "held-parent"
    parent_fault = OSError("public parent lost")
    parent_error = PublicationCommitContextError(
        "public parent lost; NEEDS_CONTEXT",
        failures=(parent_fault,),
    )
    parent_error.__cause__ = parent_fault

    def lose_parent(
        _descriptor: int,
        current: Path,
        _expected: tuple[int, int],
    ) -> None:
        current.rename(displaced)
        current.mkdir()
        raise parent_error

    # When: error evidence is finalized after the public binding disappears.
    with open_parent(parent) as descriptor:
        active_evidence = capture_named_transient(
            descriptor,
            parent,
            _identity(parent),
            active,
        )
        monkeypatch.setattr(
            publication_evidence, "require_parent_identity", lose_parent
        )
        finalized = publication_evidence.finalize_error_evidence(
            descriptor,
            parent,
            _identity(parent),
            original,
            parent_loss_evidence=active_evidence,
        )

    # Then: the exact original/final faults stay ordered beside demoted evidence.
    assert finalized is parent_error
    assert finalized.retained == ()
    assert_live_retained_records(finalized.retained)
    assert_failure_order(finalized, (original_fault, original, parent_fault))
    transient = {(item.leaf_name, item.identity) for item in finalized.transient}
    assert transient == {
        (active.name, _identity(displaced / active.name)),
        (previous.name, retained.identity),
    }
    assert tuple(parent.iterdir()) == ()


__all__: tuple[str, ...] = ()
